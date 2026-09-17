"""Authentication dependency."""
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db
from .models import Session as SessionRow, User
from .security import as_aware, hash_token, utcnow

_UNAUTH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sign in again.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def current_user(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
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
