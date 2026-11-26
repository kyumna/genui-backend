"""Streams a UI from free LLM providers, validates it, retries, and falls back.

The model is asked to write a short summary, then a ---UI--- line, then the JSON.
The summary is forwarded to the client while it is being written; the JSON is
buffered, validated, and sent once complete.
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from app.config import settings
from app.mock import mock_ui
from app.prompts import SYSTEM_PROMPT, build_user_message
from app.schemas import UINode, validate_ui

log = logging.getLogger("genui.llm")

DELIMITER = "---UI---"
ATTEMPTS_PER_PROVIDER = 2  # first try + one retry with the validation error
MOCK_DELAY = 0.03  # seconds between mock "tokens"


class GenerationError(Exception):
    """No provider produced a valid UI."""


class ProviderUnavailable(Exception):
    """Rate limit, outage, bad key, or network error: skip to the next provider."""


@dataclass(frozen=True)
class Provider:
    name: str
    url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class TextDelta:
    delta: str


@dataclass(frozen=True)
class Reset:
    """Discard the summary shown so far (a provider failed after it started)."""


@dataclass(frozen=True)
class UIReady:
    ui: UINode
    title: str


@dataclass(frozen=True)
class Generated:
    ui: UINode
    title: str
    summary: str


StreamEvent = TextDelta | Reset | UIReady


def configured_providers() -> list[Provider]:
    catalog = {
        "gemini": Provider(
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            settings.gemini_api_key or "",
            settings.gemini_model,
        ),
        "groq": Provider(
            "groq",
            "https://api.groq.com/openai/v1/chat/completions",
            settings.groq_api_key or "",
            settings.groq_model,
        ),
    }
    order = [n.strip() for n in settings.provider_order.split(",") if n.strip()]
    return [catalog[n] for n in order if n in catalog and catalog[n].api_key]


def extract_json(text: str) -> str:
    """Return the JSON object in the model output (after the delimiter if present)."""
    if DELIMITER in text:
        text = text.split(DELIMITER, 1)[1]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("No JSON object found in the output")
    return text[start : end + 1]


def parse_ui(text: str) -> UINode:
    """Parse model output into a validated UI tree. Raises ValueError if invalid."""
    data = json.loads(extract_json(text))
    # Some models wrap the tree as {"ui": {...}}.
    if isinstance(data, dict) and "type" not in data and isinstance(data.get("ui"), dict):
        data = data["ui"]
    return validate_ui(UINode.model_validate(data))


def ui_title(ui: UINode, fallback: str) -> str:
    """Title for the file card: the first Heading in the tree."""
    stack = [ui]
    while stack:
        node = stack.pop(0)
        if node.type == "Heading" and isinstance(node.props.get("text"), str):
            return node.props["text"]
        stack.extend(node.children)
    return fallback if len(fallback) <= 60 else fallback[:57] + "..."


class _SummaryStreamer:
    """Releases the summary text as it arrives, and stops before the JSON starts."""

    MARKERS = (DELIMITER, "{", "```")
    HOLD = len(DELIMITER) - 1  # a marker may be split across two chunks

    def __init__(self, emit: bool = True) -> None:
        self.buf = ""
        self.sent = 0
        self.done = not emit

    def feed(self, delta: str) -> str:
        self.buf += delta
        if self.done:
            return ""
        region = self.buf[self.sent :]
        first = self.sent == 0
        cuts = [i for m in self.MARKERS if (i := region.find(m)) != -1]
        if cuts:
            text = region[: min(cuts)]
            self.done = True
            self.sent = len(self.buf)
            return text.strip() if first else text.rstrip()

        releasable = len(region) - self.HOLD
        if releasable <= 0:
            return ""
        raw = region[:releasable]
        lead = len(raw) - len(raw.lstrip()) if first else 0
        body = raw[lead:].rstrip()  # trailing whitespace may precede a marker: hold it
        if not body:
            return ""
        self.sent += lead + len(body)
        return body


async def _stream_chat(
    client: httpx.AsyncClient, p: Provider, messages: list[dict]
) -> AsyncIterator[str]:
    body = {
        "model": p.model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 6000,
        "stream": True,
    }
    try:
        async with client.stream(
            "POST", p.url, headers={"Authorization": f"Bearer {p.api_key}"}, json=body
        ) as r:
            if r.status_code != 200:
                raise ProviderUnavailable(f"{p.name}: HTTP {r.status_code}")
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    return
                try:
                    delta = json.loads(payload)["choices"][0]["delta"].get("content")
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
                if delta:
                    yield delta
    except httpx.HTTPError as exc:
        raise ProviderUnavailable(f"{p.name}: {type(exc).__name__}") from exc


async def _mock_events(prompt: str) -> AsyncIterator[StreamEvent]:
    ui = mock_ui(prompt)
    title = ui_title(ui, prompt)
    summary = (
        f'I put together "{title}" with a summary row, a chart and a table. '
        "This is a mock response, so add an API key to the back end for real AI output."
    )
    for piece in re.findall(r"\S+\s*", summary):
        yield TextDelta(piece)
        if MOCK_DELAY:
            await asyncio.sleep(MOCK_DELAY)
    yield UIReady(ui, title)


async def stream_generate(
    prompt: str,
    current_ui: UINode | None = None,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[StreamEvent]:
    providers = configured_providers()
    if not providers:
        log.warning("No LLM API keys configured; returning the mock UI")
        async for event in _mock_events(prompt):
            yield event
        return

    current_json = current_ui.model_dump_json(exclude_none=True) if current_ui else None
    user_message = build_user_message(prompt, current_json)

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))

    failures: list[str] = []
    shown = False  # is summary text currently visible on the client?
    try:
        for p in providers:
            messages: list[dict] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ]
            for attempt in range(1, ATTEMPTS_PER_PROVIDER + 1):
                # Retries stay silent: the user already has a summary on screen.
                streamer = _SummaryStreamer(emit=not shown and attempt == 1)
                full = ""
                try:
                    async for delta in _stream_chat(client, p, messages):
                        full += delta
                        out = streamer.feed(delta)
                        if out:
                            shown = True
                            yield TextDelta(out)
                except ProviderUnavailable as exc:
                    failures.append(str(exc))
                    break  # no point retrying a down or rate-limited provider

                try:
                    ui = parse_ui(full)
                except (ValueError, ValidationError) as exc:
                    failures.append(f"{p.name}: invalid output on attempt {attempt}")
                    messages = [
                        *messages,
                        {"role": "assistant", "content": full[:4000]},
                        {
                            "role": "user",
                            "content": f"That output was invalid: {str(exc)[:600]}\n"
                            f"Return only the corrected JSON object, with no other text.",
                        },
                    ]
                    continue

                title = ui_title(ui, prompt)
                if not shown:
                    yield TextDelta(f'Here is "{title}". Open it below to explore it.')
                yield UIReady(ui, title)
                return

            if shown:
                yield Reset()  # next provider writes a fresh summary
                shown = False
        raise GenerationError("; ".join(failures))
    finally:
        if owns_client:
            await client.aclose()


async def generate_ui(
    prompt: str,
    current_ui: UINode | None = None,
    client: httpx.AsyncClient | None = None,
) -> Generated:
    """Non-streaming convenience wrapper around stream_generate."""
    summary = ""
    async for event in stream_generate(prompt, current_ui, client):
        if isinstance(event, TextDelta):
            summary += event.delta
        elif isinstance(event, Reset):
            summary = ""
        else:
            return Generated(event.ui, event.title, summary)
    raise GenerationError("The stream ended without a UI")
