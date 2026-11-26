import asyncio
import json

import httpx
import pytest

from app import llm
from app.llm import (
    GenerationError,
    Provider,
    Reset,
    TextDelta,
    UIReady,
    stream_generate,
)

GOOD = {
    "type": "Stack",
    "props": {"gap": 4},
    "children": [{"type": "Heading", "props": {"text": "Hi"}}],
}
SUMMARY = "Here is a small greeting page."
FULL = f"{SUMMARY}\n{llm.DELIMITER}\n{json.dumps(GOOD)}"
PROVIDERS = [
    Provider("gemini", "https://gem.test/chat", "k1", "m1"),
    Provider("groq", "https://groq.test/chat", "k2", "m2"),
]


def sse(text: str, chunk: int = 7) -> httpx.Response:
    """A streamed chat completion that delivers `text` in small pieces."""
    parts = [
        "data: "
        + json.dumps({"choices": [{"delta": {"content": text[i : i + chunk]}}]})
        + "\n\n"
        for i in range(0, len(text), chunk)
    ]
    parts.append("data: [DONE]\n\n")
    return httpx.Response(
        200,
        content="".join(parts).encode(),
        headers={"content-type": "text/event-stream"},
    )


@pytest.fixture(autouse=True)
def two_providers(monkeypatch):
    monkeypatch.setattr(llm, "configured_providers", lambda: PROVIDERS)
    monkeypatch.setattr(llm, "MOCK_DELAY", 0)


def collect(handler, prompt="compare laptops"):
    async def go():
        events = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            async for ev in stream_generate(prompt, client=c):
                events.append(ev)
        return events

    return asyncio.run(go())


def text_of(events) -> str:
    return "".join(e.delta for e in events if isinstance(e, TextDelta))


def test_streams_summary_then_ui():
    events = collect(lambda req: sse(FULL))
    assert text_of(events) == SUMMARY
    assert isinstance(events[-1], UIReady)
    assert events[-1].title == "Hi"


@pytest.mark.parametrize("chunk", [1, 2, 3, 5])
def test_delimiter_split_across_chunks(chunk):
    events = collect(lambda req: sse(FULL, chunk))
    out = text_of(events)
    assert out == SUMMARY
    assert "-" not in out and "{" not in out


def test_json_only_output_gets_fallback_summary():
    events = collect(lambda req: sse(json.dumps(GOOD)))
    assert 'Here is "Hi"' in text_of(events)
    assert isinstance(events[-1], UIReady)


def test_fenced_and_wrapped_json_is_accepted():
    wrapped = f"Summary.\n{llm.DELIMITER}\n```json\n" + json.dumps({"ui": GOOD}) + "\n```"
    events = collect(lambda req: sse(wrapped))
    assert events[-1].ui.type == "Stack"


def test_retry_with_validation_error_is_silent():
    bodies = []

    def handler(req):
        bodies.append(json.loads(req.content))
        if len(bodies) == 1:
            return sse(f"First summary.\n{llm.DELIMITER}\n" + '{"type": "Script"}')
        return sse(json.dumps(GOOD))

    events = collect(handler)
    assert len(bodies) == 2
    assert "invalid" in bodies[1]["messages"][-1]["content"]
    assert text_of(events) == "First summary."  # not repeated on retry
    assert isinstance(events[-1], UIReady)


def test_falls_back_on_rate_limit():
    def handler(req):
        if req.url.host == "gem.test":
            return httpx.Response(429)
        return sse(FULL)

    events = collect(handler)
    assert isinstance(events[-1], UIReady)
    assert not any(isinstance(e, Reset) for e in events)


def test_reset_when_provider_fails_after_streaming_text():
    def handler(req):
        if req.url.host == "gem.test":
            return sse(f"Gemini summary.\n{llm.DELIMITER}\nnot json")
        return sse(FULL)

    events = collect(handler)
    kinds = [type(e).__name__ for e in events]
    assert "Reset" in kinds
    assert kinds.index("Reset") < kinds.index("UIReady")
    after_reset = events[kinds.index("Reset") + 1 :]
    assert text_of(after_reset) == SUMMARY


def test_all_providers_fail():
    with pytest.raises(GenerationError):
        collect(lambda req: httpx.Response(500))


def test_bad_output_everywhere_fails():
    with pytest.raises(GenerationError):
        collect(lambda req: sse("not json at all"))


def test_no_keys_streams_mock(monkeypatch):
    monkeypatch.setattr(llm, "configured_providers", lambda: [])
    events = asyncio.run(_drain(stream_generate("my prompt")))
    assert text_of(events)
    assert events[-1].ui.children[0].props["text"] == "my prompt"
    assert events[-1].title == "my prompt"


async def _drain(gen):
    return [e async for e in gen]
