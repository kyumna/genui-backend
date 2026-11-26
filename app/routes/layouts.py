import json
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg import Error as PsycopgError
from psycopg_pool import PoolTimeout
from pydantic import BaseModel, Field, ValidationError

from app import repo
from app.db import SharingUnavailable
from app.ratelimit import save_rate_limit
from app.schemas import UINode, validate_ui

log = logging.getLogger("genui.layouts")

router = APIRouter(prefix="/api", tags=["layouts"])

MAX_UI_BYTES = 100_000
SLUG = re.compile(r"^[A-Za-z0-9_-]{6,16}$")
NOT_CONFIGURED = "Sharing is not set up on this server."
DB_DOWN = "Could not reach the database. Please try again."


class SaveRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=120)
    ui: UINode


class SaveResponse(BaseModel):
    slug: str


class LayoutResponse(BaseModel):
    slug: str
    title: str
    prompt: str
    ui: UINode
    created_at: datetime


@router.post("/layouts", response_model=SaveResponse, dependencies=[Depends(save_rate_limit)])
async def save_layout(body: SaveRequest) -> SaveResponse:
    # Never trust the client: re-validate and cap the size before storing.
    try:
        clean = validate_ui(body.ui)
    except (ValueError, ValidationError):
        raise HTTPException(status_code=422, detail="That UI is not valid.")
    ui = clean.model_dump(mode="json", exclude_none=True)
    if len(json.dumps(ui)) > MAX_UI_BYTES:
        raise HTTPException(status_code=413, detail="That UI is too large to share.")

    try:
        slug = await repo.create_layout(body.prompt.strip(), body.title.strip(), ui)
    except SharingUnavailable:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
    except (PsycopgError, PoolTimeout):
        log.exception("Saving layout failed")
        raise HTTPException(status_code=503, detail=DB_DOWN)
    return SaveResponse(slug=slug)


@router.get("/layouts/{slug}", response_model=LayoutResponse)
async def get_layout(slug: str, response: Response) -> LayoutResponse:
    if not SLUG.match(slug):
        raise HTTPException(status_code=404, detail="Not found.")
    try:
        row = await repo.get_layout(slug)
    except SharingUnavailable:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
    except (PsycopgError, PoolTimeout):
        log.exception("Loading layout failed")
        raise HTTPException(status_code=503, detail=DB_DOWN)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found.")

    # Layouts never change after saving, but re-check against the current schema.
    try:
        row["ui"] = validate_ui(UINode.model_validate(row["ui"]))
    except (ValueError, ValidationError):
        log.error("Stored layout %s no longer validates", slug)
        raise HTTPException(status_code=404, detail="Not found.")

    response.headers["Cache-Control"] = "public, max-age=60"
    return LayoutResponse(**row)
