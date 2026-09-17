"""Sign-in, sessions, and linking a number to the groups already waiting for it."""
import secrets
from typing import Optional, Tuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..database import next_seq
from ..models import (
    GroupMember, LoginHistory, Session as SessionRow, User, new_id, utcnow,
)
from ..security import (
    as_aware, hash_token, in_days, in_minutes, new_token,
)


def _burn_refresh(row: SessionRow) -> None:
    """Make a session's refresh token impossible to look up again.

    Revoking a session is not enough on its own. `rotate_session` deliberately
    still finds recently-rotated rows, so that a phone which never heard the
    reply to its last refresh can retry (see the grace window there). A session
    ended on purpose — signed out, or dropped because a token was replayed —
    must not be reachable that way, so its refresh hash is replaced with a
    value nothing will ever present.
    """
    row.refresh_hash = secrets.token_hex(32)


async def find_user(db: AsyncSession, mobile: str) -> Optional[User]:
    return await db.scalar(select(User).where(User.mobile_number == mobile))


async def register_or_login(
    db: AsyncSession, mobile: str, name: Optional[str]
) -> Tuple[User, bool]:
    """One door for new and returning people, as the spec asks. Returns the
    user and whether the account was just created."""
    user = await find_user(db, mobile)
    if user is not None:
        if name and name.strip() and name.strip() != user.name:
            user.name = name.strip()[:120]
        user.last_login_at = utcnow()
        user.updated_at = utcnow()
        await db.flush()
        return user, False

    clean = (name or "").strip()[:120]
    if not clean:
        clean = "Member"
    user = User(
        id=new_id(),
        mobile_number=mobile,
        name=clean,
        mobile_verified=False,
        account_status="active",
        last_login_at=utcnow(),
    )
    db.add(user)
    await db.flush()
    return user, True


async def claim_memberships(db: AsyncSession, user: User) -> int:
    """Attach this account to every group member row that was created for its
    number before it existed. This is what makes "add someone from your
    contacts and they see the group" work.

    Each claimed row gets a fresh seq so the other phones in the group learn
    that the placeholder is now a real person.
    """
    rows = (await db.scalars(
        select(GroupMember).where(
            GroupMember.phone_e164 == user.mobile_number,
            GroupMember.user_id.is_(None),
            GroupMember.deleted.is_(False),
        )
    )).all()
    for row in rows:
        row.user_id = user.id
        row.updated_at = utcnow()
        row.seq = await next_seq(db)
    if rows:
        await db.flush()
    return len(rows)


async def issue_session(
    db: AsyncSession,
    user: User,
    settings: Settings,
    device_information: Optional[str],
    platform: Optional[str],
) -> Tuple[str, str, SessionRow]:
    access, refresh = new_token(), new_token()
    row = SessionRow(
        id=new_id(),
        user_id=user.id,
        access_hash=hash_token(access),
        refresh_hash=hash_token(refresh),
        access_expires_at=in_minutes(settings.access_token_minutes),
        refresh_expires_at=in_days(settings.refresh_token_days),
        device_information=(device_information or "")[:200] or None,
        platform=(platform or "")[:40] or None,
    )
    db.add(row)
    await db.flush()
    return access, refresh, row


async def rotate_session(
    db: AsyncSession, refresh_token: str, settings: Settings
) -> Optional[Tuple[str, str, User]]:
    """Exchange a refresh token for a new pair.

    The old token is spent as it is used. Presenting a spent one again is
    either a phone that never heard the reply, or a copy in someone else's
    hands; `refresh_grace_seconds` decides which, and the two outcomes are
    opposite — reissue, or drop every session this account has.

    A session ended deliberately (logout, or the theft response) has its
    refresh hash burned as well, so it can never come back through the
    grace window.
    """
    now = utcnow()
    row = await db.scalar(
        select(SessionRow).where(SessionRow.refresh_hash == hash_token(refresh_token))
    )
    if row is None:
        return None

    if row.revoked_at is not None:
        # A spent token came back. Two very different things look like this.
        #
        # 1. The reply to the last refresh never reached the phone — it timed
        #    out, or the app was backgrounded, or the server was still waking
        #    up. The phone still holds the old token because it never learned
        #    the new one. This is ordinary and happens to honest users.
        # 2. Someone copied a token and is replaying it.
        #
        # Time tells them apart well enough: a dropped reply is retried within
        # seconds, a stolen token turns up whenever the thief gets round to it.
        # Inside the grace window, reissue — which is what the phone was owed
        # in the first place. Outside it, assume the worst and drop every
        # session this account has.
        spent_ago = (now - as_aware(row.revoked_at)).total_seconds()
        if 0 <= spent_ago <= settings.refresh_grace_seconds:
            user = await db.get(User, row.user_id)
            if user is None or user.account_status != "active":
                return None
            access, refresh, _ = await issue_session(
                db, user, settings, row.device_information, row.platform
            )
            return access, refresh, user

        live = (await db.scalars(
            select(SessionRow).where(
                SessionRow.user_id == row.user_id, SessionRow.revoked_at.is_(None)
            )
        )).all()
        for dead in live:
            dead.revoked_at = now
            _burn_refresh(dead)
        _burn_refresh(row)          # and the replayed one cannot be tried again
        await db.flush()
        return None

    if as_aware(row.refresh_expires_at) < now:
        return None

    user = await db.get(User, row.user_id)
    if user is None or user.account_status != "active":
        return None

    row.revoked_at = now
    access, refresh, _ = await issue_session(
        db, user, settings, row.device_information, row.platform
    )
    return access, refresh, user


async def revoke_by_access(db: AsyncSession, access_token: str) -> bool:
    row = await db.scalar(
        select(SessionRow).where(SessionRow.access_hash == hash_token(access_token))
    )
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = utcnow()
    _burn_refresh(row)
    await db.flush()
    return True


async def record_login(
    db: AsyncSession,
    user: Optional[User],
    mobile: str,
    ip: Optional[str],
    device_information: Optional[str],
    platform: Optional[str],
    status_text: str,
) -> None:
    db.add(LoginHistory(
        id=new_id(),
        user_id=user.id if user else None,
        mobile_number=mobile,
        ip_address=(ip or "")[:64] or None,
        device_information=(device_information or "")[:200] or None,
        platform=(platform or "")[:40] or None,
        login_status=status_text,
    ))
    await db.flush()
