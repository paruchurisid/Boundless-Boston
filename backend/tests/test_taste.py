import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.tiktok import (
    extract_place_mentions_from_videos,
    extract_tags_from_videos,
    match_place_mentions_to_venues,
    normalize_tag_token,
)


def test_normalize_tag_token_maps_keywords():
    assert normalize_tag_token("Ramen") == "noodles"
    assert normalize_tag_token("coffee") == "cafe"
    assert normalize_tag_token("seafood") == "seafood"
    assert normalize_tag_token("sushi") == "sushi"
    assert normalize_tag_token("bostonseafood") == "seafood"
    assert normalize_tag_token("italianfood") == "italian"
    assert normalize_tag_token("barbara") is None  # do not substring-match "bar"
    assert normalize_tag_token("club") is None  # bare club is too noisy
    assert normalize_tag_token("nightclub") == "night_club"
    assert normalize_tag_token("xyzzy") is None


def test_normalize_place_categories_prefers_cuisine():
    cats = m.normalize_place_categories(
        ["restaurant", "food", "point_of_interest", "establishment", "seafood_restaurant"],
        primary_type="seafood_restaurant",
    )
    assert cats[0] == "seafood"
    assert "restaurant" in cats
    assert "food" not in cats
    assert "point_of_interest" not in cats
    assert m.normalize_place_categories(["italian_restaurant", "restaurant"])[0] == "italian"
    assert m.matches_category({"categories": ["seafood", "restaurant"]}, "restaurant")
    assert m.matches_category({"categories": ["seafood"]}, "seafood")
    assert m.matches_category({"categories": ["seafood"]}, "restaurant")
    assert not m.matches_category({"categories": ["park"]}, "restaurant")


def test_extract_tags_from_videos():
    tags = extract_tags_from_videos(
        [
            {"title": "Best ramen in Boston #noodles", "video_description": "late night noodles"},
            {"title": "Cozy cafe morning", "video_description": "#coffee"},
            {"title": "Live music at a bar", "video_description": ""},
            {"title": "Dinner at an Italian spot", "video_description": "#bostonitalianfood lobster roll"},
            {"title": "Join our club tonight", "video_description": "school club meeting"},
        ]
    )
    names = [t["tag"] for t in tags]
    assert "noodles" in names
    assert "cafe" in names
    assert "bar" in names
    assert "italian" in names
    assert "seafood" in names
    assert "restaurant" not in names  # cuisine signals suppress bare restaurant
    assert "night_club" not in names  # bare "club" no longer counts


def test_extract_and_match_place_mentions():
    mentions = extract_place_mentions_from_videos(
        [
            {"title": "Dinner at Democracy Brewing", "video_description": "#boston"},
            {"title": 'Late night at "jm Curley"', "video_description": ""},
            {"title": "back to your school", "video_description": "Join Sightshare Club today"},
            {"title": "your highschool memories", "video_description": "Follow for more"},
        ]
    )
    names = [m["name"] for m in mentions]
    assert any("Democracy" in n for n in names)
    assert any("Curley" in n for n in names)
    joined = " | ".join(names).lower()
    assert "your school" not in joined
    assert "highschool" not in joined
    assert "sightshare" not in joined
    assert "join" not in joined
    matched = match_place_mentions_to_venues(
        mentions,
        [{"id": "1", "name": "Democracy Brewing", "address": "35 Temple Place", "categories": ["bar"]}],
    )
    hit = next(m for m in matched if "Democracy" in m["name"])
    assert hit["matched_venue"]["id"] == "1"
    assert "guessed" in hit["label"]


def test_taste_score_jaccard_and_missing():
    missing = m.taste_score(["cafe"], [])
    assert missing["missing_reason"] == "no_preference_data"
    hit = m.taste_score(["cafe", "bakery"], ["cafe", "noodles"])
    assert hit["missing_reason"] is None
    assert hit["value"] == pytest.approx(1 / 3)  # intersection cafe; union cafe,bakery,noodles
    assert "cafe" in hit["raw"]["intersection"]


def test_score_venue_includes_taste_and_rescales_when_missing():
    venue = {
        "rating": 4.5,
        "review_count": 100,
        "indoor_outdoor": "indoor",
        "momentum_delta": 5,
        "categories": ["cafe", "bakery"],
        "nearby_events": 1,
    }
    weather = {"temperature_f": 55, "precipitation_chance_pct": 0}
    reach = {"reach_value": 0.5}

    without = m.score_venue(venue, 4.0, weather, reach, [])
    assert without["components"]["taste"]["weight"] == 0
    assert without["components"]["taste"]["missing_reason"] == "no_preference_data"
    assert sum(c["weight"] for c in without["components"].values()) == pytest.approx(1.0)

    with_tags = m.score_venue(venue, 4.0, weather, reach, ["cafe"])
    assert with_tags["components"]["taste"]["weight"] == pytest.approx(m.SCORING["weights"]["taste"])
    assert with_tags["components"]["taste"]["value"] > 0


def test_preferences_demo_endpoint():
    client = TestClient(m.app)
    res = client.post("/api/tiktok/demo")
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "demo"
    assert "noodles" in body["preference_tags"]
    assert body["place_mentions"]
    assert body["place_mentions"][0]["name"]


def test_preferences_live_session_stays_connected_without_tags(monkeypatch, tmp_path):
    """OAuth session with an empty/unmappable feed stays live and still shows taste chips."""
    import app.tiktok as tiktok

    monkeypatch.setenv("APP_MODE", "live")
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "test-key")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(tiktok, "SESSION_DB", tmp_path / "tiktok-sessions.sqlite3")
    tiktok.init_session_db()
    tiktok._set_session("sess-1", "access-token", None, "open-1", 3600)

    async def _no_videos(_token: str):
        return []

    monkeypatch.setattr(tiktok, "_fetch_videos", _no_videos)
    client = TestClient(m.app)
    res = client.get("/api/tiktok/preferences", cookies={tiktok.SESSION_COOKIE: "sess-1"})
    assert res.status_code == 200
    body = res.json()
    assert body["connected"] is True
    assert body["mode"] == "live"
    assert body["preference_tags"] == ["night_club", "mexican", "seafood"]
    assert body["place_mentions"]
    assert m.HEALTH["tiktok"]["status"] == "live"


def test_query_accepts_preference_tags():
    m._HITS.clear()  # earlier rate-limit tests can leave the sliding window full
    client = TestClient(m.app)
    from datetime import datetime, timedelta, timezone

    when = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    res = client.post(
        "/api/query",
        json={
            "time": when,
            "budget": "$$",
            "lat": 42.355,
            "lng": -71.062,
            "max_walk_min": 25,
            "preference_tags": ["cafe", "noodles"],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["query"]["preference_tags"] == ["cafe", "noodles"]
    assert body["recommendations"]
    taste = body["recommendations"][0]["score"]["components"]["taste"]
    assert taste["missing_reason"] is None
    assert "tiktok" in [s["source"] for s in body["sources_used"]]
