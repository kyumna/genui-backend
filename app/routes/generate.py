import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from app.llm import GenerationError, Reset, TextDelta, generate_ui, stream_generate
from app.ratelimit import rate_limit
from app.schemas import UINode, validate_ui

log = logging.getLogger("genui.generate")

router = APIRouter(prefix="/api", tags=["generate"])

FRIENDLY_FAILURE = "The AI could not build that interface right now. Try again or rephrase."


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    # Lets the user refine an existing UI ("make the table a chart").
    current_ui: UINode | None = None


class GenerateResponse(BaseModel):
    ui: UINode
    title: str
    summary: str


def _prepare(body: GenerateRequest) -> tuple[str, UINode | None]:
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="Prompt is empty.")
    current = None
    if body.current_ui is not None:
        try:
            current = validate_ui(body.current_ui)
        except (ValueError, ValidationError):
            raise HTTPException(status_code=422, detail="current_ui is not a valid UI.")
    return prompt, current


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post(
    "/generate",
    response_model=GenerateResponse,
    dependencies=[Depends(rate_limit)],
)
async def generate(body: GenerateRequest) -> GenerateResponse:
    prompt, current = _prepare(body)
    try:
        result = await generate_ui(prompt, current)
    except GenerationError as exc:
        # Details (provider names, status codes) stay in the server log.
        log.error("Generation failed: %s", exc)
        raise HTTPException(status_code=502, detail=FRIENDLY_FAILURE)
    return GenerateResponse(ui=result.ui, title=result.title, summary=result.summary)


@router.post("/generate/stream", dependencies=[Depends(rate_limit)])
async def generate_stream(body: GenerateRequest) -> StreamingResponse:
    prompt, current = _prepare(body)

    async def events():
        try:
            async for event in stream_generate(prompt, current):
                if isinstance(event, TextDelta):
                    yield _sse("text", {"delta": event.delta})
                elif isinstance(event, Reset):
                    yield _sse("reset", {})
                else:
                    ui = event.ui.model_dump(mode="json", exclude_none=True)
                    yield _sse("ui", {"ui": ui, "title": event.title})
        except GenerationError as exc:
            log.error("Generation failed: %s", exc)
            yield _sse("error", {"message": FRIENDLY_FAILURE})
        except Exception:
            log.exception("Unexpected error while streaming")
            yield _sse("error", {"message": "Something went wrong. Please try again."})
        else:
            yield _sse("done", {})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
