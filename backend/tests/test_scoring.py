import pytest

import app.main as m

VENUE = {"rating": 4.5, "review_count": 100, "indoor_outdoor": "indoor", "momentum_delta": 5}
WEATHER = {"temperature_f": 55, "precipitation_chance_pct": 0}
REACH = {"reach_value": 0.5}


def test_weights_come_from_yaml_and_sum_to_one():
    assert m.SCORING["weights"] == {"momentum": 0.30, "quality": 0.30, "reach": 0.20, "events": 0.10, "weather": 0.10}


def test_missing_components_drop_out_and_the_rest_rescale():
    live = {**VENUE, "momentum_meta": {"method": "unavailable", "label": None, "missing_reason": "no_velocity_data"}}
    s = m.score_venue(live, 4.0, WEATHER, REACH)  # momentum and events both missing
    c = s["components"]
    assert c["momentum"]["weight"] == 0 and c["events"]["weight"] == 0
    assert c["quality"]["weight"] == pytest.approx(0.5) and c["reach"]["weight"] == pytest.approx(1 / 3)
    assert sum(x["weight"] for x in c.values()) == pytest.approx(1.0)
    assert c["quality"]["base_weight"] == 0.30


def test_a_perfect_place_can_reach_one_even_with_missing_sources():
    perfect = {"rating": 5.0, "review_count": 10**9, "indoor_outdoor": "indoor",
               "momentum_meta": {"missing_reason": "no_velocity_data"}}
    s = m.score_venue(perfect, 5.0, {"temperature_f": 30, "precipitation_chance_pct": 90}, {"reach_value": 1.0})
    assert s["value"] == pytest.approx(1.0, abs=1e-3)


def test_all_data_present_uses_base_weights():
    s = m.score_venue({**VENUE, "nearby_events": 1}, 4.0, WEATHER, REACH)
    assert {k: c["weight"] for k, c in s["components"].items()} == pytest.approx(m.SCORING["weights"])


PLAN_SCHED = {"reachable": True, "reach_value": 0.5, "method": "scheduled_round_trip", "outbound": {"route": "Red"}}
PLAN_LIVE = {**PLAN_SCHED, "reach_value": 1.0, "method": "predicted_round_trip"}
NO_PLAN = {"reachable": False, "reach_value": 0.0, "method": "walking_fallback", "label": "No nearby MBTA stop pair"}


def test_beyond_walking_range_needs_transit():
    assert m.reach_for(40, 20, NO_PLAN) is None
    assert m.reach_for(40, 20, PLAN_SCHED)["method"] == "scheduled_round_trip"
    assert m.reach_for(None, 20, PLAN_LIVE)["reach_value"] == 1.0


def test_walkable_places_take_the_better_reach():
    assert m.reach_for(10, 20, NO_PLAN)["method"] == "walking_fallback"
    assert m.reach_for(10, 20, NO_PLAN)["reach_value"] == 0.5
    assert m.reach_for(10, 20, PLAN_LIVE)["reach_value"] == 1.0
