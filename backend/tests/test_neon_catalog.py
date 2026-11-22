import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import app.main as m
import app.neon as neon


def query():
    return m.QueryInput.model_construct(time=datetime(2026, 11, 22, 0, tzinfo=timezone.utc),
        budget="$$", lat=42.355, lng=-71.062, max_walk_min=20, travel="walk")


def test_catalog_adapter_reads_parameterized_nearby_rows(monkeypatch):
    pool = type("Pool", (), {"fetch": AsyncMock(return_value=[{
        "external_id": "node/123", "name": "Neon Cafe", "lat": 42.355, "lng": -71.062,
        "categories": '["cafe"]', "details": json.dumps({"opening_hours": "24/7", "cuisine": None})}])})()
    monkeypatch.setattr(neon, "configured", lambda: True)
    monkeypatch.setattr(neon, "_pool", pool)
    rows = asyncio.run(neon.catalog_places(42.355, -71.062))
    venues = m.normalize_osm_candidates(query(), rows)
    assert venues[0]["name"] == "Neon Cafe"
    assert venues[0]["source_refs"][0]["external_id"] == "node/123"
    assert venues[0]["rating"] is None
    assert len(pool.fetch.call_args.args) == 8


def test_database_failure_returns_unavailable(monkeypatch):
    pool = type("Pool", (), {"fetch": AsyncMock(side_effect=RuntimeError("secret connection URL"))})()
    monkeypatch.setattr(neon, "configured", lambda: True)
    monkeypatch.setattr(neon, "_pool", pool)
    assert asyncio.run(neon.catalog_places(42.355, -71.062)) is None
    assert neon.status()["catalog"] == {"status": "unavailable"}


def test_query_returns_neon_places_without_google(monkeypatch):
    monkeypatch.setattr(m, "DEMO", False)
    monkeypatch.setattr(m, "catalog_places", AsyncMock(return_value=[{
        "osm": "node/123", "name": "Neon Cafe", "lat": 42.355, "lng": -71.062,
        "amenity": "cafe", "opening_hours": "24/7"}]))
    google = AsyncMock(side_effect=AssertionError("Google should not run"))
    monkeypatch.setattr(m, "live_candidates", google)
    monkeypatch.setattr(m, "routed_walk_minutes", AsyncMock(return_value=[]))
    monkeypatch.setattr(m, "forecast_for_query", AsyncMock(return_value={}))
    monkeypatch.setattr(m, "boston_home_games", AsyncMock(return_value=None))
    monkeypatch.setattr(m, "persist_recommendation_run", AsyncMock(return_value={"status": "disabled"}))
    result = asyncio.run(m.make_query(query()))
    assert result["recommendations"][0]["venue"]["name"] == "Neon Cafe"
    google.assert_not_called()


def test_unavailable_catalog_uses_existing_sources(monkeypatch):
    monkeypatch.setattr(m, "DEMO", False)
    monkeypatch.setattr(m, "catalog_places", AsyncMock(return_value=None))
    google = AsyncMock(return_value=([], False))
    monkeypatch.setattr(m, "live_candidates", google)
    monkeypatch.setattr(m, "osm_candidates", lambda *args: [])
    monkeypatch.setattr(m, "routed_walk_minutes", AsyncMock(return_value=[]))
    monkeypatch.setattr(m, "forecast_for_query", AsyncMock(return_value={}))
    monkeypatch.setattr(m, "boston_home_games", AsyncMock(return_value=None))
    monkeypatch.setattr(m, "persist_recommendation_run", AsyncMock(return_value={"status": "disabled"}))
    assert asyncio.run(m.make_query(query()))["recommendations"] == []
    google.assert_awaited_once()


def test_a_category_search_asks_google_for_that_category(monkeypatch):
    monkeypatch.setattr(m, "DEMO", False)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    calls = []
    async def fake_request(source, url, params, **kw):
        calls.append((url, kw["json_body"]))
        return {"places": []}
    monkeypatch.setattr(m, "request_json", fake_request)
    asyncio.run(m.live_candidates(query(), "noodles"))
    asyncio.run(m.live_candidates(query(), None))
    assert calls[0][0].endswith(":searchText") and calls[0][1]["textQuery"] == "ramen noodles"
    assert calls[0][1]["pageSize"] == 20 and calls[0][1]["locationBias"]["circle"]["radius"] == 5000.0
    assert calls[1][0].endswith(":searchNearby")  # no category: broad nearby search, as before
