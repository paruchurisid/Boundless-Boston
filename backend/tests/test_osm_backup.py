import json
from datetime import datetime, timezone

import app.main as m

# 2026-11-21 is a Saturday; times are UTC (Boston = UTC-5).
SAT_7PM = datetime(2026, 11, 22, 0, 0, tzinfo=timezone.utc)
SAT_1AM_SUN = datetime(2026, 11, 22, 6, 0, tzinfo=timezone.utc)   # Sunday 1:00 am Boston
SUN_NOON = datetime(2026, 11, 22, 17, 0, tzinfo=timezone.utc)


def test_simple_and_overriding_rules():
    assert m.osm_open_at("Mo-Su 11:00-22:00", SAT_7PM) == "open"
    assert m.osm_open_at("Mo-Fr 11:00-22:00; Sa off", SAT_7PM) == "closed"
    assert m.osm_open_at("Mo-Su 11:00-22:00; Su off", SUN_NOON) == "closed"  # later rule replaces Sunday
    assert m.osm_open_at("24/7", SAT_1AM_SUN) == "open"


def test_wrapping_days_and_after_midnight_hours():
    assert m.osm_open_at("Su-Th 11:00-22:00; Fr,Sa 11:00-02:00", SAT_1AM_SUN) == "open"   # Saturday's hours run into Sunday
    assert m.osm_open_at("Su-Th 11:00-22:00; Fr,Sa 11:00-23:00", SAT_1AM_SUN) == "closed"
    assert m.osm_open_at("Mo-Su 07:00-24:00", SAT_7PM) == "open"
    assert m.osm_open_at("Mo-Sa 11:00-15:00,17:00-21:00", SAT_7PM) == "open"


def test_unsupported_or_missing_hours_are_unknown():
    for spec in (None, "", "Mo-Fr 09:00-17:00; PH off", "Jan-Mar Mo-Fr 10:00-16:00", '"call ahead"', "sunrise-sunset"):
        assert m.osm_open_at(spec, SAT_7PM) == "unknown"


def test_snapshot_candidates_are_nearest_labeled_and_routable(tmp_path, monkeypatch):
    snap = {"generated_at": "2026-11-21T19:00:00+00:00", "venues": [
        {"osm": "node/1", "lat": 42.3551, "lng": -71.0621, "name": "Near Cafe", "amenity": "cafe", "opening_hours": "Mo-Su 07:00-23:00"},
        {"osm": "way/2", "lat": 42.3540, "lng": -71.0700, "name": "Common", "leisure": "park"},
        {"osm": "node/3", "lat": 42.50, "lng": -71.20, "name": "Too Far", "amenity": "bar"}]}
    path = tmp_path / "osm.json"
    path.write_text(json.dumps(snap))
    monkeypatch.setattr(m, "OSM_SNAPSHOT", path)
    q = m.QueryInput.model_construct(time=SAT_7PM, budget="$$", lat=42.355, lng=-71.062, max_walk_min=20)
    venues = m.osm_candidates(q)
    assert [v["name"] for v in venues] == ["Near Cafe", "Common"]
    cafe, park = venues
    assert cafe["open_hours"]["status_at_requested_time"] == "open" and park["open_hours"]["status_at_requested_time"] == "unknown"
    assert cafe["price_level"] is None and park["indoor_outdoor"] == "outdoor"
    assert m.routable(cafe)  # OSM venues may use real walking routes
    assert m.HEALTH["overpass"]["status"] == "cached"


def test_missing_snapshot_disables_the_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "OSM_SNAPSHOT", tmp_path / "missing.json")
    q = m.QueryInput.model_construct(time=SAT_7PM, budget="$$", lat=42.355, lng=-71.062, max_walk_min=20)
    assert m.osm_candidates(q) == [] and m.HEALTH["overpass"]["status"] == "disabled"
