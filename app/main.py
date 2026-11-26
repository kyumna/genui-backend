import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import settings
from app.routes import generate, layouts

log = logging.getLogger("genui")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.database_url:
        try:
            await db.init_db(settings.database_url)
        except Exception:
            log.exception("Database unavailable; sharing is disabled")
    else:
        log.warning("DATABASE_URL is not set; sharing is disabled")
    yield
    await db.close_db()


app = FastAPI(title="genui API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(generate.router)
app.include_router(layouts.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
