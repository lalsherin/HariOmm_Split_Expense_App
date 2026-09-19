"""Sync endpoint."""
import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..deps import current_user
from ..middleware.rate_limit import enforce
from ..models import Counter, User
from ..schemas import SyncRequest, SyncResponse
from . import service

router = APIRouter(prefix="/sync", tags=["sync"])
settings = get_settings()

# Never hold a request longer than this, whatever the client asks for. The app
# abandons a request after 20 seconds, so anything close to that would show up
# as "No connection" rather than as waiting.
MAX_WAIT = 15
POLL_EVERY = 0.75


async def _global_seq(db: AsyncSession) -> int:
    """The server-wide change counter — one cheap read.

    Every write anywhere bumps it, so while it sits still nothing can possibly
    have appeared for this account either, and there is no reason to run the
    four per-table queries a real pull costs.
    """
    value = await db.scalar(select(Counter.value).where(Counter.name == "sync"))
    await db.commit()          # don't sit on a snapshot between checks
    return int(value or 0)


@router.post("", response_model=SyncResponse)
@router.post("/", response_model=SyncResponse, include_in_schema=False)
async def sync(
    body: SyncRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await enforce(db, f"sync:{user.id}", settings.rl_sync_per_user,
                  settings.rl_sync_per_user_window)
    rejected = await service.push(db, user, body.changes)
    out = await service.pull(db, user, body.since)
    await db.commit()

    def empty(d):
        return not (d["groups"] or d["members"] or d["expenses"] or d["settlements"])

    # Nothing to report yet, and the phone said it is willing to wait: hold the
    # request open rather than hanging up and making it ask again in two
    # minutes. This is what makes a group appear on the other phone about a
    # second after it is created.
    wait = max(0, min(int(body.wait or 0), MAX_WAIT))
    if wait and not rejected and empty(out):
        seen = await _global_seq(db)
        deadline = asyncio.get_event_loop().time() + wait
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(POLL_EVERY)
            now = await _global_seq(db)
            if now == seen:
                continue                      # nothing has changed anywhere
            seen = now
            out = await service.pull(db, user, body.since)
            await db.commit()
            if not empty(out):
                break                         # something for this account

    return SyncResponse(rejected=rejected, **out)
