from fastapi.testclient import TestClient

import app.main as m

BODY = {"time": "2099-01-01T00:00:00Z", "budget": "$$", "lat": 42.355, "lng": -71.062, "max_walk_min": 20}  # rejected (422) before any upstream call


def client():
    m._HITS.clear()
    return TestClient(m.app)


def test_per_visitor_limit_returns_429_with_retry_after():
    c = client()
    codes = [c.post("/api/query", json=BODY, headers={"x-forwarded-for": "1.2.3.4"}).status_code for _ in range(31)]
    assert codes[:30] == [422] * 30 and codes[30] == 429
    r = c.post("/api/query", json=BODY, headers={"x-forwarded-for": "1.2.3.4"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert r.json()["error"]["code"] == "rate_limited" and r.json()["sources_used"] == []
    assert c.post("/api/query", json=BODY, headers={"x-forwarded-for": "5.6.7.8"}).status_code == 422  # other visitors unaffected


def test_site_wide_cap_holds_even_with_spoofed_addresses():
    c = client()
    codes = [c.post("/api/query", json=BODY, headers={"x-forwarded-for": f"10.0.0.{i}"}).status_code for i in range(121)]
    assert codes.count(429) == 1 and codes[-1] == 429


def test_window_slides(monkeypatch):
    c = client()
    t = [1000.0]
    monkeypatch.setattr(m.clock, "time", lambda: t[0])
    for _ in range(30):
        c.post("/api/query", json=BODY, headers={"x-forwarded-for": "9.9.9.9"})
    assert c.post("/api/query", json=BODY, headers={"x-forwarded-for": "9.9.9.9"}).status_code == 429
    t[0] += 61
    assert c.post("/api/query", json=BODY, headers={"x-forwarded-for": "9.9.9.9"}).status_code == 422


def test_unlimited_paths_and_health_are_untouched():
    c = client()
    assert all(c.get("/api/health").status_code == 200 for _ in range(50))
