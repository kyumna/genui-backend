"""Postgres connection pool and schema (psycopg 3, async)."""

import logging

from psycopg_pool import AsyncConnectionPool

log = logging.getLogger("genui.db")

SCHEMA = """
create table if not exists layouts (
    id         uuid primary key default gen_random_uuid(),
    slug       text unique not null,
    prompt     text not null,
    title      text not null,
    ui_json    jsonb not null,
    created_at timestamptz not null default now()
)
"""

_pool: AsyncConnectionPool | None = None


class SharingUnavailable(Exception):
    """No database is configured or reachable."""


async def init_db(url: str) -> None:
    global _pool
    pool = AsyncConnectionPool(
        url,
        min_size=0,  # Neon's free tier sleeps; do not hold idle connections open
        max_size=4,
        open=False,
        timeout=15,
        check=AsyncConnectionPool.check_connection,  # drop connections the server closed
        kwargs={"autocommit": True, "prepare_threshold": None},  # safe with poolers
    )
    await pool.open()
    try:
        async with pool.connection() as conn:
            await conn.execute(SCHEMA)
    except Exception:
        await pool.close()
        raise
    _pool = pool
    log.info("Database ready")


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> AsyncConnectionPool:
    if _pool is None:
        raise SharingUnavailable("Database is not configured")
    return _pool
