import secrets
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from app.db import get_pool

SLUG_ATTEMPTS = 5


async def create_layout(prompt: str, title: str, ui: dict[str, Any]) -> str:
    """Insert a layout and return its public slug."""
    async with get_pool().connection() as conn:
        for _ in range(SLUG_ATTEMPTS):
            slug = secrets.token_urlsafe(6)  # 8 URL-safe characters
            cur = await conn.execute(
                "insert into layouts (slug, prompt, title, ui_json) "
                "values (%s, %s, %s, %s) "
                "on conflict (slug) do nothing returning slug",
                (slug, prompt, title, Jsonb(ui)),
            )
            if await cur.fetchone():
                return slug
    raise RuntimeError("Could not allocate a unique slug")


async def get_layout(slug: str) -> dict[str, Any] | None:
    async with get_pool().connection() as conn:
        cur = await conn.execute(
            "select slug, prompt, title, ui_json, created_at "
            "from layouts where slug = %s",
            (slug,),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    created_at: datetime = row[4]
    return {
        "slug": row[0],
        "prompt": row[1],
        "title": row[2],
        "ui": row[3],
        "created_at": created_at,
    }
