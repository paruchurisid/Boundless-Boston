import asyncio

import app.main as m


def test_valid_filters_keeps_only_in_bounds_values():
    raw = {"budget": "$", "max_walk_min": 15, "category": "noodles"}
    assert m.valid_filters(raw) == raw
    assert m.valid_filters({"budget": "$$$$", "max_walk_min": 500, "category": "casino"}) == {}
    assert m.valid_filters({"max_walk_min": True, "budget": None}) == {}
    assert m.valid_filters("not a dict") == {} and m.valid_filters(None) == {}


def run(text, monkeypatch, response):
    async def fake_request_json(*args, **kwargs):
        return response
    monkeypatch.setattr(m, "DEMO", False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(m, "request_json", fake_request_json)
    return asyncio.run(m.parse_query_text(text))


def test_uses_gemini_output_when_valid(monkeypatch):
    reply = {"candidates": [{"content": {"parts": [{"text": '{"budget": "$", "max_walk_min": 15, "category": "bar"}'}]}}]}
    assert run("cheap dive bar within 15 min", monkeypatch, reply) == {"budget": "$", "max_walk_min": 15, "category": "bar", "parser": "gemini"}


def test_falls_back_to_rules_when_gemini_fails(monkeypatch):
    assert run("cheap ramen under 15 min", monkeypatch, None) == {"budget": "$", "max_walk_min": 15, "category": "noodles", "parser": "rules"}
    garbled = {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}
    assert run("pizza", monkeypatch, garbled) == {"category": "pizza", "parser": "rules"}


def test_no_text_means_no_filters(monkeypatch):
    assert run("", monkeypatch, None) == {}
