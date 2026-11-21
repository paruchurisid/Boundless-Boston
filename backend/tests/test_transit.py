import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import app.main as m

BOSTON = ZoneInfo("America/New_York")


def query(hour: int, minute: int = 0, **extra) -> m.QueryInput:
    when = datetime(2026, 11, 21, hour, minute, tzinfo=BOSTON)
    return m.QueryInput(time=when, budget="$$", lat=42.355, lng=-71.062, max_walk_min=20, **extra)


def test_boston_line_names_and_colors():
    assert m.mbta_line("Green-D") == {"id": "Green-D", "name": "Green Line D", "color": "#00843D", "mode": "subway"}
    assert m.mbta_line("Red")["name"] == "Red Line"
    assert m.mbta_line("741")["name"] == "Silver Line SL1"
    assert m.mbta_line("39") == {"id": "39", "name": "Bus 39", "color": "#FFC72C", "mode": "bus"}
    assert m.mbta_line("CR-Fitchburg")["name"] == "Fitchburg Line (Commuter Rail)"


def test_service_day_ends_at_3am_including_after_midnight():
    assert m.mbta_service_end(datetime(2026, 11, 21, 20, 0, tzinfo=BOSTON)) == datetime(2026, 11, 22, 3, 0, tzinfo=BOSTON)
    assert m.mbta_service_end(datetime(2026, 11, 22, 1, 30, tzinfo=BOSTON)) == datetime(2026, 11, 22, 3, 0, tzinfo=BOSTON)


def test_demo_trip_has_line_and_last_train(monkeypatch):
    monkeypatch.setattr(m, "DEMO", True)
    plan = asyncio.run(m.assess_mbta_round_trip(query(19), {"id": "demo-eventide"}, []))
    assert plan["reachable"] and plan["method"] == "scheduled_round_trip"
    assert plan["outbound"]["line"]["name"] == "Green Line D"
    assert plan["last_return"]["last_of_night"] is True
    assert datetime.fromisoformat(plan["last_return"]["depart_at"]).astimezone(BOSTON).strftime("%H:%M") == "00:41"
    assert m.transit_summary(plan) == "Green Line D, Park Street to Fenway; last train back 12:41 AM"


def test_demo_trip_is_unavailable_after_the_last_train(monkeypatch):
    monkeypatch.setattr(m, "DEMO", True)
    plan = asyncio.run(m.assess_mbta_round_trip(query(23, 50), {"id": "demo-eventide"}, []))
    assert not plan["reachable"]


def test_far_demo_venues_come_back_by_t_and_closed_ones_do_not(monkeypatch):
    monkeypatch.setattr(m, "DEMO", True)
    async def no_gemini(text):
        return {}
    monkeypatch.setattr(m, "parse_query_text", no_gemini)
    result = asyncio.run(m.make_query(query(19)))
    by_id = {r["venue"]["id"]: r for r in result["recommendations"]}
    assert {"demo-pinocchios", "demo-eventide", "demo-earls"} <= set(by_id)  # all beyond the 20 min walk limit
    assert by_id["demo-pinocchios"]["reachability"]["outbound"]["line"]["name"] == "Red Line"
    assert "take the T" in by_id["demo-earls"]["explanation"]
    assert "demo-restaurant" not in by_id  # closed fixture stays filtered


def _schedule(trip: str, at: datetime) -> dict:
    return {"relationships": {"trip": {"data": {"id": trip}}},
            "attributes": {"departure_time": at.isoformat(), "arrival_time": at.isoformat()}}


def test_live_plan_prefers_subway_over_bus_and_never_uses_next_morning_trains(monkeypatch):
    monkeypatch.setattr(m, "DEMO", False)
    origin = [{"id": "place-pktrm", "name": "Park Street", "distance_m": 300}]
    venue_stop = [{"id": "place-harsq", "name": "Harvard", "distance_m": 200}]
    async def stops(lat, lng, radius_m=1200): return venue_stop
    async def routes(stop_id): return {"Red", "1"}
    async def alerts(stop_id, route_id): return []
    async def predictions(stop_id, route_id, direction): return set()
    tried = []
    q = query(21)
    async def schedules(stop_id, route_id, direction, start, end):
        tried.append(route_id)
        assert end <= m.mbta_service_end(q.time)  # the return search stops at the end of the service day
        rows = []
        if start == q.time.astimezone(timezone.utc) and direction == 0:  # outbound
            base = start + timedelta(minutes=5)
            rows.append(_schedule("out1", base if stop_id == "place-pktrm" else base + timedelta(minutes=13)))
        if start > q.time and direction == 1:  # return trips, 23:30 and 00:47
            for trip, t in (("r1", datetime(2026, 11, 21, 23, 30, tzinfo=BOSTON)), ("r2", datetime(2026, 11, 22, 0, 47, tzinfo=BOSTON))):
                rows.append(_schedule(trip, t if stop_id == "place-harsq" else t + timedelta(minutes=13)))
        return rows
    for name, fn in (("mbta_nearby_stops", stops), ("mbta_routes_at", routes), ("mbta_route_alerts", alerts),
                     ("mbta_predictions", predictions), ("mbta_schedules", schedules)):
        monkeypatch.setattr(m, name, fn)
    plan = asyncio.run(m.assess_mbta_round_trip(q, {"id": "v", "lat": 42.37, "lng": -71.12}, origin))
    assert tried[0] == "Red"  # subway tried before Bus 1
    assert plan["line"]["name"] == "Red Line"
    assert plan["last_return"]["last_of_night"] is True
    assert m.local_clock(plan["last_return"]["depart_at"]) == "12:47 AM"
    assert m.local_clock(plan["return"]["depart_at"]) == "11:30 PM"
