import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import app.main as m

BOSTON = ZoneInfo("America/New_York")


def query(hour: int, minute: int = 0, limit: int = 30, **extra) -> m.QueryInput:
    when = datetime(2026, 11, 21, hour, minute, tzinfo=BOSTON)
    # Validate with a time that passes the next-24h check, then swap in the fixed date so tests run on any day
    q = m.QueryInput(time=datetime.now(BOSTON) + timedelta(hours=1), budget="$$", lat=42.355, lng=-71.062, max_walk_min=limit, **extra)
    return q.model_copy(update={"time": when})


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
    assert plan["total_min"] == 3 + 3 + 14 + 6  # walk to Park Street, wait, ride, walk to Eventide
    assert m.transit_summary(plan) == "Green Line D, Park Street to Fenway, 26 min door to door; last train back 12:41 AM"


def test_demo_trip_is_unavailable_after_the_last_train(monkeypatch):
    monkeypatch.setattr(m, "DEMO", True)
    plan = asyncio.run(m.assess_mbta_round_trip(query(23, 50), {"id": "demo-eventide"}, []))
    assert not plan["reachable"]


def demo_results(monkeypatch, q):
    monkeypatch.setattr(m, "DEMO", True)
    async def no_gemini(text):
        return {}
    monkeypatch.setattr(m, "parse_query_text", no_gemini)
    return {r["venue"]["id"]: r for r in asyncio.run(m.make_query(q))["recommendations"]}


def test_far_demo_venues_come_back_by_t_and_closed_ones_do_not(monkeypatch):
    by_id = demo_results(monkeypatch, query(19))
    assert {"demo-pinocchios", "demo-eventide", "demo-earls"} <= set(by_id)  # 46-72 min on foot, 22-26 min by T
    assert by_id["demo-pinocchios"]["reachability"]["outbound"]["line"]["name"] == "Red Line"
    assert "door to door by T" in by_id["demo-earls"]["explanation"]
    assert "demo-restaurant" not in by_id  # closed fixture stays filtered


def _schedule(trip: str, at: datetime) -> dict:
    return {"relationships": {"trip": {"data": {"id": trip}}},
            "attributes": {"departure_time": at.isoformat(), "arrival_time": at.isoformat()}}


def test_live_plan_prefers_subway_over_bus_and_never_uses_next_morning_trains(monkeypatch):
    monkeypatch.setattr(m, "DEMO", False)
    origin = [{"id": "place-pktrm", "name": "Park Street", "distance_m": 160, "lat": 42.3564, "lng": -71.0624}]  # ~3 min walk
    venue_stop = [{"id": "place-harsq", "name": "Harvard", "distance_m": 390, "lat": 42.3734, "lng": -71.1189}]
    async def stops(lat, lng, radius_m=1200): return venue_stop
    async def routes(stop_id): return {"Red", "1"}
    async def alerts(stop_id, route_id, at): return []
    async def predictions(stop_id, route_id, direction): return set()
    tried = []
    q = query(21)
    async def schedules(stop_id, route_id, direction, start, end):
        tried.append(route_id)
        assert end <= m.mbta_service_end(q.time)  # the return search stops at the end of the service day
        rows = []
        if start == q.time.astimezone(timezone.utc) and direction == 0:  # outbound
            for trip, wait in (("out0", 1), ("out1", 5)):  # out0 leaves before you can walk to Park Street
                base = start + timedelta(minutes=wait)
                rows.append(_schedule(trip, base if stop_id == "place-pktrm" else base + timedelta(minutes=13)))
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
    assert m.local_clock(plan["outbound"]["depart_at"]) == "9:05 PM"  # the 9:01 train is uncatchable
    walk_from = m.walk_estimate_minutes(42.3734, -71.1189, 42.37, -71.12)
    assert plan["walk_to_stop_min"] == m.walk_estimate_minutes(42.355, -71.062, 42.3564, -71.0624)
    assert plan["total_min"] == 5 + 13 + walk_from


