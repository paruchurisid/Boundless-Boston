from datetime import datetime

from app.main import opening_at

# Places API (New) shape: dates are {"year","month","day"} objects; this bar closes after midnight.
HOURS = {"periods": [{"open": {"day": 6, "hour": 11, "minute": 0, "date": {"year": 2026, "month": 11, "day": 21}},
                      "close": {"day": 0, "hour": 1, "minute": 0, "date": {"year": 2026, "month": 11, "day": 22}}}]}


def at(iso: str) -> str:
    return opening_at(HOURS, datetime.fromisoformat(iso), "America/New_York")


def test_open_in_evening():
    assert at("2026-11-22T00:00:00+00:00") == "open"  # 7pm Boston


def test_closed_before_opening():
    assert at("2026-11-21T15:00:00+00:00") == "closed"  # 10am


def test_open_past_midnight_until_close():
    assert at("2026-11-22T05:30:00+00:00") == "open"  # 12:30am
    assert at("2026-11-22T06:30:00+00:00") == "closed"  # 1:30am
