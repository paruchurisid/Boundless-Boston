import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import app.main as m
from app import reliability as rel


def pred(trip, stop, predicted, schedule_id, relationship=None, route="Red"):
    return {"attributes": {"departure_time": predicted, "direction_id": 1, "schedule_relationship": relationship},
            "relationships": {"route": {"data": {"id": route}}, "trip": {"data": {"id": trip}},
                              "stop": {"data": {"id": stop}}, "schedule": {"data": {"id": schedule_id} if schedule_id else None}}}


def sched(schedule_id, departure):
    return {"type": "schedule", "id": schedule_id, "attributes": {"departure_time": departure}}


def platform(stop, parent):
    return {"type": "stop", "id": stop, "relationships": {"parent_station": {"data": {"id": parent}}}}


PAYLOAD = {
    "data": [
        pred("t1", "70068", "2026-11-21T23:50:30-05:00", "s1"),                # 2.5 min late at Harvard
        pred("t2", "70068", "2026-11-21T23:58:00-05:00", "s2", "CANCELLED"),   # cancelled: skipped
        pred("t3", "70068", "2026-11-22T00:05:00-05:00", None),                # no schedule to compare: skipped
        pred("t4", "70001", "2026-11-22T00:05:00-05:00", "s4"),                # station not recorded: skipped
        pred("t5", "70068", None, "s5"),                                       # arrival-only (terminal): skipped
    ],
    "included": [sched("s1", "2026-11-21T23:48:00-05:00"), sched("s2", "2026-11-21T23:58:00-05:00"),
                 sched("s4", "2026-11-22T00:04:00-05:00"), sched("s5", "2026-11-22T00:10:00-05:00"),
                 platform("70068", "place-harsq"), platform("70001", "place-forhl")],
}


def test_parse_keeps_real_departures_and_maps_platforms_to_stations():
    rows = rel.parse_departures(PAYLOAD)
    assert len(rows) == 1
    scheduled, station, route, direction, trip, predicted, delay = rows[0]
    assert (station, route, direction, trip, delay) == ("place-harsq", "Red", 1, "t1", 150)
    assert predicted - scheduled == timedelta(seconds=150)


def test_summary_needs_enough_trains():
    assert rel.summary(180.0, rel.MIN_TRAINS - 1) is None
    assert rel.summary(180.0, rel.MIN_TRAINS) == {"avg_delay_min": 3.0, "trains": rel.MIN_TRAINS}


def test_without_tiger_nothing_is_attached(monkeypatch):
    monkeypatch.delenv("TIGER_DATABASE_URL", raising=False)
    assert asyncio.run(rel.recent([("Red", "place-harsq", 1)])) == {}
    assert rel.status() == {"status": "disabled"}


def test_endpoint_validates_ids_and_reports_no_data(monkeypatch):
    monkeypatch.delenv("TIGER_DATABASE_URL", raising=False)
    c = TestClient(m.app)
    m._HITS.clear()
    r = c.get("/api/reliability", params={"route": "Red", "stop": "place-harsq", "direction": 1})
    assert r.status_code == 200 and r.json()["recent"] is None and r.json()["timeline"] is None
    assert c.get("/api/reliability", params={"route": "Red'; drop table x;--", "stop": "place-harsq", "direction": 1}).status_code == 422
    assert c.get("/api/reliability", params={"route": "Red", "stop": "place-harsq", "direction": 2}).status_code == 422


def test_last_train_leg_carries_its_station_id():
    t = datetime(2026, 11, 21, 23, 0, tzinfo=timezone.utc)
    legs = (t, t + timedelta(minutes=10))
    plan = m.round_trip_plan("Red", "Park Street", "Harvard", legs, legs, legs, True, False, t, (5, 5), station_id="place-harsq", return_direction=1)
    last = plan["last_return"]
    assert (last["from_stop_id"], last["direction_id"], last["route"]) == ("place-harsq", 1, "Red")


def test_a_failure_skips_tiger_for_a_minute(monkeypatch):
    monkeypatch.setenv("TIGER_DATABASE_URL", "postgres://unused")
    monkeypatch.setattr(rel, "asyncpg", object())  # configured() only checks the driver is importable
    calls = []
    async def broken():
        calls.append(1)
        raise OSError("down")
    monkeypatch.setattr(rel, "_db", broken)
    monkeypatch.setattr(rel, "_down_until", 0.0)
    assert asyncio.run(rel.recent([("Red", "place-harsq", 1)])) == {}
    assert asyncio.run(rel.recent([("Red", "place-harsq", 1)])) == {}  # skipped, no second connection attempt
    assert calls == [1] and rel.status() == {"status": "unavailable"}