def test_trip_limit_counts_door_to_door_time(monkeypatch):
    by_id = demo_results(monkeypatch, query(19, limit=25))
    assert "demo-pinocchios" in by_id and "demo-earls" in by_id  # 22 and 23 min
    assert "demo-eventide" not in by_id  # 26 min door to door


def test_walk_only_ignores_the_t(monkeypatch):
    by_id = demo_results(monkeypatch, query(19, travel="walk"))
    assert not {"demo-pinocchios", "demo-eventide", "demo-earls"} & set(by_id)
    assert all(r["reachability"]["method"] == "walking_fallback" for r in by_id.values())


def test_the_faster_way_wins():
    plan = {"reachable": True, "reach_value": 0.5, "method": "scheduled_round_trip", "total_min": 18, "outbound": {"route": "Red"}}
    assert m.reach_for(25, 30, plan)["method"] == "scheduled_round_trip"  # 18 min by T beats a 25 min walk
    walked = m.reach_for(12, 30, plan)
    assert walked["method"] == "walking_fallback" and walked["outbound"] is None and walked["total_min"] == 12
    assert m.reach_for(40, 15, plan) is None  # neither fits 15 min
    assert m.reach_for(40, 30, plan, "walk") is None  # walk-only ignores the T


def test_nearby_stops_are_found_locally_without_sending_coordinates(monkeypatch):
    import asyncio
    import app.main as m
    calls = []
    async def fake_request_json(source, url, params=None, **kw):
        calls.append((url, params))
        return {"data": [
            {"id": "place-dwnxg", "attributes": {"name": "Downtown Crossing", "latitude": 42.3555, "longitude": -71.0605, "location_type": 1}},
            {"id": "70020", "attributes": {"name": "Downtown Crossing", "latitude": 42.3554, "longitude": -71.0604, "location_type": 0}},
            {"id": "far", "attributes": {"name": "Quincy", "latitude": 42.25, "longitude": -71.0, "location_type": 1}},
            {"id": "nogps", "attributes": {"name": "No GPS", "latitude": None, "longitude": None, "location_type": 0}}]}
    monkeypatch.setattr(m, "request_json", fake_request_json)
    m._MBTA_STOPS.clear()
    first = asyncio.run(m.mbta_nearby_stops(42.355, -71.062))
    second = asyncio.run(m.mbta_nearby_stops(42.356, -71.061))
    assert [s["id"] for s in first] == ["place-dwnxg", "70020"] and second
    assert len(calls) == 1  # the stop list is fetched once and reused
    assert not any(k.startswith("filter[latitude]") or k.startswith("filter[longitude]") for k in calls[0][1])
    m._MBTA_STOPS.clear()


def test_failed_stop_list_fetch_backs_off(monkeypatch):
    import asyncio
    import app.main as m
    calls = []
    async def failing(*a, **kw):
        calls.append(1)
        return None
    monkeypatch.setattr(m, "request_json", failing)
    m._MBTA_STOPS.clear()
    async def burst():
        return await asyncio.gather(*(m.mbta_nearby_stops(42.355, -71.062) for _ in range(5)))
    assert asyncio.run(burst()) == [[]] * 5
    assert asyncio.run(m.mbta_nearby_stops(42.355, -71.062)) == []
    assert len(calls) == 1  # one fetch for the burst (lock), then backoff instead of refetching
    m._MBTA_STOPS.clear()


