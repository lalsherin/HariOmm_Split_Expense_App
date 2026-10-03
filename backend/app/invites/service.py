"""Group invite links: create, check, accept, revoke.

An invite is a capability: whoever holds the link may ask to join. So the
token is random (128 bits from `secrets`), unrelated to the group's id, stored
only as a hash, and checked every time against the current state of the
world — revoked, expired, group deleted — before anything is done with it.

Joining still needs a signed-in account (the server decides who you are, from
your session) and an explicit Join on the phone; opening a link never adds
anyone. A join is one ordinary group_members row, exactly what adding someone
by number creates, so sync, balances and the late-install rules all apply to
it unchanged.
"""
import re
import secrets
from datetime import timedelta
from typing import Optional, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import next_seq
from ..models import (Expense, Group, GroupHidden, GroupInvite, GroupMember, User,
                      new_id, utcnow)
from ..security import as_aware, hash_token
from ..sync.service import visible_group_ids

_settings = get_settings()

# token_urlsafe(16) is 22 characters of [A-Za-z0-9_-]. Anything else is not a
# token we issued, and is turned away before it reaches the database.
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")

MESSAGES = {
    "ok": "",
    "invalid": "This invite link isn't valid.",
    "expired": "This invite link has expired. Ask for a new one.",
    "revoked": "This invite link has been replaced by a newer one. Ask for a new one.",
    "deleted": "This group is no longer available.",
    "owner": "You are already the owner of this group.",
    "already_member": "You're already a member of this group.",
    "joined": "You've joined the group.",
}


class InviteError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


async def create(db: AsyncSession, user: User, group_id: str) -> Tuple[str, GroupInvite]:
    """A new link for a group the caller is in. Any member may invite: members
    can already add people by number, so this gives nobody a new power."""
    group = await db.get(Group, group_id)
    if group is None or group.deleted:
        raise InviteError(404, MESSAGES["deleted"])
    if group_id not in await visible_group_ids(db, user):
        raise InviteError(403, "You're not in that group.")
    token = secrets.token_urlsafe(16)
    row = GroupInvite(
        id=new_id(), group_id=group_id, token_hash=hash_token(token), created_by=user.id,
        created_at=utcnow(), expires_at=utcnow() + timedelta(days=_settings.invite_days),
    )
    db.add(row)
    await db.flush()
    return token, row


async def resolve(db: AsyncSession, token: str) -> Tuple[str, Optional[GroupInvite], Optional[Group]]:
    """What a token currently opens: ("ok", invite, group) or a reason it opens
    nothing. Never says more than the reason."""
    if not token or not _TOKEN.match(token):
        return "invalid", None, None
    inv = await db.scalar(select(GroupInvite).where(GroupInvite.token_hash == hash_token(token)))
    if inv is None:
        return "invalid", None, None
    if inv.revoked_at is not None:
        return "revoked", inv, None
    if as_aware(inv.expires_at) <= utcnow():
        return "expired", inv, None
    group = await db.get(Group, inv.group_id)
    if group is None or group.deleted:
        return "deleted", inv, None
    return "ok", inv, group


async def _membership(db: AsyncSession, user: User, group: Group) -> Optional[GroupMember]:
    """A live member row that is this person: linked to their account, or
    holding their number and waiting to be claimed."""
    return await db.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group.id,
            GroupMember.deleted.is_(False),
            (GroupMember.user_id == user.id) | (GroupMember.phone_e164 == user.mobile_number),
        ).limit(1)
    )


async def _standing(db: AsyncSession, user: User, group: Group) -> Optional[str]:
    if group.created_by == user.id:
        return "owner"
    row = await _membership(db, user, group)
    if row is not None:
        if row.user_id is None:              # added by number, not yet claimed: claim it
            row.user_id = user.id
            row.updated_at = utcnow()
            row.seq = await next_seq(db)
        return "already_member"
    return None


async def summary(db: AsyncSession, group: Group) -> dict:
    """What the invitee is shown before joining: name, size, amount tracked.
    No member names, numbers, ids or individual expenses."""
    members = await db.scalar(select(func.count()).select_from(GroupMember).where(
        GroupMember.group_id == group.id, GroupMember.deleted.is_(False)))
    total = await db.scalar(select(func.coalesce(func.sum(Expense.amount_minor), 0)).where(
        Expense.group_id == group.id, Expense.deleted.is_(False)))
    return {"name": group.name, "currency": group.currency,
            "members": int(members or 0), "total_minor": int(total or 0)}


async def preview(db: AsyncSession, user: User, token: str) -> dict:
    status, inv, group = await resolve(db, token)
    out = {"status": status, "message": MESSAGES[status]}
    if status != "ok":
        return out
    standing = await _standing(db, user, group)
    out["group"] = await summary(db, group)
    if standing:
        out.update(status=standing, message=MESSAGES[standing], group_id=group.id)
    return out


async def accept(db: AsyncSession, user: User, token: str) -> dict:
    status, inv, group = await resolve(db, token)
    if status != "ok":
        return {"status": status, "message": MESSAGES[status]}
    standing = await _standing(db, user, group)
    if standing:
        return {"status": standing, "message": MESSAGES[standing], "group_id": group.id}
    now = utcnow()
    db.add(GroupMember(
        id="m-" + new_id(), group_id=group.id, user_id=user.id, phone_e164=user.mobile_number,
        name=user.name, role="member", joined_at=now, updated_at=now, deleted=False,
        seq=await next_seq(db),
    ))
    # Joining is being added, and being added cancels an earlier "remove from
    # my view" — the same rule as when the owner adds you back by number.
    hidden = await db.get(GroupHidden, {"user_id": user.id, "group_id": group.id})
    if hidden is not None:
        await db.delete(hidden)
    await db.flush()
    return {"status": "joined", "message": MESSAGES["joined"], "group_id": group.id}


async def revoke_all(db: AsyncSession, user: User, group_id: str) -> int:
    """Owner only: every live link for the group stops working."""
    group = await db.get(Group, group_id)
    if group is None or group.deleted:
        raise InviteError(404, MESSAGES["deleted"])
    if group.created_by != user.id:
        raise InviteError(403, "Only the person who created the group can do that.")
    res = await db.execute(
        update(GroupInvite)
        .where(GroupInvite.group_id == group_id, GroupInvite.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    await db.flush()
    return int(res.rowcount or 0)
