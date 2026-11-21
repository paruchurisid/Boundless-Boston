import asyncio
from datetime import datetime, timedelta, timezone

import app.main as m

MLB = {"dates": [{"games": [
    {"gameDate": "2026-09-22T22:45:00Z", "venue": {"name": "Fenway Park"}, "teams": {"away": {"team": {"name": "Cleveland Guardians"}}}},
    {"gameDate": "2026-09-22T23:10:00Z", "venue": {"name": "Fenway Park"}, "status": {"codedGameState": "D", "detailedState": "Postponed"}, "teams": {"away": {"team": {"name": "Yankees"}}}},
    {"gameDate": "2026-09-23T17:40:00Z", "venue": {"name": "Tropicana Field"}, "teams": {"away": {"team": {"name": "Boston Red Sox"}}}}]}]}
NHL = {"games": [
    {"startTimeUTC": "2026-11-22T00:00:00Z", "venue": {"default": "TD Garden"}, "awayTeam": {"commonName": {"default": "Capitals"}}, "gameScheduleState": "OK"},
    {"startTimeUTC": "2026-11-23T00:00:00Z", "venue": {"default": "Madison Square Garden"}, "awayTeam": {"commonName": {"default": "Bruins"}}},
    {"startTimeUTC": "2026-11-24T00:00:00Z", "venue": {"default": "TD Garden"}, "awayTeam": {"commonName": {"default": "Leafs"}}, "gameScheduleState": "PPD"}]}


def load(monkeypatch, mlb, nhl):
    async def fake(source, url, *a, **k):
        return mlb if "mlb" in url else nhl
    monkeypatch.setattr(m, "request_json", fake)
    m._SPORTS.clear()
    try:
        return asyncio.run(m.boston_home_games())
    finally:
        m._SPORTS.clear()


def test_only_boston_home_games_that_are_on(monkeypatch):
    games = load(monkeypatch, MLB, NHL)
    assert [(g["label"], g["venue"]) for g in games] == [("Red Sox vs Cleveland Guardians", "Fenway Park"), ("Bruins vs Capitals", "TD Garden")]


def test_one_feed_down_still_counts_the_other_and_both_down_is_unknown(monkeypatch):
    assert [g["venue"] for g in load(monkeypatch, None, NHL)] == ["TD Garden"]
    assert load(monkeypatch, None, None) is None


def test_window_is_three_hours_either_side():
    start = datetime(2026, 11, 22, 0, 0, tzinfo=timezone.utc)
    games = [{"start": start, "venue": "TD Garden", "label": "Bruins vs Capitals"}]
    for offset, expected in ((-3, 1), (0, 1), (2.5, 1), (3, 1), (3.5, 0), (-3.5, 0)):
        assert len(m.games_around(games, start + timedelta(hours=offset))) == expected
    assert m.games_around(None, start) is None


def test_half_mile_radius_reaches_north_end_not_back_bay():
    garden = m.SPORTS_VENUES["TD Garden"]
    assert m.haversine(42.3637, -71.0545, *garden) <= m.SCORING["events"]["radius_m"]  # Hanover St, North End
    assert m.haversine(42.3500, -71.0780, *garden) > m.SCORING["events"]["radius_m"]   # Back Bay


def test_backoff_after_failure_returns_unknown_without_crashing(monkeypatch):
    calls = []
    async def down(*a, **k):
        calls.append(1)
        return None
    monkeypatch.setattr(m, "request_json", down)
    m._SPORTS.clear()
    assert asyncio.run(m.boston_home_games()) is None and asyncio.run(m.boston_home_games()) is None
    assert len(calls) == 2  # one gather of MLB + NHL, then backoff
    m._SPORTS.clear()


def test_a_failed_feed_keeps_its_last_list_and_retries_soon(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(m.clock, "time", lambda: t[0])
    feeds = {"mlb": MLB, "nhl": NHL}
    async def fake(source, url, *a, **k):
        return feeds["mlb" if "mlb" in url else "nhl"]
    monkeypatch.setattr(m, "request_json", fake)
    m._SPORTS.clear()
    assert len(asyncio.run(m.boston_home_games())) == 2
    t[0] += 7 * 3600
    feeds["nhl"] = None  # NHL times out on the next refresh
    games = asyncio.run(m.boston_home_games())
    assert {g["label"] for g in games} == {"Red Sox vs Cleveland Guardians", "Bruins vs Capitals"}  # Bruins kept
    assert m._SPORTS["fresh_until"] == t[0] + 300  # retried in 5 min, not 6 h
    m._SPORTS.clear()


def test_unexpected_feed_shapes_count_as_down(monkeypatch):
    for bad in ([1, 2], {"games": [{"startTimeUTC": "not a date", "venue": {"default": "TD Garden"}}]}):
        assert [g["venue"] for g in load(monkeypatch, MLB, bad)] == ["Fenway Park"]
    assert load(monkeypatch, "oops", [1]) is None
