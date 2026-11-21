from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import sqlite3
import statistics
import time as clock
import asyncio
from collections import Counter, deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parents[2]
SCORING = yaml.safe_load((ROOT / "scoring" / "weights.yaml").read_text())
assert abs(sum(SCORING["weights"].values()) - 1.0) < 1e-9, "scoring/weights.yaml weights must sum to 1"
DEMO = os.getenv("APP_MODE", "demo") == "demo"
DB_PATH = Path(os.getenv("CACHE_DB", str(ROOT / ".cache" / "public-cache.sqlite3")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(DB_PATH) as _db:
    _db.execute("CREATE TABLE IF NOT EXISTS cache(source TEXT,key TEXT,payload TEXT,fetched REAL,PRIMARY KEY(source,key))")
app = FastAPI(title="Boundless Boston Navigator API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","), allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

SOURCES = ["google_places", "mbta", "nws", "boston_ckan", "sports", "ticketmaster", "yelp", "overpass", "routing", "gemini", "census_acs", "gemini_explain"]  # gemini_explain: own breaker, so explain load cannot disable query parsing
HEALTH: dict[str, dict[str, Any]] = {s: {"source": s, "status": "demo" if DEMO and s in SOURCES[:4] else "disabled", "checked_at": None, "last_success_at": None, "cache_age_s": None, "detail": "Fixture mode" if DEMO and s in SOURCES[:4] else "Not configured"} for s in SOURCES}
FAILURES: dict[str, int] = {s: 0 for s in SOURCES}
OPEN_UNTIL: dict[str, float] = {}
HALF_OPEN_PROBES: set[str] = set()
TTL = {"google_places": 300, "mbta": 60, "nws": 600, "boston_ckan": 3600}
CKAN_BASE = os.getenv("BOSTON_CKAN_URL", "https://data.boston.gov/api/3/action")
MBTA_BASE = "https://api-v3.mbta.com"
# Riders say "Green Line D", not "Green-D": Boston line names with the MBTA's official line colors.
MBTA_LINES = {"Red": ("Red Line", "#DA291C"), "Mattapan": ("Mattapan Trolley", "#DA291C"), "Orange": ("Orange Line", "#ED8B00"),
              "Blue": ("Blue Line", "#003DA5"), **{f"Green-{b}": (f"Green Line {b}", "#00843D") for b in "BCDE"}}
SILVER_LINES = {"741": "SL1", "742": "SL2", "743": "SL3", "751": "SL4", "749": "SL5", "746": "SLW"}
MODE_RANK = {"subway": 0, "silver": 1, "bus": 2, "commuter_rail": 3, "ferry": 4}  # prefer the T over buses, buses over Commuter Rail
MBTA_MAX_ROUTE_TRIES = 6  # each route tried costs ~8 MBTA calls; stay well under the rate limit
MIN_STAY = timedelta(hours=1)  # earliest return considered after setting out

def mbta_line(route_id: str) -> dict[str, str]:
    if route_id in MBTA_LINES:
        (name, color), mode = MBTA_LINES[route_id], "subway"
    elif route_id in SILVER_LINES:
        name, color, mode = f"Silver Line {SILVER_LINES[route_id]}", "#7C878E", "silver"
    elif route_id.startswith("CR-"):
        name, color, mode = f"{route_id[3:].replace('-', ' ')} Line (Commuter Rail)", "#80276C", "commuter_rail"
    elif route_id.startswith("Boat-"):
        name, color, mode = "MBTA Ferry", "#008EAA", "ferry"
    elif route_id.startswith("Shuttle"):
        name, color, mode = "Shuttle bus", "#FFC72C", "bus"
    else:
        name, color, mode = f"Bus {route_id}", "#FFC72C", "bus"
    return {"id": route_id, "name": name, "color": color, "mode": mode}

def mbta_service_end(t: datetime) -> datetime:
    """End of the MBTA service day containing t; service days run 03:00 to 02:59 next morning."""
    zone = ZoneInfo("America/New_York")
    local = t.astimezone(zone)
    day = local.date() - timedelta(days=1) if local.hour < 3 else local.date()
    return datetime.combine(day + timedelta(days=1), datetime.min.time(), zone).replace(hour=3)

CKAN_RESOURCES: dict[str, dict[str, Any]] = {}
CKAN_RESOLVED_AT = 0.0

class QueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    free_text: str | None = Field(default=None, max_length=300)
    time: datetime
    budget: Literal["$", "$$", "$$$"]
    lat: float
    lng: float
    max_walk_min: int = Field(ge=1, le=120)  # the trip-time limit: door to door, on foot or by T
    travel: Literal["walk", "walk_t"] = "walk_t"
    weather_override: Literal["clear", "rain", "cold"] | None = None

    @field_validator("lat")
    @classmethod
    def valid_lat(cls, v: float) -> float:
        if not math.isfinite(v) or not -90 <= v <= 90: raise ValueError("lat must be between -90 and 90")
        return v
    @field_validator("lng")
    @classmethod
    def valid_lng(cls, v: float) -> float:
        if not math.isfinite(v) or not -180 <= v <= 180: raise ValueError("lng must be between -180 and 180")
        return v
    @field_validator("time")
    @classmethod
    def within_day(cls, v: datetime) -> datetime:
        if v.tzinfo is None: raise ValueError("time must include a timezone")
        now = datetime.now(timezone.utc)
        if not now <= v.astimezone(timezone.utc) <= now + timedelta(hours=24): raise ValueError("time must be within the next 24 hours")
        return v

FIXTURES = [
 {"id":"demo-tatte","name":"Tatte Bakery & Cafe","lat":42.3548,"lng":-71.0601,"address":"1 Boston Wharf Rd, Boston","categories":["cafe","bakery"],"price_level":2,"rating":4.4,"review_count":820,"open_hours":{"status_at_requested_time":"open"},"indoor_outdoor":"indoor","walk_min":8,"source_refs":[{"source":"google_places","external_id":"demo-tatte"}],"attributions":[{"source":"google_places","text":"Demo venue data · Google Places attribution required in live mode","translate_no":True}],"momentum_delta":7},
 {"id":"demo-tatte-2","name":"Thinking Cup","lat":42.3552,"lng":-71.0620,"address":"236 Hanover St, Boston","categories":["cafe","dessert"],"price_level":2,"rating":4.3,"review_count":410,"open_hours":{"status_at_requested_time":"open"},"indoor_outdoor":"indoor","walk_min":12,"source_refs":[{"source":"google_places","external_id":"demo-thinking-cup"}],"attributions":[{"source":"google_places","text":"Demo venue data · Google Places attribution required in live mode","translate_no":True}],"momentum_delta":4},
 {"id":"demo-pizza","name":"Regina Pizzeria","lat":42.3654,"lng":-71.0568,"address":"11 1/2 Thacher St, Boston","categories":["pizza","restaurant"],"price_level":2,"rating":4.5,"review_count":1600,"open_hours":{"status_at_requested_time":"open"},"indoor_outdoor":"indoor","walk_min":19,"source_refs":[{"source":"google_places","external_id":"demo-regina"}],"attributions":[{"source":"google_places","text":"Demo venue data · Google Places attribution required in live mode","translate_no":True}],"momentum_delta":3},
 {"id":"demo-noodle","name":"Pho Pasteur","lat":42.3512,"lng":-71.0629,"address":"682 Washington St, Boston","categories":["vietnamese","noodles"],"price_level":1,"rating":4.1,"review_count":980,"open_hours":{"status_at_requested_time":"open"},"indoor_outdoor":"indoor","walk_min":14,"source_refs":[{"source":"google_places","external_id":"demo-pho"}],"attributions":[{"source":"google_places","text":"Demo venue data · Google Places attribution required in live mode","translate_no":True}],"momentum_delta":8},
 {"id":"demo-public-garden","name":"Boston Public Garden","lat":42.3540,"lng":-71.0700,"address":"4 Charles St, Boston","categories":["park","outdoors"],"price_level":1,"rating":4.8,"review_count":5200,"open_hours":{"status_at_requested_time":"open"},"indoor_outdoor":"outdoor","walk_min":10,"source_refs":[{"source":"google_places","external_id":"demo-garden"}],"attributions":[{"source":"google_places","text":"Demo venue data · Google Places attribution required in live mode","translate_no":True}],"momentum_delta":10},
 {"id":"demo-restaurant","name":"Union Oyster House","lat":42.3610,"lng":-71.0562,"address":"41 Union St, Boston","categories":["seafood","restaurant"],"price_level":3,"rating":4.2,"review_count":2100,"open_hours":{"status_at_requested_time":"closed"},"indoor_outdoor":"indoor","walk_min":17,"source_refs":[{"source":"google_places","external_id":"demo-union"}],"attributions":[{"source":"google_places","text":"Demo venue data · Google Places attribution required in live mode","translate_no":True}],"momentum_delta":2},
 {"id":"demo-pinocchios","name":"Pinocchio's Pizza & Subs","lat":42.3721,"lng":-71.1206,"address":"74 Winthrop St, Cambridge","categories":["pizza","restaurant"],"price_level":1,"rating":4.5,"review_count":1300,"open_hours":{"status_at_requested_time":"open"},"indoor_outdoor":"indoor","walk_min":72,"source_refs":[{"source":"google_places","external_id":"demo-pinocchios"}],"attributions":[{"source":"google_places","text":"Demo venue data · Google Places attribution required in live mode","translate_no":True}],"momentum_delta":6},
 {"id":"demo-eventide","name":"Eventide Fenway","lat":42.3448,"lng":-71.0995,"address":"1321 Boylston St, Boston","categories":["seafood","restaurant"],"price_level":2,"rating":4.4,"review_count":900,"open_hours":{"status_at_requested_time":"open"},"indoor_outdoor":"indoor","walk_min":46,"source_refs":[{"source":"google_places","external_id":"demo-eventide"}],"attributions":[{"source":"google_places","text":"Demo venue data · Google Places attribution required in live mode","translate_no":True}],"momentum_delta":5},
 {"id":"demo-earls","name":"Earls Kitchen + Bar Assembly Row","lat":42.3925,"lng":-71.0790,"address":"450 Artisan Way, Somerville","categories":["restaurant","bar"],"price_level":2,"rating":4.3,"review_count":2500,"open_hours":{"status_at_requested_time":"open"},"indoor_outdoor":"indoor","walk_min":61,"source_refs":[{"source":"google_places","external_id":"demo-earls"}],"attributions":[{"source":"google_places","text":"Demo venue data · Google Places attribution required in live mode","translate_no":True}],"momentum_delta":3},
]
# Demo-mode T trips for the fixture venues beyond walking range:
# (from stop, to stop, route, ride min, last train back (local h, m), walk to first stop min, walk from last stop min).
DEMO_TRANSIT = {
    "demo-pinocchios": ("Park Street", "Harvard", "Red", 13, (0, 47), 3, 3),
    "demo-eventide": ("Park Street", "Fenway", "Green-D", 14, (0, 41), 3, 6),
    "demo-earls": ("Downtown Crossing", "Assembly", "Orange", 12, (0, 38), 3, 5),
}


def now_iso() -> str: return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
def source_use(source: str, status: str | None = None) -> dict[str, Any]:
    h = HEALTH[source]
    attributions = {
        "google_places": [{"source": source, "text": "Google Maps", "url": "https://maps.google.com", "required_logo": "Google Maps", "translate_no": True}],
        "mbta": [{"source": source, "text": "MBTA V3 API", "url": "https://api-v3.mbta.com/"}],
        "nws": [{"source": source, "text": "Weather data by the National Weather Service", "url": "https://www.weather.gov/"}],
        "boston_ckan": [{"source": source, "text": "City of Boston Open Data", "url": "https://data.boston.gov/"}],
        "sports": [{"source": source, "text": "Game schedules: MLB Stats API (© MLB Advanced Media) and NHL", "url": "https://statsapi.mlb.com/"}],
        "overpass": [{"source": source, "text": "© OpenStreetMap contributors (ODbL)", "url": "https://www.openstreetmap.org/copyright"}],
        "routing": [{"source": source, "text": "© openrouteservice.org by HeiGIT | Map data © OpenStreetMap contributors", "url": "https://openrouteservice.org/"}],
    }
    return {"source": source, "status": status or h["status"], "observed_at": h["last_success_at"], "cache_age_s": h["cache_age_s"], "attribution": attributions.get(source, [])}
def envelope(data: dict[str, Any], used: list[str]) -> dict[str, Any]:
    return {**data, "sources_used": [source_use(s) for s in used], "generated_at": now_iso()}

def cache_get(source: str, params: dict[str, Any]) -> Any | None:
    key = hashlib.sha256(json.dumps(params, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute("SELECT payload,fetched FROM cache WHERE source=? AND key=?", (source,key)).fetchone()
    if not row: return None
    age = clock.time() - row[1]
    if age > TTL.get(source, 600): return None
    HEALTH[source].update(status="cached", cache_age_s=round(age), last_success_at=datetime.fromtimestamp(row[1], timezone.utc).isoformat())
    return json.loads(row[0])

def cache_put(source: str, params: dict[str, Any], payload: Any) -> None:
    key = hashlib.sha256(json.dumps(params, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with sqlite3.connect(DB_PATH) as db:
        db.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?,?)", (source,key,json.dumps(payload),clock.time()))

def normalized_params(params: dict[str, Any]) -> dict[str, Any]:
    result = dict(params)
    for k in ("lat", "lng"):
        if k in result: result[k] = round(float(result[k]), 4)
    return result

def upstream_reason(response: httpx.Response) -> str:
    """Short, non-secret reason from a Google-style error body (status, ErrorInfo reason, quota names); '' otherwise."""
    try:
        err = response.json()["error"]
        parts = [str(err.get("status") or "")]
        for detail in err.get("details") or []:
            meta = detail.get("metadata") or {}
            parts += [str(detail.get("reason") or ""), str(meta.get("quota_metric") or ""), str(meta.get("quota_limit") or "")]
    except Exception:  # display-only: a malformed body must never break request_json or its breaker bookkeeping
        return ""
    return " ".join(p for p in parts if p)[:160]

async def request_json(source: str, url: str, params: dict[str, Any] | None = None,
                       headers: dict[str, str] | None = None, method: str = "GET",
                       json_body: dict[str, Any] | None = None, timeout: float = 4.0) -> Any | None:
    """One outbound HTTP path with bounded retries, cache, and per-source breaker."""
    if DEMO:
        return None
    params = params or {}
    cache_key = normalized_params({"url": url, "params": params, "body": json_body, "method": method})
    cache_allowed = source not in ("google_places", "gemini", "gemini_explain", "routing")  # Places terms; no user free text; ORS echoes origin + Places coordinates
    if clock.time() < OPEN_UNTIL.get(source, 0):
        cached_when_open = cache_get(source, cache_key) if cache_allowed else None
        HEALTH[source].update(status="open-circuit", detail="Circuit open for 60 seconds")
        return cached_when_open
    cached = cache_get(source, cache_key) if cache_allowed else None
    if cached is not None:
        HEALTH[source].update(status="cached")
        return cached
    if source in OPEN_UNTIL:
        if source in HALF_OPEN_PROBES:
            HEALTH[source].update(status="open-circuit", detail="Half-open probe already in progress")
            return None
        HALF_OPEN_PROBES.add(source)
    retryable_status = False
    last_code, last_reason = None, ""
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
                response = await client.request(method, url, params=params, headers=headers, json=json_body)
            last_code = response.status_code
            if response.status_code >= 400:
                last_reason = upstream_reason(response)
            retryable_status = response.status_code == 429 or response.status_code >= 500
            if retryable_status and attempt == 0:
                await asyncio.sleep(random.uniform(0.1, 0.4))
                continue
            response.raise_for_status()
            payload = response.json()
            if cache_allowed:
                cache_put(source, cache_key, payload)
            FAILURES[source] = 0
            OPEN_UNTIL.pop(source, None)
            HALF_OPEN_PROBES.discard(source)
            HEALTH[source].update(status="live", checked_at=now_iso(), last_success_at=now_iso(), cache_age_s=0, detail="")
            return payload
        except httpx.HTTPStatusError as exc:
            retryable_status = exc.response.status_code == 429 or exc.response.status_code >= 500
            if retryable_status and attempt == 0:
                await asyncio.sleep(random.uniform(0.1, 0.4))
                continue
            break
        except (httpx.TransportError, ValueError):  # TransportError covers timeouts, connect, protocol and proxy errors
            if attempt == 0:
                await asyncio.sleep(random.uniform(0.1, 0.4))
                continue
            break
    FAILURES[source] += 1
    HALF_OPEN_PROBES.discard(source)
    status = ("upstream unavailable" if retryable_status else "upstream request failed") + (f" (HTTP {last_code}{': ' + last_reason if last_reason else ''})" if last_code else " (no response)")
    HEALTH[source].update(status="disabled", checked_at=now_iso(), detail=status)
    if FAILURES[source] >= 3:
        OPEN_UNTIL[source] = clock.time() + 60
        HEALTH[source].update(status="open-circuit", detail="Three consecutive request failures")
    return cache_get(source, cache_key) if cache_allowed else None

def haversine(a: float,b: float,c: float,d: float) -> float:
    r=6371000; p1,p2=math.radians(a),math.radians(c); dp=math.radians(c-a); dl=math.radians(d-b)
    x=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(x))
def parse_free_text(text: str | None) -> dict[str, Any]:
    if not text: return {}
    s=text.lower(); out={}
    if any(x in s for x in ("cheap","inexpensive","budget")): out["budget"]="$"
    walk=re.search(r"(?:under|within|less than)\s+(\d+)\s*(?:min|minute)",s)
    if walk: out["max_walk_min"]=int(walk.group(1))
    for word,category in (("ramen","noodles"),("pizza","pizza"),("coffee","cafe"),("park","park")):
        if word in s: out["category"]=category; break
    return out

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
CATEGORIES = ["noodles", "pizza", "cafe", "park", "bar", "night_club", "restaurant"]
GEMINI_SCHEMA = {"type": "OBJECT", "properties": {
    "budget": {"type": "STRING", "enum": ["$", "$$", "$$$"], "nullable": True},
    "max_walk_min": {"type": "INTEGER", "nullable": True},
    "category": {"type": "STRING", "enum": CATEGORIES, "nullable": True}}}
GEMINI_PROMPT = ("Extract search filters from a Boston night-out request. Set a field only when the request states or clearly "
                 "implies it: budget ($ cheap, $$ moderate, $$$ upscale), max_walk_min (walking limit in minutes), "
                 "category (closest of: " + ", ".join(CATEGORIES) + "). Otherwise use null.\nRequest: ")

def valid_filters(raw: Any) -> dict[str, Any]:
    """Keep only filters that pass the same bounds as the request schema; the model's output is untrusted."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    if raw.get("budget") in ("$", "$$", "$$$"): out["budget"] = raw["budget"]
    walk = raw.get("max_walk_min")
    if isinstance(walk, int) and not isinstance(walk, bool) and 1 <= walk <= 120: out["max_walk_min"] = walk
    if raw.get("category") in CATEGORIES: out["category"] = raw["category"]
    return out

async def parse_query_text(text: str | None) -> dict[str, Any]:
    """Gemini when configured; the deterministic rules otherwise or on any failure."""
    if not text:
        return {}
    key = os.getenv("GEMINI_API_KEY")
    if DEMO or not key:
        HEALTH["gemini"].update(status="demo" if DEMO else "disabled", detail="Rule-based parser in use" if DEMO else "GEMINI_API_KEY is not configured")
        return {**parse_free_text(text), "parser": "rules"}
    body = {"contents": [{"parts": [{"text": GEMINI_PROMPT + text}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": GEMINI_SCHEMA, "temperature": 0}}
    model = os.getenv("GEMINI_MODEL") or "gemini-3.5-flash-lite"  # an empty GEMINI_MODEL= line means default
    data = await request_json("gemini", GEMINI_URL.format(model=model), headers={"x-goog-api-key": key}, method="POST", json_body=body)
    try:
        return {**valid_filters(json.loads(data["candidates"][0]["content"]["parts"][0]["text"])), "parser": "gemini"}
    except (TypeError, KeyError, IndexError, ValueError):
        return {**parse_free_text(text), "parser": "rules"}

EXPLAIN_SCHEMA = {"type": "OBJECT", "properties": {"why": {"type": "STRING"}}, "required": ["why"]}
EXPLAIN_PROMPT = ("Write one friendly sentence (max 25 words) on why this place fits tonight. Use only the facts given; "
                  "do not invent hours, prices, ratings, events or distances. Return JSON {why}.\nPlace: ")

class ExplainInput(BaseModel):
    """The facts the frontend echoes back from a recommendation's explain_facts; bounded because it is client input."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(max_length=200)
    name: str = Field(max_length=120)
    categories: list[Annotated[str, Field(max_length=40)]] = Field(default_factory=list, max_length=3)
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int | None = Field(default=None, ge=0)
    price: Literal["$", "$$", "$$$"] | None = None
    walk_min: int | None = Field(default=None, ge=0, le=300)
    transit: str | None = Field(default=None, max_length=120)
    temperature_f: float | None = Field(default=None, ge=-60, le=130)
    rain_chance_pct: int | None = Field(default=None, ge=0, le=100)
    nearby_events: int | None = Field(default=None, ge=0)

def local_clock(iso: str) -> str:
    t = datetime.fromisoformat(iso).astimezone(ZoneInfo("America/New_York"))
    return t.strftime("%I:%M %p").lstrip("0")

def transit_summary(reach: dict[str, Any]) -> str | None:
    """'Red Line, Park Street to Harvard; last train back 12:47 AM', from the plan's own fields only."""
    out = reach.get("outbound")
    if not out or not out.get("line"):
        return None
    text = f"{out['line']['name']}, {out['from_stop']} to {out['to_stop']}"
    if reach.get("total_min") is not None:
        text += f", {reach['total_min']} min door to door"
    last = reach.get("last_return")
    if last:
        text += f"; {'last train back' if last.get('last_of_night') else 'latest train back'} {local_clock(last['depart_at'])}"
    return text

def explanation_facts(rec: dict[str, Any]) -> dict[str, Any]:
    v, comps = rec["venue"], rec["score"]["components"]
    weather = comps["weather"]["raw"]
    return {"id": v["id"], "name": v["name"][:120], "categories": [str(c)[:40] for c in v.get("categories", [])[:3]], "rating": v.get("rating"),
            "review_count": v.get("review_count"), "price": "$" * v["price_level"] if v.get("price_level") else None,
            "walk_min": v.get("walk_min"), "transit": (transit_summary(rec["reachability"]) or rec["reachability"].get("label") or "")[:120] or None,
            "temperature_f": weather.get("temperature_f"), "rain_chance_pct": weather.get("precipitation_chance_pct"),
            "nearby_events": comps["events"]["raw"].get("nearby_events")}

def grounded(why: Any, facts: dict[str, Any]) -> bool:
    """One short sentence whose every number appears in that place's facts (a cheap check against invented figures)."""
    if not isinstance(why, str) or not 0 < len(why) <= 220:
        return False
    def numbers(text: str) -> set[float]:  # by value, so "53" matches 53.0 and "4,000" stays 4000
        return {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}
    return numbers(why) <= numbers(json.dumps(facts))

async def gemini_explanation(facts: dict[str, Any]) -> str | None:
    """A grounded one-line explanation for one place, or None so the caller keeps the template."""
    key = os.getenv("GEMINI_API_KEY")
    if DEMO or not key:
        return None
    body = {"contents": [{"parts": [{"text": EXPLAIN_PROMPT + json.dumps(facts)}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": EXPLAIN_SCHEMA, "temperature": 0.4}}
    model = os.getenv("GEMINI_MODEL") or "gemini-3.5-flash-lite"
    # On demand from one card, so a slower reply is fine; one generation occasionally takes 5-6 s.
    data = await request_json("gemini_explain", GEMINI_URL.format(model=model), headers={"x-goog-api-key": key}, method="POST", json_body=body, timeout=10.0)
    try:
        why = json.loads(data["candidates"][0]["content"]["parts"][0]["text"])["why"].strip()
    except (TypeError, KeyError, IndexError, ValueError, AttributeError):
        return None
    return why if grounded(why, facts) else None

def matches_category(venue: dict[str, Any], wanted: str | None) -> bool:
    if not wanted:
        return True
    categories=[str(c).casefold() for c in venue.get("categories", [])]
    if wanted == "noodles":
        return any("ramen" in c or "noodle" in c or "japanese" in c or "vietnamese" in c for c in categories)
    if wanted == "pizza":
        return any("pizza" in c for c in categories)
    if wanted == "cafe":
        return any("cafe" in c or "coffee" in c or "bakery" in c for c in categories)
    if wanted == "park":
        return any("park" in c or "garden" in c for c in categories)
    return wanted in categories

def score_venue(v: dict[str,Any], median: float, weather: dict[str,Any], reach: dict[str, Any]) -> dict[str,Any]:
    cfg=SCORING
    delta=v.get("momentum_delta"); momentum=min(1,max(0,delta or 0)/10)
    momentum_meta=v.get("momentum_meta") or {"method":"demo_fixture","label":"demo"}
    reviews=v.get("review_count") or 0; rating=v.get("rating"); m=cfg["quality"]["prior_reviews_m"]
    quality=.5 if rating is None else ((reviews/(reviews+m))*rating+(m/(reviews+m))*median)/cfg["quality"]["rating_max"]
    reach_value=float(reach.get("reach_value", 0.0))
    nearby=v.get("nearby_events"); events=0.0 if nearby is None else min(1.0, nearby/cfg["events"]["saturation_count"])
    w=cfg["weather"]
    adverse=(weather.get("precipitation_chance_pct") or 0)>=w["precipitation_chance_threshold_pct"] or (weather.get("temperature_f") is not None and weather["temperature_f"]<w["cold_threshold_f"])
    mood=w["indoor_adverse"] if (adverse and v["indoor_outdoor"]=="indoor") else (w["outdoor_adverse"] if adverse and v["indoor_outdoor"]=="outdoor" else w["neutral_type"])
    components={"momentum":{"value":momentum,"raw":{"review_delta_30d":delta,**momentum_meta},"sources":["google_places"],"label":momentum_meta.get("label"),"missing_reason":momentum_meta.get("missing_reason")},
                "quality":{"value":quality,"raw":{"rating":rating,"review_count":reviews,"prior_reviews":m,"prior_rating":median},"sources":["google_places"],"missing_reason":"no rating" if rating is None else None},
                "reach":{"value":reach_value,"raw":reach,"sources":["mbta"]},
                "events":{"value":events,"raw":{"nearby_events":nearby,"games":v.get("nearby_games") or []},"sources":["sports"],"missing_reason":"event data unavailable" if nearby is None else None},
                "weather":{"value":mood,"raw":weather,"sources":["nws"],"missing_reason":"weather unavailable" if weather.get("temperature_f") is None and weather.get("precipitation_chance_pct") is None else None}}
    # Components without data drop out and the rest are rescaled, so missing sources never cap the score.
    available=sum(cfg["weights"][k] for k,c in components.items() if not c.get("missing_reason"))
    for k,c in components.items():
        c["base_weight"]=cfg["weights"][k]
        c["weight"]=0.0 if c.get("missing_reason") else c["base_weight"]/available
    total=sum(c["value"]*c["weight"] for c in components.values())
    return {"value":round(total,4),"components":components}

def reach_for(walk_min: int | None, trip_limit: int, plan: dict[str, Any], travel: str = "walk_t") -> dict[str, Any] | None:
    """Eligible if the walk, or the door-to-door T trip with a train back, fits the trip-time limit; the faster one wins.
    A plan without total_min (older shape) counts as fitting. Walk-only searches ignore transit."""
    walkable = walk_min is not None and walk_min <= trip_limit
    total = plan.get("total_min")
    by_t = travel == "walk_t" and bool(plan.get("reachable")) and (total is None or total <= trip_limit)
    if by_t and (not walkable or total is None or total < walk_min):
        return plan
    if walkable:
        return {"reachable": True, "reach_value": SCORING["reach"]["walking_fallback"], "method": "walking_fallback",
                "outbound": None, "return": None, "last_return": None, "total_min": walk_min, "label": "Within walking range"}
    return None

def _period_datetime(point: dict[str, Any], zone: ZoneInfo, reference: datetime) -> datetime | None:
    if not point:
        return None
    day = point.get("date")
    hour, minute = int(point.get("hour", 0)), int(point.get("minute", 0))
    if day:
        try:
            if isinstance(day, dict):  # Places API (New) sends {"year","month","day"}
                return datetime(int(day["year"]), int(day["month"]), int(day["day"]), hour, minute, tzinfo=zone)
            return datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00").replace(tzinfo=zone)
        except (ValueError, KeyError, TypeError):
            return None
    # Regular weekly periods use Google weekday numbering (Sunday=0).
    if "day" in point:
        google_day = int(point["day"])
        python_day = (google_day + 6) % 7
        offset = (python_day - reference.weekday()) % 7
        date = reference.date() + timedelta(days=offset)
        return datetime.combine(date, datetime.min.time(), zone).replace(hour=hour, minute=minute)
    return None

def opening_at(hours: dict[str, Any] | None, requested: datetime, timezone_id: str | None) -> str:
    if not hours:
        return "unknown"
    try:
        zone = ZoneInfo(timezone_id or "America/New_York")
    except Exception:
        zone = ZoneInfo("America/New_York")
    target = requested.astimezone(zone)
    periods = hours.get("periods")
    if periods is None:
        return "unknown"
    for period in periods:
        opening = period.get("open", {})
        closing = period.get("close", {})
        if opening.get("date"):
            opened = _period_datetime(opening, zone, target)
            occurrences = [opened] if opened else []
        elif "day" in opening:
            wanted_day = (int(opening["day"]) + 6) % 7
            occurrences = []
            for offset in range(-1, 8):
                date = target.date() + timedelta(days=offset)
                if date.weekday() == wanted_day:
                    occurrences.append(datetime.combine(date, datetime.min.time(), zone).replace(hour=int(opening.get("hour", 0)), minute=int(opening.get("minute", 0))))
        else:
            occurrences = []
        for opened in occurrences:
            if opened is None:
                continue
            if not closing:
                return "open"
            if closing.get("date"):
                closed = _period_datetime(closing, zone, target)
            elif "day" in closing:
                close_day = (int(closing["day"]) + 6) % 7
                close_date = opened.date() + timedelta(days=(close_day - opened.weekday()) % 7)
                closed = datetime.combine(close_date, datetime.min.time(), zone).replace(hour=int(closing.get("hour", 0)), minute=int(closing.get("minute", 0)))
            else:
                closed = None
            if closed is None:
                continue
            if closed <= opened:
                closed += timedelta(days=1)
            if opened <= target < closed:
                return "open"
    # Empty current periods means explicitly closed; unparseable non-empty periods means unknown.
    if not periods:
        return "closed"
    parsed_any = any(p.get("open", {}).get("date") or "day" in p.get("open", {}) for p in periods)
    return "closed" if parsed_any else "unknown"

ORS_MATRIX_URL = "https://api.openrouteservice.org/v2/matrix/foot-walking"

async def routed_walk_minutes(lat: float, lng: float, venues: list[dict[str, Any]]) -> list[int | None] | None:
    """Street-routed walking minutes from the origin to each venue (None where ORS finds no route); None if unavailable."""
    key = os.getenv("ORS_API_KEY")
    if DEMO:
        HEALTH["routing"].update(status="demo", detail="Fixture walk times")
        return None
    if not venues:
        return None
    if not key:
        HEALTH["routing"].update(status="disabled", detail="ORS_API_KEY is not configured")
        return None
    # ORS takes [lng, lat]; one matrix call covers every candidate. Not cached: the response echoes the coordinates.
    locations = [[round(lng, 4), round(lat, 4)]] + [[v["lng"], v["lat"]] for v in venues]
    body = {"locations": locations, "sources": [0], "destinations": list(range(1, len(locations))), "metrics": ["duration"]}
    data = await request_json("routing", ORS_MATRIX_URL, headers={"Authorization": key}, method="POST", json_body=body)
    try:
        row = data["durations"][0]
    except (TypeError, KeyError, IndexError):
        return None
    if len(row) != len(venues):
        return None
    return [None if d is None else max(1, math.ceil(d / 60)) for d in row]

def routable(venue: dict[str, Any]) -> bool:
    """Only venues with known, non-Google sources may go to OpenRouteService (Maps ToS 3.2.3(a),(c)); unknown origin fails closed."""
    refs = venue.get("source_refs") or []
    return bool(refs) and not any(r.get("source") == "google_places" for r in refs)

def walk_estimate_minutes(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    # Conservative street-grid multiplier over straight-line distance; always disclosed as an estimate.
    return max(1, math.ceil(haversine(lat1, lng1, lat2, lng2) * 1.3 / 78.0))

OSM_SNAPSHOT = ROOT / "backend" / "data" / "osm_venues.json"  # refreshed by scripts/refresh_osm_snapshot.py
OSM_DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]

def parse_osm_hours(spec: str | None) -> dict[int, list[tuple[int, int]]] | None:
    """Common OSM opening_hours forms → {weekday: [(start_min, end_min)]}; end may pass 1440 (after midnight).
    Supports '24/7', 'Mo-Fr 11:00-22:00; Sa,Su 10:00-02:00', 'Su off'. Anything else (PH, months, comments) → None = unknown."""
    if not spec:
        return None
    spec = re.sub(r"\s*,\s*", ",", spec.strip())  # "11:00-14:00, 17:00-22:00" is common in OSM
    if spec == "24/7":
        return {d: [(0, 1440)] for d in range(7)}
    week: dict[int, list[tuple[int, int]]] = {d: [] for d in range(7)}
    for rule in filter(None, (r.strip() for r in spec.split(";"))):
        m = re.fullmatch(r"(?:([A-Z][a-z](?:-[A-Z][a-z])?(?:,[A-Z][a-z](?:-[A-Z][a-z])?)*)\s+)?(off|closed|\d\d:\d\d-\d\d:\d\d(?:,\d\d:\d\d-\d\d:\d\d)*)", rule)
        if not m:
            return None
        days: set[int] = set()
        for part in (m.group(1) or "Mo-Su").split(","):
            ends = part.split("-")
            if any(e not in OSM_DAYS for e in ends):
                return None  # PH, SH, etc.
            a, b = OSM_DAYS.index(ends[0]), OSM_DAYS.index(ends[-1])
            days.update(range(a, b + 1) if a <= b else [*range(a, 7), *range(0, b + 1)])  # Su-Th wraps
        spans = []
        if m.group(2) not in ("off", "closed"):
            for span in m.group(2).split(","):
                (h1, m1), (h2, m2) = (map(int, t.split(":")) for t in span.split("-"))
                if h1 > 24 or h2 > 48 or m1 > 59 or m2 > 59:
                    return None
                start, end = h1 * 60 + m1, h2 * 60 + m2
                spans.append((start, end + 1440 if end <= start else end))  # 18:00-02:00 runs past midnight
        for d in days:
            week[d] = spans  # a later rule replaces earlier ones for its days
    return week

def osm_open_at(spec: str | None, when: datetime) -> str:
    week = parse_osm_hours(spec)
    if week is None:
        return "unknown"
    local = when.astimezone(ZoneInfo("America/New_York"))
    minute, day = local.hour * 60 + local.minute, local.weekday()
    today = any(a <= minute < b for a, b in week[day])
    from_yesterday = any(b > 1440 and minute < b - 1440 for _, b in week[(day - 1) % 7])
    return "open" if today or from_yesterday else "closed"

_OSM_CACHE: dict[str, Any] = {}

def load_osm_snapshot() -> dict[str, Any] | None:
    """The parsed snapshot, re-read only when the file changes (it is a few MB; parsing per request would block the loop)."""
    try:
        mtime = OSM_SNAPSHOT.stat().st_mtime
        if _OSM_CACHE.get("mtime") != mtime:
            snap = json.loads(OSM_SNAPSHOT.read_text())
            snap["generated"] = datetime.fromisoformat(snap["generated_at"])
            if not isinstance(snap["venues"], list):
                raise ValueError("venues must be a list")
            _OSM_CACHE.update(mtime=mtime, snap=snap)
        return _OSM_CACHE["snap"]
    except (OSError, ValueError, KeyError, TypeError):
        return None

def osm_candidates(q: QueryInput, category: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Backup venues from the bundled OSM snapshot (no key, no live call): the nearest named places within 5 km
    that are open at the requested time and match the category; only those count toward the limit."""
    snap = load_osm_snapshot()
    if snap is None:
        HEALTH["overpass"].update(status="disabled", detail="No usable OSM snapshot; run scripts/refresh_osm_snapshot.py")
        return []
    generated = snap["generated"]
    HEALTH["overpass"].update(status="cached", last_success_at=generated.isoformat(), checked_at=now_iso(),
                              cache_age_s=round((datetime.now(timezone.utc) - generated).total_seconds()),
                              detail="Bundled OSM snapshot (backup while Google Places is unavailable)")
    near = sorted(((haversine(q.lat, q.lng, v["lat"], v["lng"]), v) for v in snap["venues"]), key=lambda x: x[0])
    out = []
    for distance, v in near:
        if distance > 5000 or len(out) >= limit:
            break
        if osm_open_at(v.get("opening_hours"), q.time) != "open":
            continue
        raw = v.get("amenity") or v.get("leisure") or "venue"
        kind = {"nightclub": "night_club"}.get(raw, raw)  # match Google type names
        cuisine = [c.strip() for c in v.get("cuisine", "").split(";") if c.strip()]
        categories = [kind, *(["bar"] if kind == "pub" else []), *cuisine]  # a "bar" search should include pubs
        if not matches_category({"categories": categories}, category):
            continue
        address = " ".join(x for x in (v.get("addr:housenumber"), v.get("addr:street")) if x) or None
        out.append({"id": f"osm-{v['osm'].replace('/', '-')}", "name": v["name"], "lat": v["lat"], "lng": v["lng"], "address": address,
                    "categories": categories, "price_level": None, "rating": None, "review_count": None,
                    "open_hours": {"status_at_requested_time": "open", "periods": None,
                                   "timezone": "America/New_York", "source": "overpass"},
                    "indoor_outdoor": "outdoor" if kind == "park" else "indoor",
                    "walk_min": walk_estimate_minutes(q.lat, q.lng, v["lat"], v["lng"]), "walk_method": "straight_line_estimate",
                    "source_refs": [{"source": "overpass", "external_id": v["osm"], "url": f"https://www.openstreetmap.org/{v['osm']}"}],
                    "attributions": [{"source": "overpass", "text": "© OpenStreetMap contributors", "url": "https://www.openstreetmap.org/copyright"}],
                    "momentum_delta": None, "momentum_meta": {"method": "unavailable", "label": None, "missing_reason": "no_velocity_data"}})
    return out

async def live_candidates(q: QueryInput) -> tuple[list[dict[str,Any]],bool]:
    key=os.getenv("GOOGLE_MAPS_API_KEY")
    if DEMO: return [dict(v) for v in FIXTURES], False
    if not key:
        HEALTH["google_places"].update(status="disabled", detail="GOOGLE_MAPS_API_KEY is not configured")
        return [], False
    body={"locationRestriction":{"circle":{"center":{"latitude":q.lat,"longitude":q.lng},"radius":5000}},"maxResultCount":20,"includedTypes":["restaurant","cafe","bar","night_club","park"]}
    try:
        data=await request_json("google_places","https://places.googleapis.com/v1/places:searchNearby",{},headers={"X-Goog-Api-Key":key,"X-Goog-FieldMask":"places.id,places.displayName,places.location,places.formattedAddress,places.rating,places.userRatingCount,places.priceLevel,places.currentOpeningHours,places.regularOpeningHours,places.primaryType,places.types,places.googleMapsUri,places.timeZone,places.attributions"},method="POST",json_body=body)
        if data is None:
            return [], False
        result=[]
        for p in data.get("places",[]):
            loc=p.get("location",{}); pl=p.get("priceLevel"); price={"PRICE_LEVEL_FREE":1,"PRICE_LEVEL_INEXPENSIVE":1,"PRICE_LEVEL_MODERATE":2,"PRICE_LEVEL_EXPENSIVE":3,"PRICE_LEVEL_VERY_EXPENSIVE":3}.get(pl)
            latitude, longitude=loc.get("latitude"),loc.get("longitude")
            if latitude is None or longitude is None: continue
            hours=p.get("currentOpeningHours") or p.get("regularOpeningHours")
            tz=p.get("timeZone",{}).get("id") if isinstance(p.get("timeZone"),dict) else None
            types=p.get("types",[])
            place_types=[str(t).casefold() for t in types]
            if any("park" in t or "garden" in t for t in place_types):
                indoor_outdoor="outdoor"
            elif any(any(word in t for word in ("restaurant","cafe","bakery","bar","night_club","food")) for t in place_types):
                indoor_outdoor="indoor"
            else:
                indoor_outdoor="unknown"
            delta, velocity_meta=None,{"method":"unavailable","label":None,"missing_reason":"google_review_velocity_not_persisted_for_provider_compliance"}
            provider_attrs=[{"source":"google_places","text":"Google Maps","url":"https://maps.google.com","required_logo":"Google Maps","translate_no":True}]
            for attr in p.get("attributions",[]):
                if attr.get("provider"):
                    provider_attrs.append({"source":"google_places","text":attr["provider"],"url":attr.get("providerUri")})
            result.append({"id":p.get("id",str(uuid4())),"name":p.get("displayName",{}).get("text","Venue"),"lat":latitude,"lng":longitude,"address":p.get("formattedAddress"),"categories":types or [p.get("primaryType","venue")],"price_level":price,"rating":p.get("rating"),"review_count":p.get("userRatingCount"),"open_hours":{"status_at_requested_time":opening_at(hours,q.time,tz),"periods":(hours or {}).get("periods"),"timezone":tz},"indoor_outdoor":indoor_outdoor,"walk_min":walk_estimate_minutes(q.lat,q.lng,latitude,longitude),"walk_method":"straight_line_estimate","source_refs":[{"source":"google_places","external_id":p.get("id"),"url":p.get("googleMapsUri")}],"attributions":provider_attrs,"momentum_delta":delta,"momentum_meta":velocity_meta})
        return result, False
    except Exception:
        HEALTH["google_places"].update(status="disabled",detail="Google Places unavailable")
        return [], False

def _resource_trip_id(resource: dict[str, Any]) -> str | None:
    return (resource.get("relationships", {}).get("trip", {}).get("data") or {}).get("id")

def _event_time(schedule: dict[str, Any], event: str = "departure") -> datetime | None:
    attrs=schedule.get("attributes",{})
    raw = (attrs.get("arrival_time") or attrs.get("departure_time")) if event=="arrival" else (attrs.get("departure_time") or attrs.get("arrival_time"))
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None

_MBTA_STOPS: dict[str, Any] = {}
_MBTA_STOPS_LOCK = asyncio.Lock()  # one 2.7 MB fetch at a time; waiters reuse its result

async def mbta_all_stops() -> list[dict[str, Any]] | None:
    """Every MBTA stop and station (open data, ~8k), fetched at most daily. Nearest-stop search then runs locally, so no
    coordinates (Google Places or the user's) are sent to the MBTA; only stop IDs are, for routes and schedules."""
    if _MBTA_STOPS and clock.time() < _MBTA_STOPS["fresh_until"]:
        return _MBTA_STOPS.get("stops")
    async with _MBTA_STOPS_LOCK:
        if _MBTA_STOPS and clock.time() < _MBTA_STOPS["fresh_until"]:
            return _MBTA_STOPS.get("stops")
        return await _refresh_mbta_stops()

async def _refresh_mbta_stops() -> list[dict[str, Any]] | None:
    headers = {"x-api-key": os.environ["MBTA_API_KEY"]} if os.getenv("MBTA_API_KEY") else None
    data = await request_json("mbta", f"{MBTA_BASE}/stops", {"filter[location_type]": "0,1", "fields[stop]": "name,latitude,longitude,location_type"},
                              headers=headers, timeout=15.0)
    if not data:
        # Back off instead of refetching on every lookup (that would stall requests and trip the shared MBTA breaker);
        # keep serving the previous list if there is one.
        _MBTA_STOPS["fresh_until"] = clock.time() + (300 if _MBTA_STOPS.get("stops") else 60)
        return _MBTA_STOPS.get("stops")
    stops = [{"id": st["id"], "name": a.get("name", "MBTA stop"), "lat": a["latitude"], "lng": a["longitude"], "station": a.get("location_type") == 1}
             for st in data.get("data", []) if (a := st.get("attributes", {})).get("latitude") is not None and a.get("longitude") is not None]
    _MBTA_STOPS.update(fresh_until=clock.time() + 86400, stops=stops)
    return stops

async def mbta_nearby_stops(lat: float, lng: float, radius_m: int = 1200) -> list[dict[str, Any]]:
    stops = await mbta_all_stops()
    if not stops:
        return []
    near = sorted(({**s, "distance_m": d} for s in stops if (d := haversine(lat, lng, s["lat"], s["lng"])) <= radius_m),
                  key=lambda s: s["distance_m"])
    # Nearest stations cover the subway lines (a nearby bus stop or platform would otherwise crowd them out); plus the closest bus stops.
    return [s for s in near if s["station"]][:3] + [s for s in near if not s["station"]][:2]

async def mbta_routes_at(stop_id: str) -> set[str]:
    headers={"x-api-key":os.environ["MBTA_API_KEY"]} if os.getenv("MBTA_API_KEY") else None
    data = await request_json("mbta", f"{MBTA_BASE}/routes", {"filter[stop]": stop_id, "page[limit]": 100}, headers=headers)
    return {r["id"] for r in (data or {}).get("data", [])}

async def mbta_schedules(stop_id: str, route_id: str, direction: int, start: datetime, end: datetime) -> list[dict[str, Any]]:
    zone = ZoneInfo("America/New_York")
    local_start, local_end = start.astimezone(zone), end.astimezone(zone)
    # MBTA service days run through 02:59; post-midnight trips belong to the prior service date.
    service_day = (local_start.date() - timedelta(days=1)) if local_start.hour < 3 else local_start.date()
    async def get_for_service_day(day: date) -> list[dict[str, Any]]:
        day_start = datetime.combine(day, datetime.min.time(), zone) + timedelta(hours=3)
        day_end = day_start + timedelta(days=1)
        low, high = max(local_start, day_start), min(local_end, day_end)
        if low >= high:
            return []
        low_minutes = int((low - datetime.combine(day, datetime.min.time(), zone)).total_seconds() // 60)
        high_minutes = int((high - datetime.combine(day, datetime.min.time(), zone)).total_seconds() // 60)
        def hm(minutes: int) -> str:
            return f"{minutes // 60:02d}:{minutes % 60:02d}"
        params = {"filter[stop]": stop_id, "filter[route]": route_id, "filter[direction_id]": direction,
                  "filter[date]": day.isoformat(), "filter[min_time]": hm(low_minutes), "filter[max_time]": hm(high_minutes),
                  "include": "trip,route", "page[limit]": 100, "sort": "departure_time"}
        headers={"x-api-key":os.environ["MBTA_API_KEY"]} if os.getenv("MBTA_API_KEY") else None
        data=await request_json("mbta",f"{MBTA_BASE}/schedules",params,headers=headers)
        return (data or {}).get("data",[])
    days=[]
    cursor=service_day
    last_day=local_end.date()
    while cursor<=last_day:
        days.append(cursor)
        cursor+=timedelta(days=1)
    pages=await asyncio.gather(*(get_for_service_day(day) for day in days))
    return [row for page in pages for row in page]

async def mbta_predictions(stop_id: str, route_id: str, direction: int) -> set[str]:
    params = {"filter[stop]": stop_id, "filter[route]": route_id, "filter[direction_id]": direction,
              "sort": "arrival_time", "page[limit]": 20}
    headers={"x-api-key":os.environ["MBTA_API_KEY"]} if os.getenv("MBTA_API_KEY") else None
    data = await request_json("mbta", f"{MBTA_BASE}/predictions", params, headers=headers)
    trips = set()
    for prediction in (data or {}).get("data", []):
        trip_id = _resource_trip_id(prediction)
        if trip_id:
            trips.add(trip_id)
    return trips

async def mbta_route_alerts(stop_id: str, route_id: str, at: datetime) -> list[dict[str, Any]]:
    # Only alerts active at the trip time: an upcoming weekend suspension must not block tonight's trains.
    params={"filter[stop]":stop_id,"filter[route]":route_id,"filter[activity]":"BOARD","filter[datetime]":at.replace(microsecond=0).isoformat(),"page[limit]":50}
    headers={"x-api-key":os.environ["MBTA_API_KEY"]} if os.getenv("MBTA_API_KEY") else None
    data=await request_json("mbta",f"{MBTA_BASE}/alerts",params,headers=headers)
    return (data or {}).get("data",[])

def round_trip_plan(route_id: str, origin: str, destination: str, out: tuple[datetime, datetime], back: tuple[datetime, datetime],
                    last: tuple[datetime, datetime], last_of_night: bool, live: bool, start: datetime, walks: tuple[int, int],
                    label: str | None = None) -> dict[str, Any]:
    """One shape for live and demo plans: Boston line info, both legs, the latest train back, and door-to-door minutes
    (setting out at start: walk to the stop, wait, ride, walk to the venue)."""
    total_min = math.ceil((out[1] - start).total_seconds() / 60) + walks[1]
    line = mbta_line(route_id)
    def leg(a: str, b: str, times: tuple[datetime, datetime]) -> dict[str, Any]:
        return {"from_stop": a, "to_stop": b, "route": route_id, "line": line, "depart_at": times[0].isoformat(), "arrive_at": times[1].isoformat()}
    return {"reachable": True, "reach_value": 1.0 if live else 0.5, "method": "predicted_round_trip" if live else "scheduled_round_trip",
            "line": line, "outbound": leg(origin, destination, out), "return": {**leg(destination, origin, back), "before_last_service": True},
            "total_min": total_min, "walk_to_stop_min": walks[0], "walk_from_stop_min": walks[1],
            # last_of_night: the search window reached the end of the MBTA service day, so this really is the last train back.
            "last_return": {**leg(destination, origin, last), "last_of_night": last_of_night},
            "label": label or ("Live departure and scheduled return" if live else "Scheduled round trip; prediction unavailable")}

# Subway transfer stations (parent stops). Routes are looked up live, so branch changes don't need code edits.
TRANSFER_HUBS = {"place-pktrm": "Park Street", "place-dwnxg": "Downtown Crossing", "place-state": "State",
                 "place-gover": "Government Center", "place-haecl": "Haymarket", "place-north": "North Station"}
TRANSFER_MIN = timedelta(minutes=3)  # time to change platforms
BLOCKING_EFFECTS = {"NO_SERVICE", "SUSPENSION"}

async def route_blocked(route_id: str, stop_ids: tuple[str, ...], at: datetime) -> bool:
    alerts = await asyncio.gather(*(mbta_route_alerts(sid, route_id, at) for sid in stop_ids))
    return any(a.get("attributes", {}).get("effect") in BLOCKING_EFFECTS for group in alerts for a in group)

async def find_leg(a: str, b: str, route_id: str, earliest: datetime, latest: datetime) -> tuple[datetime, datetime, int, str] | None:
    """Earliest-arriving trip on one route from stop a (leaving at/after earliest) to stop b (arriving by latest):
    (depart, arrive, direction, trip_id). Same trip at both stops, in time order."""
    for direction in (0, 1):
        at_a, at_b = await asyncio.gather(mbta_schedules(a, route_id, direction, earliest, latest),
                                          mbta_schedules(b, route_id, direction, earliest, latest))
        deps = {tid: t for x in at_a if (tid := _resource_trip_id(x)) and (t := _event_time(x, "departure"))}
        arrs = {tid: t for x in at_b if (tid := _resource_trip_id(x)) and (t := _event_time(x, "arrival"))}
        trips = [(arrs[tid], deps[tid], tid) for tid in deps if tid in arrs and earliest <= deps[tid] < arrs[tid] <= latest]
        if trips:
            arrive, depart, tid = min(trips)
            return depart, arrive, direction, tid
    return None

async def transfer_round_trip(q: QueryInput, venue: dict[str, Any], origin_stops: list[dict[str, Any]],
                              venue_stops: list[dict[str, Any]], routes_by_stop: dict[str, set[str]],
                              depart: datetime, return_after: datetime, return_before: datetime, last_of_night: bool) -> dict[str, Any] | None:
    """One change between two subway lines at a transfer station, there and back. Only the single best candidate is tried
    (about 16 MBTA calls), and only when no direct line works."""
    hub_ids = list(TRANSFER_HUBS)
    hub_routes = dict(zip(hub_ids, await asyncio.gather(*(mbta_routes_at(h) for h in hub_ids))))
    best = None
    for origin in origin_stops:
        for destination in venue_stops:
            for a in routes_by_stop.get(origin["id"], set()):
                for b in routes_by_stop.get(destination["id"], set()):
                    if a == b or mbta_line(a)["mode"] != "subway" or mbta_line(b)["mode"] != "subway":
                        continue
                    for hub in hub_ids:
                        if a in hub_routes[hub] and b in hub_routes[hub] and hub not in (origin["id"], destination["id"]):
                            rank = origin["distance_m"] + destination["distance_m"]
                            if best is None or rank < best[0]:
                                best = (rank, origin, destination, a, b, hub)
    if best is None:
        return None
    _, origin, destination, a, b, hub = best
    walk_to = walk_estimate_minutes(q.lat, q.lng, origin["lat"], origin["lng"])
    walk_from = walk_estimate_minutes(destination["lat"], destination["lng"], venue["lat"], venue["lng"])
    catchable = depart + timedelta(minutes=walk_to)
    if any(await asyncio.gather(route_blocked(a, (origin["id"], hub), catchable), route_blocked(b, (hub, destination["id"]), catchable),
                                route_blocked(b, (destination["id"], hub), return_after), route_blocked(a, (hub, origin["id"]), return_after))):
        return None  # either line blocked going out or on the way home
    leg1 = await find_leg(origin["id"], hub, a, catchable, depart + timedelta(minutes=90))
    leg2 = leg1 and await find_leg(hub, destination["id"], b, leg1[1] + TRANSFER_MIN, leg1[1] + timedelta(minutes=60))
    back1 = leg2 and await find_leg(destination["id"], hub, b, return_after, return_before)
    back2 = back1 and await find_leg(hub, origin["id"], a, back1[1] + TRANSFER_MIN, return_before)
    if not back2:
        return None
    live = bool(await mbta_predictions(origin["id"], a, leg1[2]) & {leg1[3]})
    line_a, line_b, hub_name = mbta_line(a), mbta_line(b), TRANSFER_HUBS[hub]
    total_min = math.ceil((leg2[1] - depart).total_seconds() / 60) + walk_from
    def leg(frm: str, to: str, start: datetime, end: datetime, first: dict, second: dict) -> dict[str, Any]:
        return {"from_stop": frm, "to_stop": to, "route": first["id"], "line": first, "depart_at": start.isoformat(), "arrive_at": end.isoformat(),
                "transfer": {"at": hub_name, "line": second}}
    # shortcut: no "latest train back" for transfers (only the first return chain is searched); add a later-chain search if wanted.
    back = leg(destination["name"], origin["name"], back1[0], back2[1], line_b, line_a)
    return {"reachable": True, "reach_value": 1.0 if live else 0.5, "method": "predicted_round_trip" if live else "scheduled_round_trip",
            "line": line_a, "outbound": leg(origin["name"], destination["name"], leg1[0], leg2[1], line_a, line_b),
            "return": {**back, "before_last_service": True}, "last_return": None,
            "total_min": total_min, "walk_to_stop_min": walk_to, "walk_from_stop_min": walk_from,
            "label": f"{line_a['name']} → {line_b['name']}, change at {hub_name}" + (" (live departure)" if live else " (scheduled)")}

NO_TRANSIT = {"reachable": False, "reach_value": 0.5, "method": "walking_fallback", "outbound": None, "return": None}

def demo_round_trip(q: QueryInput, venue: dict[str, Any]) -> dict[str, Any]:
    trip = DEMO_TRANSIT.get(venue["id"])
    if not trip:
        return {**NO_TRANSIT, "label": "Demo transit fixtures; walking estimate used"}
    origin, destination, route_id, ride, (hour, minute), walk_to, walk_from = trip
    service_end = mbta_service_end(q.time)
    last_depart = service_end.replace(hour=hour, minute=minute)  # service_end is 03:00 the next morning
    out_depart = q.time.astimezone(timezone.utc) + timedelta(minutes=walk_to + 3)  # walk to the stop, then a short wait
    back_depart = out_depart + MIN_STAY
    if back_depart > last_depart:
        return {**NO_TRANSIT, "label": "Demo transit fixture: past the last train back"}
    minutes = timedelta(minutes=ride)
    return round_trip_plan(route_id, origin, destination, (out_depart, out_depart + minutes), (back_depart, back_depart + minutes),
                           (last_depart, last_depart + minutes), True, False, q.time, (walk_to, walk_from),
                           "Demo transit fixture: scheduled round trip")

async def assess_mbta_round_trip(q: QueryInput, venue: dict[str, Any], origin_stops: list[dict[str, Any]]) -> dict[str, Any]:
    if DEMO:
        return demo_round_trip(q, venue)
    if not origin_stops:
        return {**NO_TRANSIT, "label": "No MBTA stop near you; walking estimate used"}
    venue_stops = await mbta_nearby_stops(venue["lat"], venue["lng"])
    if not origin_stops or not venue_stops:
        return {**NO_TRANSIT, "label": "No nearby MBTA stop pair; walking fallback"}
    stop_ids = list(dict.fromkeys(s["id"] for s in origin_stops + venue_stops))
    route_results = await asyncio.gather(*(mbta_routes_at(sid) for sid in stop_ids))
    routes_by_stop = dict(zip(stop_ids, route_results))
    depart = q.time.astimezone(timezone.utc)
    return_after = depart + MIN_STAY
    # Never plan a ride home on the next morning's first trains: stop at the end of this service day.
    service_end = mbta_service_end(q.time).astimezone(timezone.utc)
    return_before = min(depart + timedelta(hours=8), service_end)
    last_of_night = return_before >= service_end
    # One attempt per route, at its closest stop pair, subway lines first.
    best: dict[str, tuple[tuple[int, float], dict[str, Any], dict[str, Any]]] = {}
    for origin in origin_stops:
        for destination in venue_stops:
            for route_id in routes_by_stop.get(origin["id"], set()) & routes_by_stop.get(destination["id"], set()):
                rank = (MODE_RANK[mbta_line(route_id)["mode"]], origin["distance_m"] + destination["distance_m"])
                if route_id not in best or rank < best[route_id][0]:
                    best[route_id] = (rank, origin, destination)
    options = sorted(best.items(), key=lambda item: item[1][0])[:MBTA_MAX_ROUTE_TRIES]
    for route_id, (_, origin, destination) in options:
        walk_to = walk_estimate_minutes(q.lat, q.lng, origin["lat"], origin["lng"])
        walk_from = walk_estimate_minutes(destination["lat"], destination["lng"], venue["lat"], venue["lng"])
        catchable = depart + timedelta(minutes=walk_to)  # you have to walk to the stop before the train leaves
        if any(await asyncio.gather(route_blocked(route_id, (origin["id"], destination["id"]), catchable),
                                    route_blocked(route_id, (destination["id"], origin["id"]), return_after))):
            continue  # blocked going out, or on the way home (e.g. an evening suspension)
        # A valid leg must be the same trip at both ends, in the correct time order.
        for direction in (0, 1):
            out_a, out_b = await asyncio.gather(
                mbta_schedules(origin["id"], route_id, direction, depart, depart + timedelta(minutes=75)),
                mbta_schedules(destination["id"], route_id, direction, depart, depart + timedelta(minutes=75)),
            )
            origin_trips = { _resource_trip_id(x): _event_time(x,"departure") for x in out_a if _resource_trip_id(x) }
            destination_trips = { _resource_trip_id(x): _event_time(x,"arrival") for x in out_b if _resource_trip_id(x) }
            outbound_ids = {tid for tid, t in origin_trips.items() if t and t >= catchable and tid in destination_trips and destination_trips[tid] and t < destination_trips[tid] <= depart+timedelta(minutes=75)}
            if not outbound_ids:
                continue
            return_direction = 1 - direction
            if return_after >= return_before:
                continue
            ret_a, ret_b = await asyncio.gather(
                mbta_schedules(destination["id"], route_id, return_direction, return_after, return_before),
                mbta_schedules(origin["id"], route_id, return_direction, return_after, return_before),
            )
            venue_trips = {_resource_trip_id(x): _event_time(x,"departure") for x in ret_a if _resource_trip_id(x)}
            home_trips = {_resource_trip_id(x): _event_time(x,"arrival") for x in ret_b if _resource_trip_id(x)}
            return_ids = {tid for tid, t in venue_trips.items() if t and return_after <= t < return_before and tid in home_trips and home_trips[tid] and t < home_trips[tid]}
            if return_ids:
                predicted_out = await mbta_predictions(origin["id"], route_id, direction)
                live_confirmed = bool(predicted_out & outbound_ids)  # the return is beyond prediction range; it is schedule-confirmed
                out_id = min(outbound_ids, key=destination_trips.__getitem__)  # earliest arrival
                ret_id = min(return_ids, key=venue_trips.__getitem__)
                last_id = max(return_ids, key=venue_trips.__getitem__)
                return round_trip_plan(route_id, origin["name"], destination["name"],
                                       (origin_trips[out_id], destination_trips[out_id]), (venue_trips[ret_id], home_trips[ret_id]),
                                       (venue_trips[last_id], home_trips[last_id]), last_of_night, live_confirmed,
                                       depart, (walk_to, walk_from))
    # No single line works: try one change between subway lines.
    plan = await transfer_round_trip(q, venue, origin_stops, venue_stops, routes_by_stop, depart, return_after, return_before, last_of_night)
    return plan or {**NO_TRANSIT, "label": "No matching scheduled round trip; walking fallback"}

def _field_name(fields: list[dict[str, Any]], aliases: tuple[str, ...]) -> str | None:
    names = {str(f.get("id", "")).casefold(): str(f.get("id", "")) for f in fields}
    return next((names[a.casefold()] for a in aliases if a.casefold() in names), None)

async def resolve_ckan_resources(force: bool = False) -> dict[str, dict[str, Any]]:
    global CKAN_RESOLVED_AT
    if DEMO:
        return {}
    if CKAN_RESOURCES and not force and clock.time() - CKAN_RESOLVED_AT < 86400:
        return CKAN_RESOURCES
    packages = {
        "311": os.getenv("BOSTON_311_PACKAGE", "311-service-requests"),
        "licenses": os.getenv("BOSTON_LICENSE_PACKAGE", "active-food-establishment-licenses"),
    }
    resolved: dict[str, dict[str, Any]] = {}
    for role, package in packages.items():
        shown = await request_json("boston_ckan", f"{CKAN_BASE}/package_show", {"id": package})
        result = (shown or {}).get("result")
        if not result:
            HEALTH["boston_ckan"].update(status="disabled", detail=f"package_show failed for {role} dataset")
            continue
        resources = [r for r in result.get("resources", []) if r.get("datastore_active")]
        if role == "311":
            resources.sort(key=lambda r: ("new system" not in (r.get("name") or "").casefold(),
                                          str(datetime.now().year) not in (r.get("name") or "")))
        else:
            resources.sort(key=lambda r: ("license" not in (r.get("name") or "").casefold(), r.get("name") is None))
        if not resources:
            HEALTH["boston_ckan"].update(status="disabled", detail=f"No datastore resource found for {role}")
            continue
        resource = resources[0]
        sample = await request_json("boston_ckan", f"{CKAN_BASE}/datastore_search", {"resource_id": resource["id"], "limit": 1})
        fields = (sample or {}).get("result", {}).get("fields", [])
        if not fields:
            HEALTH["boston_ckan"].update(status="disabled", detail=f"Schema unavailable for {role}")
            continue
        item = {"package": package, "package_title": result.get("title"), "package_url": result.get("url") or f"https://data.boston.gov/dataset/{package}",
                "contact": result.get("contact_point"), "phone": result.get("contact_point_phone"),
                "resource_id": resource["id"], "resource_name": resource.get("name"), "fields": fields}
        if role == "311":
            item.update({"date_field": _field_name(fields, ("open_date", "open_dt", "open_datetime", "created_at", "created_date")),
                         "category_field": _field_name(fields, ("case_topic", "service_name", "case_title", "subject", "reason", "type", "request_type")),
                         "lat_field": _field_name(fields, ("latitude", "lat")), "lng_field": _field_name(fields, ("longitude", "lng", "lon"))})
            if not all(item.get(k) for k in ("date_field", "category_field", "lat_field", "lng_field")):
                HEALTH["boston_ckan"].update(status="disabled", detail="schema_unrecognized: 311 fields do not match supported aliases")
                continue
        else:
            item.update({"issued_field": _field_name(fields, ("issued", "issue_date", "license_date", "issued_date", "license_add_dt_tm")),
                         "name_field": _field_name(fields, ("business_name", "businessname", "dba_name", "dbaname", "business", "name")),
                         "lat_field": _field_name(fields, ("gpsy", "latitude", "lat")), "lng_field": _field_name(fields, ("gpsx", "longitude", "lng", "lon")),
                         "address_field": _field_name(fields, ("address", "descpremadd", "location"))})
            if not all(item.get(k) for k in ("issued_field", "name_field")):
                HEALTH["boston_ckan"].update(status="disabled", detail="schema_unrecognized: license fields do not match supported aliases")
                continue
        resolved[role] = item
    CKAN_RESOURCES.clear()
    CKAN_RESOURCES.update(resolved)
    CKAN_RESOLVED_AT = clock.time()
    return CKAN_RESOURCES

def _parse_city_date(value: Any) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    for fmt in (None, "%m/%d/%Y", "%Y/%m/%d", "%m/%d/%y"):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00")) if fmt is None else datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None

async def ckan_records(role: str, start: datetime, limit: int = 10000) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None]:
    resources = await resolve_ckan_resources()
    meta = resources.get(role)
    if not meta:
        return None, None
    date_field = meta.get("date_field") or meta.get("issued_field")
    fields = [date_field, meta.get("category_field"), meta.get("lat_field"), meta.get("lng_field"),
              meta.get("name_field"), meta.get("address_field")]
    fields = list(dict.fromkeys(f for f in fields if f))
    page_limit = min(limit, 32000)
    offset = 0
    collected: list[dict[str, Any]] = []
    max_pages = 10 if role == "311" else 1
    complete_window = role != "311"
    for _ in range(max_pages):
        params = {"resource_id": meta["resource_id"], "limit": page_limit, "offset": offset,
                  "sort": f"{date_field} desc", "fields": ",".join(fields)}
        data = await request_json("boston_ckan", f"{CKAN_BASE}/datastore_search", params)
        result = (data or {}).get("result")
        if result is None:
            return meta, None
        page = result.get("records", [])
        if not page:
            break
        collected.extend(page)
        oldest = _parse_city_date(page[-1].get(date_field))
        if role != "311" or (oldest is not None and oldest < start) or len(page) < page_limit:
            complete_window = True
            break
        offset += len(page)
    meta["sampled"] = (len(collected) >= page_limit) if role != "311" else not complete_window
    return meta, collected

async def live_neighborhood(lat: float, lng: float, radius_m: int) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    meta311, rows311 = await ckan_records("311", cutoff)
    meta_licenses, rows_licenses = await ckan_records("licenses", cutoff, limit=3000)
    summary = None
    if meta311 and rows311 is not None:
        category_counts: Counter[str] = Counter()
        matched = 0
        for row in rows311:
            try:
                rlat, rlng = float(row.get(meta311["lat_field"])), float(row.get(meta311["lng_field"]))
            except (TypeError, ValueError):
                continue
            if haversine(lat, lng, rlat, rlng) > radius_m:
                continue
            opened = _parse_city_date(row.get(meta311["date_field"]))
            if opened is None or opened < cutoff:
                continue
            category = str(row.get(meta311["category_field"]) or "Uncategorized").strip()
            if category:
                category_counts[category] += 1
                matched += 1
        summary = {"period_start": cutoff.date().isoformat(), "period_end": datetime.now(timezone.utc).date().isoformat(),
                   "top_categories": [{"category": name, "count": count} for name, count in category_counts.most_common(8)],
                   "records_considered": len(rows311), "spatial_records_matched": matched,
                   "sampled": meta311.get("sampled", True), "source_ref": meta311["package_url"]}
    licenses = None
    if meta_licenses and rows_licenses is not None:
        licenses = []
        for row in rows_licenses:
            issued = _parse_city_date(row.get(meta_licenses["issued_field"]))
            if issued is None or issued < cutoff:
                continue
            item = {"name": row.get(meta_licenses["name_field"]), "issued_at": issued.date().isoformat(),
                    "source_ref": meta_licenses["package_url"]}
            try:
                license_lat, license_lng = float(row.get(meta_licenses.get("lat_field"))), float(row.get(meta_licenses.get("lng_field")))
                if -90 <= license_lat <= 90 and -180 <= license_lng <= 180:
                    distance = haversine(lat, lng, license_lat, license_lng)
                    if distance <= radius_m:
                        item.update({"lat": license_lat, "lng": license_lng, "distance_m": round(distance)})
                    else:
                        continue
            except (TypeError, ValueError):
                if meta_licenses.get("lat_field") and meta_licenses.get("lng_field"):
                    continue
            if meta_licenses.get("address_field"):
                item["address"] = row.get(meta_licenses["address_field"])
            licenses.append(item)
        licenses.sort(key=lambda x: x["issued_at"], reverse=True)
        licenses = licenses[:30]
    contact = None
    contact_meta = meta311 or meta_licenses
    if contact_meta:
        contact = [{"name": contact_meta.get("contact") or "Boston 311", "service": "City service requests and public data",
                    "phone": contact_meta.get("phone") or "311", "url": "https://www.boston.gov/departments/boston-311",
                    "distance_m": 0, "source_ref": contact_meta["package_url"]}]
    return {"center": {"lat": lat, "lng": lng}, "radius_m": radius_m, "311": summary,
            "business_licenses": licenses, "business_licenses_source": meta_licenses.get("package_title") if meta_licenses else None,
            "business_licenses_sampled": bool(meta_licenses and meta_licenses.get("sampled")),
            "section_status": {"311": "available" if summary is not None else "unavailable",
                               "business_licenses": "available" if licenses is not None else "unavailable"},
            "city_contacts": contact}

NWS_BASE = "https://api.weather.gov"
# NWS requires an identifying User-Agent; the repo URL is the contact.
NWS_HEADERS = {"User-Agent": "BoundlessBostonNavigator (https://github.com/paruchurisid/Boundless-Boston)", "Accept": "application/geo+json"}

def nws_period_at(data: dict[str, Any] | None, target: datetime) -> dict[str, Any] | None:
    """The hourly NWS forecast period covering target, as temperature_f and precipitation_chance_pct."""
    for period in (data or {}).get("properties", {}).get("periods", []):
        try:
            begins, ends = datetime.fromisoformat(period["startTime"]), datetime.fromisoformat(period["endTime"])
            temp = float(period["temperature"])
        except (KeyError, TypeError, ValueError):
            continue
        if begins <= target < ends:
            if period.get("temperatureUnit") == "C":
                temp = temp * 9 / 5 + 32
            chance = (period.get("probabilityOfPrecipitation") or {}).get("value")
            return {"temperature_f": temp, "precipitation_chance_pct": chance, "forecast_for": period["startTime"], "source": "nws"}
    return None

# Big home games are the events that fill nearby bars; both schedules are public and need no key.
SPORTS_VENUES = {"Fenway Park": (42.3467, -71.0972), "TD Garden": (42.3662, -71.0621)}
_SPORTS: dict[str, Any] = {}

def _mlb_home_games(data: Any) -> list[dict[str, Any]] | None:
    try:
        games = []
        for day in data.get("dates", []):
            for g in day.get("games", []):
                status = g.get("status") or {}
                if status.get("codedGameState") in ("D", "C") or status.get("detailedState") in ("Postponed", "Cancelled"):
                    continue  # rainouts stay in the schedule at their original time
                venue = (g.get("venue") or {}).get("name")
                if venue in SPORTS_VENUES and g.get("gameDate"):
                    away = (((g.get("teams") or {}).get("away") or {}).get("team") or {}).get("name", "visitors")
                    games.append({"start": datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00")), "venue": venue, "label": f"Red Sox vs {away}"})
        return games
    except (AttributeError, TypeError, ValueError, KeyError):
        return None  # unexpected shape counts as the feed being down, never a failed search

def _nhl_home_games(data: Any) -> list[dict[str, Any]] | None:
    try:
        games = []
        for g in data.get("games", []):
            venue = (g.get("venue") or {}).get("default")
            if venue in SPORTS_VENUES and g.get("startTimeUTC") and g.get("gameScheduleState", "OK") == "OK":
                away = ((g.get("awayTeam") or {}).get("commonName") or {}).get("default", "visitors")
                games.append({"start": datetime.fromisoformat(g["startTimeUTC"].replace("Z", "+00:00")), "venue": venue, "label": f"Bruins vs {away}"})
        return games
    except (AttributeError, TypeError, ValueError, KeyError):
        return None

async def boston_home_games() -> list[dict[str, Any]] | None:
    """Red Sox (MLB) and Bruins (NHL) home games, refreshed every 6 h. A failed feed keeps its last good list and is
    retried in 5 min; None only when neither team has ever loaded."""
    if _SPORTS and clock.time() < _SPORTS["fresh_until"]:
        return _SPORTS.get("games")  # absent after a failed first fetch (backoff with nothing to serve)
    today = datetime.now(ZoneInfo("America/New_York")).date()
    season = f"{today.year}{today.year + 1}" if today.month >= 7 else f"{today.year - 1}{today.year}"
    mlb, nhl = await asyncio.gather(
        request_json("sports", "https://statsapi.mlb.com/api/v1/schedule",
                     {"sportId": 1, "teamId": 111, "startDate": (today - timedelta(days=1)).isoformat(), "endDate": (today + timedelta(days=2)).isoformat()}),
        request_json("sports", f"https://api-web.nhle.com/v1/club-schedule-season/BOS/{season}"))
    by_team = _SPORTS.setdefault("by_team", {})
    fresh = {"mlb": None if mlb is None else _mlb_home_games(mlb), "nhl": None if nhl is None else _nhl_home_games(nhl)}
    for team, games in fresh.items():
        if games is not None:
            by_team[team] = games
    _SPORTS["fresh_until"] = clock.time() + (6 * 3600 if all(g is not None for g in fresh.values()) else 300)
    _SPORTS["games"] = [g for games in by_team.values() for g in games] if by_team else None
    return _SPORTS["games"]

def games_around(games: list[dict[str, Any]] | None, when: datetime) -> list[dict[str, Any]] | None:
    """Games that started up to 3 h before, or start within 3 h after, the requested time (crowds arriving or leaving)."""
    if games is None:
        return None
    return [g for g in games if timedelta(hours=-3) <= g["start"] - when <= timedelta(hours=3)]

async def forecast_for_query(q: QueryInput) -> dict[str, Any]:
    if DEMO:
        result = {"temperature_f": 55.0, "precipitation_chance_pct": 0, "source": "demo_fixture"}
    else:
        # NWS redirects coordinates with more than 4 decimals, so round first.
        point = await request_json("nws", f"{NWS_BASE}/points/{q.lat:.4f},{q.lng:.4f}", headers=NWS_HEADERS)
        hourly_url = (point or {}).get("properties", {}).get("forecastHourly")
        data = await request_json("nws", hourly_url, headers=NWS_HEADERS) if hourly_url else None
        result = nws_period_at(data, q.time)
        if result is None:
            result = {"temperature_f": None, "precipitation_chance_pct": None, "forecast_for": q.time.isoformat(), "source": "unavailable"}
            if HEALTH["nws"]["status"] not in ("disabled", "open-circuit"):
                HEALTH["nws"].update(status="disabled", detail="Forecast hour unavailable")
    if q.weather_override == "rain":
        result["precipitation_chance_pct"] = 100
        result["override"] = "rain"
    elif q.weather_override == "cold":
        result["temperature_f"] = min(float(result.get("temperature_f") or 40), 35.0)
        result["override"] = "cold"
    return result

async def make_query(q: QueryInput) -> dict[str,Any]:
    parsed=await parse_query_text(q.free_text)
    budget=parsed.get("budget",q.budget); walk=parsed.get("max_walk_min",q.max_walk_min)
    places,_=await live_candidates(q)
    backup=not DEMO and not places  # Google unavailable (no key, quota, outage): fall back to the OSM snapshot, never mixed
    if backup: places=osm_candidates(q,parsed.get("category"))
    else: HEALTH["overpass"].update(status="disabled", detail="Standby: used only when Google Places is unavailable")
    # Google Places coordinates must not go to a non-Google routing service (Maps ToS 3.2.3(a),(c)), so only
    # non-Google candidates are routed; Google venues keep the labeled straight-line estimate.
    to_route=[v for v in places if routable(v)]
    routed=await routed_walk_minutes(q.lat,q.lng,to_route)
    for venue,minutes in zip(to_route,routed or []):
        if minutes is not None:
            venue["walk_min"],venue["walk_method"]=minutes,"routed"
    weather,games=await asyncio.gather(forecast_for_query(q),boston_home_games()) if not DEMO else (await forecast_for_query(q),None)
    if DEMO:  # one labeled demo game: TD Garden, 7 pm on the search's Boston date
        day=q.time.astimezone(ZoneInfo("America/New_York")).date()
        games=[{"start":datetime.combine(day,datetime.min.time(),ZoneInfo("America/New_York")).replace(hour=19),"venue":"TD Garden","label":"Bruins vs Demo Rivals (demo)"}]
        HEALTH["sports"].update(status="demo",detail="Demo game fixture at TD Garden, 7 pm")
    games=games_around(games,q.time)
    max_price={"$":1,"$$":2,"$$$":3}[budget]
    pre_candidates=[]
    for venue in places:
        if venue.get("lat") is None or venue.get("lng") is None: continue
        if venue.get("open_hours",{}).get("status_at_requested_time")!="open": continue
        # OSM has no price levels; backup venues stay eligible and the card says "price unknown".
        if venue.get("price_level") is None and not backup: continue
        if venue.get("price_level") is not None and venue["price_level"]>max_price: continue
        if not matches_category(venue,parsed.get("category")): continue
        pre_candidates.append(venue)
    # Walk-only searches skip the MBTA; otherwise check the T for places that are a long walk or beyond the limit.
    to_assess=[] if q.travel=="walk" else [v for v in pre_candidates if v.get("walk_min") is None or v["walk_min"]>min(walk,15)]
    origin_stops=[] if DEMO or not to_assess else await mbta_nearby_stops(q.lat,q.lng)
    if DEMO:
        HEALTH["mbta"].update(status="demo", detail="Demo transit fixtures (Red, Green and Orange Line trips)")
        plans={v["id"]: await assess_mbta_round_trip(q,v,origin_stops) for v in to_assess}
    else:
        limit=asyncio.Semaphore(5)  # bounds the MBTA burst (each venue can make dozens of calls) so 429s don't trip the breaker
        async def assess(v: dict[str, Any]) -> dict[str, Any]:
            async with limit: return await assess_mbta_round_trip(q,v,origin_stops)
        plan_values=await asyncio.gather(*(assess(v) for v in to_assess), return_exceptions=True)
        plans={v["id"]:(plan if isinstance(plan,dict) else {"reachable":False,"reach_value":0.0,"method":"unavailable","label":"MBTA plan unavailable"}) for v,plan in zip(to_assess,plan_values)}
    eligible=[]
    for v in pre_candidates:
        reach=reach_for(v.get("walk_min"),walk,plans.get(v["id"],{"reachable":False,"reach_value":0.0,"method":"unavailable"}),q.travel)
        if reach: eligible.append((v,reach))
    ratings=sorted(v["rating"] for v,_ in eligible if v.get("rating") is not None)
    median=statistics.median(ratings) if ratings else 3.0
    candidates=[]
    for v,reach in eligible:
        v["walk_estimate"]={"minutes":v["walk_min"],"method":v.get("walk_method","fixture_estimate"),"label":"approx." if v.get("walk_method") not in (None,"routed") else None}
        near=None if games is None else [g for g in games if haversine(v["lat"],v["lng"],*SPORTS_VENUES[g["venue"]])<=SCORING["events"]["radius_m"]]
        v["nearby_events"]=None if near is None else len(near)
        v["nearby_games"]=[f'{g["label"]} at {g["venue"]}, {g["start"].astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M %p")}' for g in near or []]
        scored=score_venue(v,median,weather,reach)
        candidates.append({"venue":v,"score":scored,"reachability":reach,
                           "explanation":(f"Open at your requested time, within budget, and about {v['walk_min']} minutes on foot; walk time is an estimate where labeled." if reach["method"]=="walking_fallback"
                                         else f"Open at your requested time and within budget; about {reach.get('total_min')} minutes door to door by T: {transit_summary(reach) or reach['outbound']['route']}."),
                           "reach_explanation":reach.get("label")})
    candidates.sort(key=lambda x:(-x["score"]["value"],x["venue"]["walk_min"]))  # ties (common in the OSM backup) go to the shorter walk
    candidates=candidates[:8]
    for c in candidates:
        c["explain_facts"]=explanation_facts(c)
    used=["google_places","mbta","nws","sports"]+(["overpass"] if backup else [])+(["routing"] if to_route else [])+(["gemini"] if q.free_text else [])
    return envelope({"query":{"time":q.time.isoformat(),"budget":budget,"lat":q.lat,"lng":q.lng,"max_walk_min":walk,"travel":q.travel,"free_text":q.free_text,"parsed_filters":parsed,"weather_override":q.weather_override},"recommendations":candidates,"empty_message":None if candidates else "Nothing open and reachable at that time. Try an earlier hour or a higher budget.","weather":weather},used)

@app.on_event("startup")
async def discover_boston_resources() -> None:
    # Resolve CKAN resource IDs from package metadata; never pin deployment-specific IDs.
    if not DEMO:
        await resolve_ckan_resources(force=True)

@app.get("/api/health")
def health() -> dict[str,str]: return {"status":"ok"}
# Per-visitor and site-wide sliding windows (requests per 60 s) on the endpoints that spend Google/Gemini/ORS/MBTA quota.
RATE_LIMITS = {"/api/query": (30, 120), "/api/recommendations": (30, 120), "/api/explain": (30, 120)}
_HITS: dict[tuple[str, str], deque[float]] = {}

def client_key(request: Request) -> str:
    # shortcut: trusts the left-most X-Forwarded-For (set by Render's proxies), which a client can spoof to dodge the
    # per-visitor limit; the site-wide cap still bounds total spend. Upgrade if Render exposes a verified client-IP header.
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")

@app.middleware("http")
async def rate_limit(request: Request, call_next):
    limits = RATE_LIMITS.get(request.url.path)
    if limits and request.method != "OPTIONS":  # CORS preflights don't spend quota
        now, path = clock.time(), request.url.path
        windows = [((client_key(request), path), limits[0]), (("*", path), limits[1])]
        for key, cap in windows:
            hits = _HITS.get(key) or deque()  # no entry until accepted, so rejected floods can't grow memory
            while hits and hits[0] <= now - 60:
                hits.popleft()
            if len(hits) >= cap:
                retry = max(1, int(hits[0] + 60 - now) + 1)
                who = "this visitor" if key[0] != "*" else "the site"
                return JSONResponse(status_code=429, headers={"Retry-After": str(retry)},
                                    content={"error": {"code": "rate_limited", "message": f"Too many requests from {who}; try again in {retry} s."},
                                             "sources_used": [], "generated_at": now_iso()})
        for key, _ in windows:
            _HITS.setdefault(key, deque()).append(now)
        if len(_HITS) > 5000:  # forget idle visitors so memory stays bounded
            for key in [k for k, v in _HITS.items() if not v or v[-1] <= now - 60]:
                del _HITS[key]
    return await call_next(request)

@app.post("/api/query")
async def query(q: QueryInput) -> dict[str,Any]: return await make_query(q)
@app.post("/api/explain")
async def explain(f: ExplainInput) -> dict[str,Any]:
    why=await gemini_explanation(f.model_dump())
    return envelope({"id":f.id,"explanation":why,"source":"gemini" if why else "unavailable"},["gemini_explain"])
@app.get("/api/recommendations")
async def recommendations(time: datetime, budget: Literal["$","$$","$$$"], lat: float, lng: float, max_walk_min: int=Query(ge=1,le=120), free_text: str|None=None, weather_override: Literal["clear","rain","cold"]|None=None) -> dict[str,Any]:
    return await make_query(QueryInput(time=time,budget=budget,lat=lat,lng=lng,max_walk_min=max_walk_min,free_text=free_text,weather_override=weather_override))
@app.get("/api/neighborhood")
async def neighborhood(lat:float=Query(ge=-90,le=90),lng:float=Query(ge=-180,le=180),radius_m:int=Query(ge=50,le=5000)) -> dict[str,Any]:
    if not DEMO:
        result=await live_neighborhood(lat,lng,radius_m)
        return envelope(result,["boston_ckan"])
    return envelope({"center":{"lat":lat,"lng":lng},"radius_m":radius_m,"311":{"period_start":(datetime.now(timezone.utc)-timedelta(days=90)).date().isoformat(),"period_end":datetime.now(timezone.utc).date().isoformat(),"top_categories":[{"category":"Street cleaning","count":42},{"category":"Pothole","count":28},{"category":"Sidewalk repair","count":19}]},"business_licenses":[{"name":"Newbury Street Cafe","issued_at":(datetime.now(timezone.utc)-timedelta(days=12)).date().isoformat(),"lat":42.351,"lng":-71.071,"source_ref":"demo-license-001"}],"city_contacts":[{"name":"311 Boston","service":"City services and non-emergency requests","phone":"311","url":"https://www.boston.gov/departments/boston-311","distance_m":0,"source_ref":"demo-contact-311"}]},["boston_ckan"])
@app.get("/api/sources/health")
def source_health() -> dict[str,Any]: return envelope({"sources":[HEALTH[s] for s in SOURCES]},[])
