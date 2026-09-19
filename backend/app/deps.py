"""Authentication dependency, and the activity it records."""
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .models import Session as SessionRow, User
from .security import as_aware, hash_token, utcnow

# How stale `last_seen_at` is allowed to get before a request refreshes it.
#
# This is the whole "heartbeat" design: there is no separate ping, because
# every authenticated request already tells us the person is there. The only
# question is how often to write it down. A phone with the app on screen makes
# roughly 280 sync requests an hour, so writing on each one would be 280
# pointless UPDATEs per user per hour, on a free-tier database, to record
# something nobody needs to the second. Fifteen minutes gives at most four
# writes an hour and still answers every question anyone actually asks of it —
# "was this person using the app today?", "is this account dormant?".
LAST_SEEN_EVERY = 900


async def current_user(
    authorization: str = Header(None),
    x_app_version: str = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await _authenticate(authorization, db)
    _touch(user, x_app_version)
    return user


def _touch(user: User, app_version) -> None:
    """Record that this account is alive, and on which build.

    Both writes are conditional, so an idle app holding a sync request open
    costs nothing. Neither is committed here — the endpoint's own commit
    carries them, and if an endpoint does not commit, the only thing lost is a
    timestamp, which is the correct trade for never adding a write barrier to
    a read path.
    """
    now = utcnow()
    seen = as_aware(user.last_seen_at) if user.last_seen_at else None
    if seen is None or (now - seen).total_seconds() >= LAST_SEEN_EVERY:
        user.last_seen_at = now
    if app_version:
        v = str(app_version).strip()[:20]
        if v and v != user.app_version:
            user.app_version = v


_UNAUTH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sign in again.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def _authenticate(authorization, db: AsyncSession) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _UNAUTH
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise _UNAUTH

    row = await db.scalar(
        select(SessionRow).where(SessionRow.access_hash == hash_token(token))
    )
    if row is None or row.revoked_at is not None:
        raise _UNAUTH
    if as_aware(row.access_expires_at) < utcnow():
        raise _UNAUTH

    user = await db.get(User, row.user_id)
    if user is None or user.account_status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not active.",
        )
    return user
