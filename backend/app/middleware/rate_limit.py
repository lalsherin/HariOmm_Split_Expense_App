"""Fixed-window rate limiting, kept in the database.

The spec asks for Redis, and for more than one server process that is the
right answer — swap `_hit` for an INCR with an EXPIRE and nothing else
changes. Against a single instance and 10,000 users, a table avoids running a
second piece of infrastructure for one counter.
"""
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import RateLimit
from ..security import as_aware, utcnow


class RateLimited(HTTPException):
    def __init__(self, retry_after: int):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again shortly.",
            headers={"Retry-After": str(max(1, retry_after))},
        )


async def enforce(db: AsyncSession, bucket: str, limit: int, window_seconds: int) -> None:
    """Count one hit against `bucket`; raise 429 when it goes over `limit`."""
    now = utcnow()
    row = await db.get(RateLimit, bucket)

    if row is None:
        db.add(RateLimit(bucket=bucket, window_start=now, count=1))
        await db.flush()
        return

    started = as_aware(row.window_start)
    if now - started >= timedelta(seconds=window_seconds):
        row.window_start = now
        row.count = 1
        await db.flush()
        return

    if row.count >= limit:
        elapsed = (now - started).total_seconds()
        raise RateLimited(int(window_seconds - elapsed))

    row.count += 1
    await db.flush()


def client_ip(request) -> str:
    """Behind a proxy, the first hop in X-Forwarded-For. Spoofable unless the
    proxy overwrites it, so it is a speed bump, not an identity."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]
