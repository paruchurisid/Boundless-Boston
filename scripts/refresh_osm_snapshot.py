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


def fetch(box: tuple[float, float, float, float]) -> list[dict]:
    headers = {"User-Agent": "BoundlessBostonNavigator (https://github.com/paruchurisid/Boundless-Boston)"}
    for attempt in range(3):
        for url in ENDPOINTS:
            try:
                r = httpx.get(url, params={"data": query(box)}, headers=headers, timeout=150)
                r.raise_for_status()
                return r.json()["elements"]
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                print(f"tile {box} attempt {attempt + 1} {url}: {type(exc).__name__}", file=sys.stderr)
        time.sleep(20 * (attempt + 1))  # be polite to the shared servers
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
