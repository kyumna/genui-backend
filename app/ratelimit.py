import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import HTTPException, Request

from app.config import settings

WINDOW_SECONDS = 60
_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def make_rate_limit(bucket: str, limit: Callable[[], int]) -> Callable[[Request], None]:
    """Simple in-memory per-IP limiter, one counter per bucket. Fine for one instance."""

    def dependency(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        hits = _hits[(bucket, ip)]
        while hits and now - hits[0] > WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= limit():
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please wait a minute and try again.",
                headers={"Retry-After": str(WINDOW_SECONDS)},
            )
        hits.append(now)

    return dependency


rate_limit = make_rate_limit("generate", lambda: settings.rate_limit_per_minute)
save_rate_limit = make_rate_limit("save", lambda: settings.save_rate_limit_per_minute)
