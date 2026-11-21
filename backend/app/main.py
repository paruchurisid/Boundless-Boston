from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import sqlite3
import time as clock
import asyncio
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parents[2]
DEMO = os.getenv("APP_MODE", "demo") == "demo"
DB_PATH = Path(os.getenv("CACHE_DB", str(ROOT / ".cache" / "public-cache.sqlite3")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(DB_PATH) as _db:
    _db.execute("CREATE TABLE IF NOT EXISTS cache(source TEXT,key TEXT,payload TEXT,fetched REAL,PRIMARY KEY(source,key))")
app = FastAPI(title="Boundless Boston Navigator API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","), allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

SOURCES = ["google_places", "mbta", "nws", "boston_ckan", "ticketmaster", "yelp", "overpass", "routing", "gemini", "census_acs"]
HEALTH: dict[str, dict[str, Any]] = {s: {"source": s, "status": "demo" if DEMO and s in SOURCES[:4] else "disabled", "checked_at": None, "last_success_at": None, "cache_age_s": None, "detail": "Fixture mode" if DEMO and s in SOURCES[:4] else "Not configured"} for s in SOURCES}
FAILURES: dict[str, int] = {s: 0 for s in SOURCES}
OPEN_UNTIL: dict[str, float] = {}
HALF_OPEN_PROBES: set[str] = set()
TTL = {"google_places": 300, "mbta": 60, "nws": 600, "boston_ckan": 3600}
CKAN_BASE = os.getenv("BOSTON_CKAN_URL", "https://data.boston.gov/api/3/action")
MBTA_BASE = "https://api-v3.mbta.com"
CKAN_RESOURCES: dict[str, dict[str, Any]] = {}
CKAN_RESOLVED_AT = 0.0

class QueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    free_text: str | None = Field(default=None, max_length=300)
    time: datetime
    budget: Literal["$", "$$", "$$$"]
    lat: float
    lng: float
    max_walk_min: int = Field(ge=1, le=120)
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
]


def now_iso() -> str: return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
def source_use(source: str, status: str | None = None) -> dict[str, Any]:
    h = HEALTH[source]
    attributions = {
        "google_places": [{"source": source, "text": "Google Maps", "url": "https://maps.google.com", "required_logo": "Google Maps", "translate_no": True}],
        "mbta": [{"source": source, "text": "MBTA V3 API", "url": "https://api-v3.mbta.com/"}],
        "nws": [{"source": source, "text": "Weather data by the National Weather Service", "url": "https://www.weather.gov/"}],
        "boston_ckan": [{"source": source, "text": "City of Boston Open Data", "url": "https://data.boston.gov/"}],
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

async def request_json(source: str, url: str, params: dict[str, Any] | None = None,
                       headers: dict[str, str] | None = None, method: str = "GET",
                       json_body: dict[str, Any] | None = None) -> Any | None:
    """One outbound HTTP path with bounded retries, cache, and per-source breaker."""
    if DEMO:
        return None
    params = params or {}
    cache_key = normalized_params({"url": url, "params": params, "body": json_body, "method": method})
    cache_allowed = source != "google_places"
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
    last_code = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(4.0)) as client:
                response = await client.request(method, url, params=params, headers=headers, json=json_body)
            last_code = response.status_code
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
    status = ("upstream unavailable" if retryable_status else "upstream request failed") + (f" (HTTP {last_code})" if last_code else " (no response)")
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
    delta=v.get("momentum_delta"); momentum=min(1,max(0,delta or 0)/10)
    momentum_meta=v.get("momentum_meta") or {"method":"demo_fixture","label":"demo"}
    reviews=v.get("review_count") or 0; rating=v.get("rating")
    quality=.5 if rating is None else (((reviews/(reviews+50))*rating+(50/(reviews+50))*median)/5 if reviews+50 else rating/5)
    reach_value=float(reach.get("reach_value", 0.0))
    events=0.0
    adverse=(weather.get("precipitation_chance_pct") or 0)>=50 or (weather.get("temperature_f") is not None and weather["temperature_f"]<40)
    mood=1.0 if (adverse and v["indoor_outdoor"]=="indoor") else (0.0 if adverse and v["indoor_outdoor"]=="outdoor" else .5)
    components={"momentum":{"value":momentum,"weight":.3,"raw":{"review_delta_30d":delta,**momentum_meta},"sources":["google_places"],"label":momentum_meta.get("label"),"missing_reason":momentum_meta.get("missing_reason")},"quality":{"value":quality,"weight":.3,"raw":{"rating":rating,"review_count":reviews,"prior_reviews":50,"prior_rating":median},"sources":["google_places"]},"reach":{"value":reach_value,"weight":.2,"raw":reach,"sources":["mbta"]},"events":{"value":events,"weight":.1,"raw":{"nearby_events":None},"sources":["ticketmaster"],"missing_reason":"Tier 2 not configured"},"weather":{"value":mood,"weight":.1,"raw":weather,"sources":["nws"],"missing_reason":"weather unavailable" if weather.get("temperature_f") is None and weather.get("precipitation_chance_pct") is None else None}}
    total=sum(c["value"]*c["weight"] for c in components.values())
    return {"value":round(total,4),"components":components}

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

def walk_estimate_minutes(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    # Conservative street-grid multiplier over straight-line distance; always disclosed as an estimate.
    return max(1, math.ceil(haversine(lat1, lng1, lat2, lng2) * 1.3 / 78.0))

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

async def mbta_nearby_stops(lat: float, lng: float, radius_m: int = 1200) -> list[dict[str, Any]]:
    params = {"filter[latitude]": lat, "filter[longitude]": lng, "filter[radius]": 0.015, "filter[location_type]": "0,1", "sort": "distance", "page[limit]": 100}  # radius is in degrees (0.015 ≈ 1.2-1.7 km here); 0,1 = stops and stations, not entrances/stairs
    headers={"x-api-key":os.environ["MBTA_API_KEY"]} if os.getenv("MBTA_API_KEY") else None
    data = await request_json("mbta", f"{MBTA_BASE}/stops", params, headers=headers)
    if not data:
        return []
    stops = []
    for stop in data.get("data", []):
        attrs = stop.get("attributes", {})
        slat, slng = attrs.get("latitude"), attrs.get("longitude")
        if slat is None or slng is None:
            continue
        distance = haversine(lat, lng, slat, slng)
        if distance <= radius_m:
            stops.append({"id": stop["id"], "name": attrs.get("name", "MBTA stop"), "lat": slat, "lng": slng, "distance_m": distance})
    return sorted(stops, key=lambda s: s["distance_m"])[:3]

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

async def mbta_route_alerts(stop_id: str, route_id: str) -> list[dict[str, Any]]:
    params={"filter[stop]":stop_id,"filter[route]":route_id,"filter[activity]":"BOARD","page[limit]":50}
    headers={"x-api-key":os.environ["MBTA_API_KEY"]} if os.getenv("MBTA_API_KEY") else None
    data=await request_json("mbta",f"{MBTA_BASE}/alerts",params,headers=headers)
    return (data or {}).get("data",[])

async def assess_mbta_round_trip(q: QueryInput, venue: dict[str, Any], origin_stops: list[dict[str, Any]]) -> dict[str, Any]:
    if DEMO:
        return {"reachable": False, "reach_value": 0.5, "method": "walking_fallback", "outbound": None, "return": None,
                "label": "Demo transit fixtures; walking estimate used"}
    venue_stops = await mbta_nearby_stops(venue["lat"], venue["lng"])
    if not origin_stops or not venue_stops:
        return {"reachable": False, "reach_value": 0.5, "method": "walking_fallback", "outbound": None, "return": None,
                "label": "No nearby MBTA stop pair; walking fallback"}
    stop_ids = list(dict.fromkeys(s["id"] for s in origin_stops + venue_stops))
    route_results = await asyncio.gather(*(mbta_routes_at(sid) for sid in stop_ids))
    routes_by_stop = dict(zip(stop_ids, route_results))
    depart = q.time.astimezone(timezone.utc)
    return_after = depart + timedelta(hours=3)
    return_before = depart + timedelta(hours=8)
    for origin in origin_stops:
        for destination in venue_stops:
            shared = routes_by_stop.get(origin["id"], set()) & routes_by_stop.get(destination["id"], set())
            for route_id in shared:
                alerts_a,alerts_b=await asyncio.gather(mbta_route_alerts(origin["id"],route_id),mbta_route_alerts(destination["id"],route_id))
                blocked_effects={"NO_SERVICE","SUSPENSION"}
                if any(a.get("attributes",{}).get("effect") in blocked_effects for a in alerts_a+alerts_b):
                    continue
                # A valid leg must be the same trip at both ends, in the correct time order.
                for direction in (0, 1):
                    out_a, out_b = await asyncio.gather(
                        mbta_schedules(origin["id"], route_id, direction, depart, depart + timedelta(minutes=75)),
                        mbta_schedules(destination["id"], route_id, direction, depart, depart + timedelta(minutes=75)),
                    )
                    origin_trips = { _resource_trip_id(x): _event_time(x,"departure") for x in out_a if _resource_trip_id(x) }
                    destination_trips = { _resource_trip_id(x): _event_time(x,"arrival") for x in out_b if _resource_trip_id(x) }
                    outbound_ids = {tid for tid, t in origin_trips.items() if t and tid in destination_trips and destination_trips[tid] and t < destination_trips[tid] <= depart+timedelta(minutes=75)}
                    if not outbound_ids:
                        continue
                    return_direction = 1 - direction
                    ret_a, ret_b = await asyncio.gather(
                        mbta_schedules(destination["id"], route_id, return_direction, return_after, return_before),
                        mbta_schedules(origin["id"], route_id, return_direction, return_after, return_before),
                    )
                    venue_trips = {_resource_trip_id(x): _event_time(x,"departure") for x in ret_a if _resource_trip_id(x)}
                    home_trips = {_resource_trip_id(x): _event_time(x,"arrival") for x in ret_b if _resource_trip_id(x)}
                    return_ids = {tid for tid, t in venue_trips.items() if t and t >= return_after and tid in home_trips and home_trips[tid] and t < home_trips[tid]}
                    if return_ids:
                        # Confirm service is currently represented by predictions at either end.
                        predicted_out, predicted_back = await asyncio.gather(
                            mbta_predictions(origin["id"], route_id, direction),
                            mbta_predictions(destination["id"], route_id, return_direction),
                        )
                        live_confirmed = bool(predicted_out & outbound_ids) and bool(predicted_back & return_ids)
                        out_id, ret_id = min(outbound_ids, key=origin_trips.__getitem__), min(return_ids, key=venue_trips.__getitem__)
                        return {"reachable": True, "reach_value": 1.0 if live_confirmed else 0.5,
                                "method": "predicted_round_trip" if live_confirmed else "scheduled_round_trip",
                                "outbound": {"from_stop": origin["name"], "to_stop": destination["name"], "route": route_id,
                                             "depart_at":origin_trips[out_id].isoformat(),"arrive_at":destination_trips[out_id].isoformat()},
                                "return": {"from_stop": destination["name"], "to_stop": origin["name"], "route": route_id,
                                           "depart_at":venue_trips[ret_id].isoformat(),"arrive_at":home_trips[ret_id].isoformat(),
                                           "before_last_service": True},
                                "label": "Live predictions and scheduled return" if live_confirmed else "Scheduled round trip; prediction unavailable"}
    return {"reachable": False, "reach_value": 0.5, "method": "walking_fallback", "outbound": None, "return": None,
            "label": "No matching scheduled round trip; walking fallback"}

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
    parsed=parse_free_text(q.free_text)
    budget=parsed.get("budget",q.budget); walk=parsed.get("max_walk_min",q.max_walk_min)
    places,_=await live_candidates(q)
    weather=await forecast_for_query(q)
    max_price={"$":1,"$$":2,"$$$":3}[budget]
    pre_candidates=[]
    for venue in places:
        if venue.get("lat") is None or venue.get("lng") is None: continue
        if venue.get("open_hours",{}).get("status_at_requested_time")!="open": continue
        if venue.get("price_level") is None or venue["price_level"]>max_price: continue
        if venue.get("walk_min") is None or venue["walk_min"]>walk: continue
        if not matches_category(venue,parsed.get("category")): continue
        pre_candidates.append(venue)
    origin_stops=[] if DEMO or not pre_candidates else await mbta_nearby_stops(q.lat,q.lng)
    if DEMO:
        HEALTH["mbta"].update(status="demo", detail="Demo transit fixtures; reach uses walking fallback")
        plans={v["id"]: await assess_mbta_round_trip(q,v,origin_stops) for v in pre_candidates}
    else:
        plan_values=await asyncio.gather(*(assess_mbta_round_trip(q,v,origin_stops) for v in pre_candidates), return_exceptions=True)
        plans={v["id"]:(plan if isinstance(plan,dict) else {"reachable":False,"reach_value":0.0,"method":"unavailable","label":"MBTA plan unavailable"}) for v,plan in zip(pre_candidates,plan_values)}
    eligible=[]
    for v in pre_candidates:
        reach=plans.get(v["id"],{"reachable":False,"reach_value":0.0,"method":"unavailable"})
        walking_fallback=v.get("walk_min") is not None and v["walk_min"]<=walk
        if not reach.get("reachable") and not walking_fallback: continue
        if not reach.get("reachable"):
            reach={**reach,"reachable":True,"reach_value":0.5,"method":"walking_fallback"}
        eligible.append((v,reach))
    ratings=sorted(v["rating"] for v,_ in eligible if v.get("rating") is not None)
    median=ratings[len(ratings)//2] if ratings else 3.0
    candidates=[]
    for v,reach in eligible:
        v["walk_estimate"]={"minutes":v["walk_min"],"method":v.get("walk_method","fixture_estimate"),"label":"approx." if v.get("walk_method") else None}
        scored=score_venue(v,median,weather,reach)
        candidates.append({"venue":v,"score":scored,"reachability":reach,
                           "explanation":f"Open at your requested time, within budget, and about {v['walk_min']} minutes on foot; walk time is an estimate where labeled.",
                           "reach_explanation":reach.get("label")})
    candidates.sort(key=lambda x:x["score"]["value"],reverse=True)
    used=["google_places","mbta","nws"]
    return envelope({"query":{"time":q.time.isoformat(),"budget":budget,"lat":q.lat,"lng":q.lng,"max_walk_min":walk,"free_text":q.free_text,"parsed_filters":parsed,"weather_override":q.weather_override},"recommendations":candidates[:8],"empty_message":None if candidates else "Nothing open and reachable at that time. Try an earlier hour or a higher budget.","weather":weather},used)

@app.on_event("startup")
async def discover_boston_resources() -> None:
    # Resolve CKAN resource IDs from package metadata; never pin deployment-specific IDs.
    if not DEMO:
        await resolve_ckan_resources(force=True)

@app.get("/api/health")
def health() -> dict[str,str]: return {"status":"ok"}
@app.post("/api/query")
async def query(q: QueryInput) -> dict[str,Any]: return await make_query(q)
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
