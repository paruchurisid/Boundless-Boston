from datetime import datetime, timezone

from app.main import parse_event_points, score_venue

START = datetime(2026, 11, 22, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 11, 22, 3, 0, tzinfo=timezone.utc)


def event(when, lat="42.3662", lng="-71.0621"):
    venue = {"location": {"latitude": lat, "longitude": lng}} if lat else {}
    return {"dates": {"start": {"dateTime": when}}, "_embedded": {"venues": [venue]}}


def test_parse_keeps_only_events_in_window_with_coordinates():
    data = {"_embedded": {"events": [
        event("2026-11-22T01:00:00Z"),
        event("2026-11-22T03:00:00Z"),          # starts at window end: excluded
        event("2026-11-21T23:00:00Z"),          # before window
        event("2026-11-22T01:30:00Z", lat=None),  # no venue coordinates
        {"dates": {"start": {"localDate": "2026-11-22"}}},  # time TBA
    ]}}
    assert parse_event_points(data, START, END) == [(42.3662, -71.0621)]


def test_parse_handles_no_results():
    assert parse_event_points({}, START, END) == [] and parse_event_points(None, START, END) == []


VENUE = {"rating": 4.5, "review_count": 100, "indoor_outdoor": "indoor"}
WEATHER = {"temperature_f": 55, "precipitation_mm": 0}
REACH = {"reach_value": 0.5}


def test_events_score_saturates_at_three():
    for count, want in ((0, 0.0), (1, 1 / 3), (3, 1.0), (7, 1.0)):
        c = score_venue({**VENUE, "nearby_events": count}, 4.0, WEATHER, REACH)["components"]["events"]
        assert c["value"] == want and c["missing_reason"] is None and c["raw"]["nearby_events"] == count


def test_unknown_events_are_labeled_not_zero_events():
    c = score_venue({**VENUE, "nearby_events": None}, 4.0, WEATHER, REACH)["components"]["events"]
    assert c["value"] == 0.0 and c["missing_reason"] == "event data unavailable" and c["raw"]["nearby_events"] is None
