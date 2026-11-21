from datetime import datetime, timezone

from app.main import nws_period_at, score_venue

HOURLY = {"properties": {"periods": [
    {"startTime": "2026-11-21T19:00:00-05:00", "endTime": "2026-11-21T20:00:00-05:00", "temperature": 52, "temperatureUnit": "F",
     "probabilityOfPrecipitation": {"value": 10}},
    {"startTime": "2026-11-21T20:00:00-05:00", "endTime": "2026-11-21T21:00:00-05:00", "temperature": 10, "temperatureUnit": "C",
     "probabilityOfPrecipitation": {"value": None}},
]}}


def test_picks_the_period_covering_the_requested_time():
    got = nws_period_at(HOURLY, datetime(2026, 11, 22, 0, 30, tzinfo=timezone.utc))  # 7:30pm Boston
    assert got == {"temperature_f": 52.0, "precipitation_chance_pct": 10, "forecast_for": "2026-11-21T19:00:00-05:00", "source": "nws"}


def test_converts_celsius_and_keeps_unknown_chance():
    got = nws_period_at(HOURLY, datetime(2026, 11, 22, 1, 0, tzinfo=timezone.utc))
    assert got["temperature_f"] == 50.0 and got["precipitation_chance_pct"] is None


def test_outside_forecast_is_none():
    assert nws_period_at(HOURLY, datetime(2026, 11, 23, tzinfo=timezone.utc)) is None and nws_period_at(None, datetime.now(timezone.utc)) is None


def weather_value(io, weather):
    v = {"rating": 4.5, "review_count": 100, "indoor_outdoor": io}
    return score_venue(v, 4.0, weather, {"reach_value": 0.5})["components"]["weather"]["value"]


def test_rain_chance_of_50_or_more_favors_indoor():
    rainy, dry = {"temperature_f": 55, "precipitation_chance_pct": 50}, {"temperature_f": 55, "precipitation_chance_pct": 49}
    assert (weather_value("indoor", rainy), weather_value("outdoor", rainy)) == (1.0, 0.0)
    assert (weather_value("indoor", dry), weather_value("outdoor", dry)) == (0.5, 0.5)
