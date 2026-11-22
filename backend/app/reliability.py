"""Last-train reliability from Tiger Data (TimescaleDB): how late trains actually ran tonight.

The recorder (`python -m app.reliability`, run from backend/) polls MBTA predictions once a minute at stations students
use and upserts each departure's latest prediction next to its schedule. Once a train has left, its row holds the
last prediction seen, which is close to when it really departed. The API reads per-line, per-station averages.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Any

import httpx

try:
    import asyncpg
except ImportError:  # demo mode runs without the database driver
    asyncpg = None

MBTA_BASE = "https://api-v3.mbta.com"
# Parent stations; predictions come back per platform and are mapped to these through parent_station.
STATIONS = {
    "place-harsq": "Harvard", "place-knncl": "Kendall/MIT", "place-pktrm": "Park Street", "place-dwnxg": "Downtown Crossing",
    "place-kencl": "Kenmore", "place-fenwy": "Fenway", "place-bucen": "Boston University Central", "place-coecl": "Copley",
    "place-bbsta": "Back Bay", "place-north": "North Station", "place-astao": "Assembly", "place-chncl": "Chinatown",
}
MIN_TRAINS = 5  # below this an average is noise, so the card shows nothing
WINDOW_H = 12  # cards report the last 12 hours, so a noon demo still covers the night before
# A train counts once it has dropped out of the MBTA feed (the recorder stopped updating it), i.e. it has left;
# a late train still on its way holds a mid-flight prediction and would pull the average toward on time.
# predicted_at <= now() also guards the case where the recorder itself stopped.
DEPARTED = "observed_at < now() - interval '2 minutes' AND predicted_at <= now()"
log = logging.getLogger(__name__)
SKIPPED = {"CANCELLED", "SKIPPED", "NO_DATA"}

_pool = None
_pool_lock = asyncio.Lock()
_status: dict[str, Any] = {"status": "not_checked"}
_down_until = 0.0  # after a failure, skip Tiger for a minute so searches don't each wait out the timeout


def configured() -> bool:
    return bool(os.getenv("TIGER_DATABASE_URL")) and asyncpg is not None


def status() -> dict[str, Any]:
    return {"status": "disabled"} if not configured() else dict(_status)


async def _db():
    global _pool
    async with _pool_lock:  # two cold-start requests must not each open a pool
        if _pool is None:
            _pool = await asyncpg.create_pool(os.environ["TIGER_DATABASE_URL"], min_size=0, max_size=5, command_timeout=4)
    return _pool


def _failed(e: Exception) -> None:
    global _status, _down_until
    _status, _down_until = {"status": "unavailable"}, time.monotonic() + 60
    log.warning("Tiger reliability query failed: %s", type(e).__name__)  # type only: never the connection string


def _parse_time(raw: str | None) -> datetime | None:
    return datetime.fromisoformat(raw) if raw else None


def parse_departures(payload: dict[str, Any]) -> list[tuple[datetime, str, str, int, str, datetime, int]]:
    """MBTA /predictions (include=schedule,stop) -> rows of
    (scheduled_at, station_id, route_id, direction_id, trip_id, predicted_at, delay_s). Departures only."""
    included = {(x["type"], x["id"]): x for x in payload.get("included", [])}
    rows = []
    for p in payload.get("data", []):
        a, rel = p.get("attributes", {}), p.get("relationships", {})
        if a.get("schedule_relationship") in SKIPPED:
            continue
        predicted = _parse_time(a.get("departure_time"))
        sched = included.get(("schedule", (rel.get("schedule", {}).get("data") or {}).get("id")))
        scheduled = _parse_time((sched or {}).get("attributes", {}).get("departure_time"))
        stop_id = (rel.get("stop", {}).get("data") or {}).get("id")
        stop = included.get(("stop", stop_id), {})
        station = (stop.get("relationships", {}).get("parent_station", {}).get("data") or {}).get("id") or stop_id
        route = (rel.get("route", {}).get("data") or {}).get("id")
        trip = (rel.get("trip", {}).get("data") or {}).get("id")
        if not (predicted and scheduled and station in STATIONS and route and trip):
            continue
        rows.append((scheduled, station, route, int(a.get("direction_id") or 0), trip, predicted,
                     round((predicted - scheduled).total_seconds())))
    return rows


UPSERT = """INSERT INTO train_departures (scheduled_at, station_id, route_id, direction_id, trip_id, predicted_at, delay_s, observed_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,now())
            ON CONFLICT (trip_id, station_id, scheduled_at)
            DO UPDATE SET predicted_at=EXCLUDED.predicted_at, delay_s=EXCLUDED.delay_s, observed_at=EXCLUDED.observed_at"""


async def record_once(client: httpx.AsyncClient) -> int:
    headers = {"x-api-key": os.environ["MBTA_API_KEY"]} if os.getenv("MBTA_API_KEY") else None
    r = await client.get(f"{MBTA_BASE}/predictions", headers=headers, params={
        "filter[stop]": ",".join(STATIONS), "filter[route_type]": "0,1", "include": "schedule,stop"})
    r.raise_for_status()
    rows = parse_departures(r.json())
    if rows:
        await (await _db()).executemany(UPSERT, rows)
    return len(rows)


async def run_recorder(interval_s: int = 60) -> None:
    if not configured():
        raise SystemExit("Set TIGER_DATABASE_URL (and pip install asyncpg) to record train reliability.")
    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            try:
                print(f"{datetime.now().isoformat(timespec='seconds')} recorded {await record_once(client)} departures", flush=True)
            except Exception as e:  # one bad minute (MBTA hiccup, DB blip) must not stop the overnight run
                print(f"{datetime.now().isoformat(timespec='seconds')} skipped: {type(e).__name__}", flush=True)
            await asyncio.sleep(interval_s)


def summary(avg_delay_s: float, trains: int) -> dict[str, Any] | None:
    """Card-ready numbers, or None when too few trains have run to say anything honest."""
    if trains < MIN_TRAINS:
        return None
    return {"avg_delay_min": round(avg_delay_s / 60, 1), "trains": trains}


async def recent(legs: list[tuple[str, str, int]]) -> dict[tuple[str, str, int], dict[str, Any]]:
    """{(route_id, station_id, direction_id): summary} over the last WINDOW_H hours, departed trains only."""
    global _status
    legs = [k for k in set(legs) if k[1] in STATIONS]
    if not configured() or not legs or time.monotonic() < _down_until:
        return {}
    try:
        async with asyncio.timeout(3):
            rows = await (await _db()).fetch(
                f"""SELECT route_id, station_id, direction_id, avg(delay_s)::float AS avg_delay_s, count(*) AS trains
                   FROM train_departures
                   WHERE scheduled_at >= now() - make_interval(hours => $4) AND {DEPARTED}
                     AND (route_id, station_id, direction_id) IN (SELECT * FROM unnest($1::text[], $2::text[], $3::smallint[]))
                   GROUP BY route_id, station_id, direction_id""",
                [k[0] for k in legs], [k[1] for k in legs], [k[2] for k in legs], WINDOW_H)
        _status = {"status": "connected"}
        return {(r["route_id"], r["station_id"], r["direction_id"]): s for r in rows if (s := summary(r["avg_delay_s"], r["trains"]))}
    except Exception as e:
        _failed(e)
        return {}


async def timeline(route_id: str, station_id: str, hours: int = WINDOW_H, bucket_min: int = 15) -> list[dict[str, Any]] | None:
    """Average delay per time bucket through the night (Timescale time_bucket), both directions, for the demo chart."""
    if not configured() or time.monotonic() < _down_until:
        return None
    try:
        async with asyncio.timeout(3):
            rows = await (await _db()).fetch(
                f"""SELECT time_bucket(make_interval(mins => $4), scheduled_at) AS bucket,
                          avg(delay_s)::float AS avg_delay_s, count(*) AS trains
                   FROM train_departures
                   WHERE route_id = $1 AND station_id = $2 AND scheduled_at >= now() - make_interval(hours => $3) AND {DEPARTED}
                   GROUP BY bucket ORDER BY bucket""",
                route_id, station_id, hours, bucket_min)
        return [{"bucket": r["bucket"].isoformat(), "avg_delay_min": round(r["avg_delay_s"] / 60, 1), "trains": r["trains"]} for r in rows]
    except Exception as e:
        _failed(e)
        return None


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    asyncio.run(run_recorder())
