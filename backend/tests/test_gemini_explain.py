import asyncio

from fastapi.testclient import TestClient

import app.main as m

FACTS = {"id": "v1", "name": "Cheers", "rating": 4.4, "walk_min": 13, "price": "$$", "nearby_events": None}


def test_grounded_accepts_numbers_from_the_facts():
    assert m.grounded("Cheers is a 13-minute walk with a 4.4 rating.", FACTS)
    assert m.grounded("A classic pub that's an easy stroll away.", FACTS)


def test_grounded_rejects_invented_numbers_and_bad_text():
    assert not m.grounded("Open until 2am with a 4.9 rating.", FACTS)
    assert not m.grounded("Nearly 4,000 reviews.", {**FACTS, "review_count": 3949})
    assert m.grounded("A 13 minute walk with a 4.40 rating and 3,949 reviews.", {**FACTS, "review_count": 3949})
    assert not m.grounded("", FACTS) and not m.grounded("x" * 221, FACTS) and not m.grounded(None, FACTS)


def explain(monkeypatch, text):
    async def fake_request_json(*args, **kwargs):
        return None if text is None else {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    monkeypatch.setattr(m, "DEMO", False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(m, "request_json", fake_request_json)
    return asyncio.run(m.gemini_explanation(FACTS))


def test_returns_grounded_line(monkeypatch):
    assert explain(monkeypatch, '{"why": "A lively pub just a 13-minute walk away."}') == "A lively pub just a 13-minute walk away."


def test_rejects_ungrounded_or_failed_replies(monkeypatch):
    assert explain(monkeypatch, '{"why": "Rated 4.9 by 5000 people."}') is None
    assert explain(monkeypatch, None) is None and explain(monkeypatch, "not json") is None and explain(monkeypatch, '["x"]') is None


def test_endpoint_validates_client_facts(monkeypatch):
    monkeypatch.setattr(m, "DEMO", True)
    client = TestClient(m.app)
    ok = client.post("/api/explain", json={"id": "v1", "name": "Cheers", "rating": 4.4, "walk_min": 13})
    assert ok.status_code == 200 and ok.json()["source"] == "unavailable" and ok.json()["explanation"] is None
    assert client.post("/api/explain", json={"id": "v1", "name": "x" * 500}).status_code == 422
    assert client.post("/api/explain", json={"id": "v1", "name": "Cheers", "prompt": "write a poem"}).status_code == 422
