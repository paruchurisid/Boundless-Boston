"""Refresh the bundled OpenStreetMap venue snapshot (no key needed).

Run occasionally (e.g. weekly):  .venv/bin/python scripts/refresh_osm_snapshot.py
Public Overpass servers often take 30-60 s or time out, so the app never queries them live; it reads this file.
Data © OpenStreetMap contributors, ODbL 1.0 (attribution shown in the app).
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BBOX = (42.30, -71.15, 42.40, -71.00)  # south, west, north, east: Boston core + Cambridge/Somerville edge
AMENITIES = "restaurant|cafe|bar|pub|fast_food|nightclub|ice_cream"
KEEP = ("name", "amenity", "leisure", "cuisine", "opening_hours", "addr:housenumber", "addr:street", "website")
ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]
OUT = Path(__file__).resolve().parents[1] / "backend" / "data" / "osm_venues.json"


def query(box: tuple[float, float, float, float]) -> str:
    b = "(%s,%s,%s,%s)" % box
    return (f'[out:json][timeout:120];(nwr["amenity"~"^({AMENITIES})$"]["name"]{b};'
            f'nwr["leisure"="park"]["name"]{b};);out center tags;')


def tiles(n: int = 3) -> list[tuple[float, float, float, float]]:
    """Split BBOX into n×n tiles: small queries finish on busy public servers where one big one 502s."""
    s, w, north, e = BBOX
    dlat, dlng = (north - s) / n, (e - w) / n
    return [(s + i * dlat, w + j * dlng, s + (i + 1) * dlat, w + (j + 1) * dlng) for i in range(n) for j in range(n)]


TILE_CACHE = Path(__file__).resolve().parent / ".osm_tiles"  # finished tiles, so a rerun resumes instead of starting over


def fetch(box: tuple[float, float, float, float], depth: int = 0) -> list[dict]:
    """One tile, cached on disk; a tile the busy servers can't finish is split into 4 smaller ones (up to 2 levels)."""
    TILE_CACHE.mkdir(exist_ok=True)
    cached = TILE_CACHE / ("%.5f_%.5f_%.5f_%.5f.json" % box)
    if cached.exists():
        return json.loads(cached.read_text())
    headers = {"User-Agent": "BoundlessBostonNavigator (https://github.com/paruchurisid/Boundless-Boston)"}
    for attempt in range(2):
        for url in ENDPOINTS:
            try:
                r = httpx.get(url, params={"data": query(box)}, headers=headers, timeout=150)
                r.raise_for_status()
                elements = r.json()["elements"]
                cached.write_text(json.dumps(elements))
                print(f"tile {box}: {len(elements)} elements via {url}", file=sys.stderr, flush=True)
                time.sleep(5)  # Overpass allows ~2 concurrent slots per IP; spacing avoids 429s
                return elements
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                code = getattr(getattr(exc, "response", None), "status_code", "")
                print(f"tile {box} attempt {attempt + 1} {url}: {type(exc).__name__} {code}", file=sys.stderr, flush=True)
            time.sleep(15 * (attempt + 1))
    if depth < 2:
        s_, w, n, e = box
        mlat, mlng = (s_ + n) / 2, (w + e) / 2
        print(f"splitting tile {box}", file=sys.stderr, flush=True)
        return [el for sub in ((s_, w, mlat, mlng), (s_, mlng, mlat, e), (mlat, w, n, mlng), (mlat, mlng, n, e))
                for el in fetch(sub, depth + 1)]
    raise RuntimeError(f"tile {box} failed")


def main() -> int:
    seen, venues = set(), []
    try:
        elements = [el for box in tiles() for el in fetch(box)]
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1  # keep the previous snapshot rather than writing a partial one
    for el in elements:
        key = f"{el['type']}/{el['id']}"
        lat, lng = el.get("lat", el.get("center", {}).get("lat")), el.get("lon", el.get("center", {}).get("lon"))
        tags = el.get("tags", {})
        if key in seen or lat is None or lng is None or not tags.get("name"):
            continue
        seen.add(key)
        venues.append({"osm": key, "lat": round(lat, 6), "lng": round(lng, 6), **{k: tags[k] for k in KEEP if k in tags}})
    OUT.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "bbox": BBOX, "license": "ODbL 1.0, © OpenStreetMap contributors",
                               "venues": venues}, separators=(",", ":")))
    print(f"wrote {len(venues)} venues to {OUT} ({OUT.stat().st_size // 1024} KB)")
    for f in TILE_CACHE.glob("*.json"):
        f.unlink()  # next refresh fetches fresh data
    return 0


if __name__ == "__main__":
    sys.exit(main())
