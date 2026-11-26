import pytest
from fastapi.testclient import TestClient

from app import llm, ratelimit
from app.config import settings
from app.main import app
from app.prompts import SYSTEM_PROMPT
from app.schemas import PROP_MODELS

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    monkeypatch.setattr(llm, "configured_providers", lambda: [])
    monkeypatch.setattr(llm, "MOCK_DELAY", 0)
    ratelimit._hits.clear()


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_generate_returns_valid_ui():
    r = client.post("/api/generate", json={"prompt": "plan my week"})
    assert r.status_code == 200
    body = r.json()
    assert body["ui"]["type"] == "Stack"
    assert body["title"] == "plan my week"
    assert body["summary"]


def test_stream_emits_text_then_ui_then_done():
    r = client.post("/api/generate/stream", json={"prompt": "plan my week"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = [e.splitlines()[0] for e in r.text.strip().split("\n\n")]
    assert events[0] == "event: text"
    assert events[-2] == "event: ui"
    assert events[-1] == "event: done"


def test_stream_reports_failure_as_error_event(monkeypatch):
    async def boom(*args, **kwargs):
        raise llm.GenerationError("provider details")
        yield  # pragma: no cover  (makes this an async generator)

    monkeypatch.setattr("app.routes.generate.stream_generate", boom)
    r = client.post("/api/generate/stream", json={"prompt": "x"})
    assert "event: error" in r.text
    assert "provider details" not in r.text  # internals are not leaked


def test_generation_failure_maps_to_502(monkeypatch):
    async def boom(*args, **kwargs):
        raise llm.GenerationError("provider details")

    monkeypatch.setattr("app.routes.generate.generate_ui", boom)
    r = client.post("/api/generate", json={"prompt": "x"})
    assert r.status_code == 502
    assert "provider details" not in r.text


def test_empty_prompt_rejected():
    assert client.post("/api/generate", json={"prompt": ""}).status_code == 422


def test_invalid_current_ui_rejected():
    body = {"prompt": "x", "current_ui": {"type": "Script"}}
    assert client.post("/api/generate", json=body).status_code == 422


def test_rate_limit(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 2)
    codes = [
        client.post("/api/generate", json={"prompt": "x"}).status_code for _ in range(3)
    ]
    assert codes == [200, 200, 429]


def test_prompt_documents_every_component():
    for name in PROP_MODELS:
        assert f"- {name}:" in SYSTEM_PROMPT