def test_one_transfer_when_no_single_line_works(monkeypatch):
    import asyncio
    from datetime import datetime, timedelta, timezone
    import app.main as m
    t0 = datetime(2026, 11, 22, 0, 0, tzinfo=timezone.utc)  # 7 pm Boston
    def sched(trip, stop, minutes, kind):
        when = (t0 + timedelta(minutes=minutes)).isoformat()
        return {"relationships": {"trip": {"data": {"id": trip}}}, "attributes": {"departure_time": when, "arrival_time": when}}
    # Orange: Jackson Sq -> DTX (trip O1, +10 -> +25); Red: DTX -> Harvard (R1, +30 -> +45). Returns 2 h later, reversed.
    table = {("jsq", "Orange", 0): [sched("O1", "jsq", 10, "d")], ("place-dwnxg", "Orange", 0): [sched("O1", "dtx", 25, "a")],
             ("place-dwnxg", "Red", 0): [sched("R1", "dtx", 30, "d")], ("hvd", "Red", 0): [sched("R1", "hvd", 45, "a")],
             ("hvd", "Red", 1): [sched("R2", "hvd", 120, "d")], ("place-dwnxg", "Red", 1): [sched("R2", "dtx", 135, "a")],
             ("place-dwnxg", "Orange", 1): [sched("O2", "dtx", 140, "d")], ("jsq", "Orange", 1): [sched("O2", "jsq", 155, "a")]}
    async def schedules(stop, route, direction, start, end):
        return [x for x in table.get((stop, route, direction), [])
                if start <= datetime.fromisoformat(x["attributes"]["departure_time"]) <= end]
    async def routes_at(stop):
        return {"place-dwnxg": {"Red", "Orange"}}.get(stop, set())
    async def no_alerts(*a): return []
    async def no_predictions(*a): return set()
    monkeypatch.setattr(m, "mbta_schedules", schedules)
    monkeypatch.setattr(m, "mbta_routes_at", routes_at)
    monkeypatch.setattr(m, "mbta_route_alerts", no_alerts)
    monkeypatch.setattr(m, "mbta_predictions", no_predictions)
    q = m.QueryInput.model_construct(time=t0, budget="$$", lat=42.3231, lng=-71.0999, max_walk_min=60, travel="walk_t")
    origin = [{"id": "jsq", "name": "Jackson Square", "lat": 42.3231, "lng": -71.0999, "distance_m": 50}]
    venue = [{"id": "hvd", "name": "Harvard", "lat": 42.3734, "lng": -71.1189, "distance_m": 80}]
    plan = asyncio.run(m.transfer_round_trip(q, {"id": "v", "lat": 42.3734, "lng": -71.1189}, origin, venue,
                                             {"jsq": {"Orange"}, "hvd": {"Red"}}, t0, t0 + timedelta(hours=1), t0 + timedelta(hours=5), False))
    assert plan and plan["method"] == "scheduled_round_trip"
    assert plan["outbound"]["transfer"]["at"] == "Downtown Crossing" and plan["outbound"]["transfer"]["line"]["name"] == "Red Line"
    assert plan["outbound"]["line"]["name"] == "Orange Line" and plan["total_min"] >= 45
    assert plan["return"]["transfer"]["line"]["name"] == "Orange Line"
    assert plan["last_return"] is None  # never show the first return as the "latest train back"
    # A missed connection (Red leaves before Orange arrives + 3 min) means no plan.
    table[("place-dwnxg", "Red", 0)] = [sched("R1", "dtx", 26, "d")]
    assert asyncio.run(m.transfer_round_trip(q, {"id": "v", "lat": 42.3734, "lng": -71.1189}, origin, venue,
                                             {"jsq": {"Orange"}, "hvd": {"Red"}}, t0, t0 + timedelta(hours=1), t0 + timedelta(hours=5), False)) is None


def test_an_alert_active_on_the_way_home_blocks_the_route(monkeypatch):
    import asyncio
    from datetime import datetime, timedelta, timezone
    import app.main as m
    t0 = datetime(2026, 11, 22, 0, 0, tzinfo=timezone.utc)
    async def alerts(stop_id, route_id, at):
        return [{"attributes": {"effect": "SUSPENSION"}}] if at >= t0 + timedelta(hours=1) else []
    monkeypatch.setattr(m, "mbta_route_alerts", alerts)
    assert asyncio.run(m.route_blocked("Red", ("a", "b"), t0)) is False
    assert asyncio.run(m.route_blocked("Red", ("a", "b"), t0 + timedelta(hours=2))) is True
