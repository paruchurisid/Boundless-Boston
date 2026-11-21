import asyncio

import app.main as m

VENUES = [{"lat": 42.3587, "lng": -71.0711}, {"lat": 42.3654, "lng": -71.0568}, {"lat": 42.36, "lng": -71.05}]


def route(monkeypatch, response):
    calls = []
    async def fake_request_json(source, url, params=None, headers=None, method="GET", json_body=None, timeout=4.0):
        calls.append(json_body)
        return response
    monkeypatch.setattr(m, "DEMO", False)
    monkeypatch.setenv("ORS_API_KEY", "test-key")
    monkeypatch.setattr(m, "request_json", fake_request_json)
    return asyncio.run(m.routed_walk_minutes(42.35512, -71.06234, VENUES)), calls


def test_converts_seconds_to_whole_minutes_and_keeps_unroutable_as_none(monkeypatch):
    minutes, calls = route(monkeypatch, {"durations": [[761.2, 59.0, None]]})
    assert minutes == [13, 1, None]
    body = calls[0]
    assert body["locations"][0] == [-71.0623, 42.3551]  # [lng, lat]
    assert body["locations"][1] == [-71.0711, 42.3587] and body["sources"] == [0] and body["destinations"] == [1, 2, 3]


def test_unavailable_or_malformed_returns_none(monkeypatch):
    assert route(monkeypatch, None)[0] is None
    assert route(monkeypatch, {"durations": [[60.0]]})[0] is None  # length mismatch
    assert route(monkeypatch, {"error": "quota"})[0] is None


def test_no_key_or_no_venues_skips_the_call(monkeypatch):
    monkeypatch.setattr(m, "DEMO", False)
    monkeypatch.delenv("ORS_API_KEY", raising=False)
    assert asyncio.run(m.routed_walk_minutes(42.0, -71.0, VENUES)) is None
    assert asyncio.run(m.routed_walk_minutes(42.0, -71.0, [])) is None


def test_only_known_non_google_venues_are_routable():
    assert not m.routable({"source_refs": [{"source": "google_places", "external_id": "x"}]})
    assert not m.routable({"source_refs": [{"source": "overpass"}, {"source": "google_places"}]})  # merged duplicate
    assert not m.routable({}) and not m.routable({"source_refs": None}) and not m.routable({"source_refs": []})
    assert m.routable({"source_refs": [{"source": "overpass", "external_id": "node/1"}]})


def test_upstream_reason_names_the_google_quota_without_secrets():
    import httpx
    body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded for consumer 'projects/123'",
                      "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "RATE_LIMIT_EXCEEDED",
                                   "metadata": {"quota_metric": "places.googleapis.com/search_nearby_requests",
                                                "quota_limit": "SearchNearbyRequestsPerDay", "consumer": "projects/123"}}]}}
    reason = m.upstream_reason(httpx.Response(429, json=body))
    assert reason == "RESOURCE_EXHAUSTED RATE_LIMIT_EXCEEDED places.googleapis.com/search_nearby_requests SearchNearbyRequestsPerDay"
    assert "projects/123" not in reason
    assert m.upstream_reason(httpx.Response(503, text="<html>oops</html>")) == ""
