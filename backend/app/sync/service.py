"""Two-way sync.

The phone is the source of truth for what its owner typed; the server is the
meeting point. Neither blocks the other, so the app keeps working with no
signal and reconciles later.

Shape of it:

  push   the phone sends everything it changed since its last successful sync.
         Each row is accepted only if the sender can see its group. Conflicts
         resolve last-writer-wins on the row's `updated_at`.
  pull   the server returns every row in the sender's groups with
         `seq` greater than the `since` the phone last saw.

`seq` is a server-assigned counter, not a clock, so two phones with wrong
clocks cannot miss each other's changes.
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import next_seq
from ..models import Expense, Group, GroupMember, Settlement, User, utcnow
from ..phone import InvalidPhoneNumber, normalise

_settings = get_settings()


def parse_ts(value: Optional[str]) -> datetime:
    if not value:
        return utcnow()
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return utcnow()


def _aware(dt: Optional[datetime]) -> datetime:
    if dt is None:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return _aware(dt).isoformat() if dt else None


async def visible_group_ids(db: AsyncSession, user: User) -> Set[str]:
    """Groups this account may read or write: ones it is a member of, plus
    ones it created (so a group survives its creator removing themselves)."""
    member_of = await db.scalars(
        select(GroupMember.group_id).where(
            GroupMember.user_id == user.id, GroupMember.deleted.is_(False)
        )
    )
    created = await db.scalars(select(Group.id).where(Group.created_by == user.id))
    return set(member_of.all()) | set(created.all())


async def _resolve_member_user(db: AsyncSession, phone_e164: Optional[str]) -> Optional[str]:
    if not phone_e164:
        return None
    return await db.scalar(select(User.id).where(User.mobile_number == phone_e164))


async def push(db: AsyncSession, user: User, changes) -> List[Dict[str, Any]]:
    """Apply the phone's changes. Returns the rows that were refused."""
    rejected: List[Dict[str, Any]] = []
    allowed = await visible_group_ids(db, user)

    # ---- groups. A group that does not exist yet is created by its sender,
    # which also makes them its first stakeholder.
    for g in changes.groups:
        existing = await db.get(Group, g.id)
        incoming_at = parse_ts(g.updated_at)
        if existing is None:
            db.add(Group(
                id=g.id, name=g.name, currency=g.currency, created_by=user.id,
                created_at=incoming_at, updated_at=incoming_at,
                deleted=g.deleted, seq=await next_seq(db),
            ))
            allowed.add(g.id)
            continue
        if g.id not in allowed:
            rejected.append({"kind": "group", "id": g.id, "reason": "not_a_member"})
            continue
        if incoming_at < _aware(existing.updated_at):
            continue                                    # ours is newer; keep it
        existing.name = g.name
        existing.currency = g.currency
        existing.deleted = g.deleted
        existing.updated_at = incoming_at
        existing.seq = await next_seq(db)

    # ---- members. The phone number on a member row is what hands the group
    # to that person when they sign in.
    for m in changes.members:
        if m.group_id not in allowed:
            rejected.append({"kind": "member", "id": m.id, "reason": "not_a_member"})
            continue
        phone = None
        if m.phone:
            try:
                phone = normalise(m.phone, _settings.default_country_code)
            except InvalidPhoneNumber:
                phone = None                            # keep the name, drop the bad number
        incoming_at = parse_ts(m.updated_at)
        existing = await db.get(GroupMember, m.id)
        linked = await _resolve_member_user(db, phone)
        if existing is None:
            db.add(GroupMember(
                id=m.id, group_id=m.group_id, user_id=linked, phone_e164=phone,
                name=m.name, role=m.role, joined_at=incoming_at,
                updated_at=incoming_at, deleted=m.deleted, seq=await next_seq(db),
            ))
            continue
        if incoming_at < _aware(existing.updated_at):
            continue
        existing.name = m.name
        existing.phone_e164 = phone
        existing.role = m.role
        existing.deleted = m.deleted
        if linked:
            existing.user_id = linked
        existing.updated_at = incoming_at
        existing.seq = await next_seq(db)

    # ---- expenses
    for e in changes.expenses:
        if e.group_id not in allowed:
            rejected.append({"kind": "expense", "id": e.id, "reason": "not_a_member"})
            continue
        incoming_at = parse_ts(e.updated_at)
        existing = await db.get(Expense, e.id)
        fields = dict(
            group_id=e.group_id, description=e.description, amount_minor=e.amount_minor,
            currency=e.currency, category=e.category, expense_date=e.expense_date,
            split_type=e.split_type, paid_by=e.paid_by,
            payers_json=json.dumps(e.payers), splits_json=json.dumps(e.splits),
            values_json=json.dumps(e.values), deleted=e.deleted,
        )
        if existing is None:
            db.add(Expense(id=e.id, created_by=user.id, created_at=incoming_at,
                           updated_at=incoming_at, seq=await next_seq(db), **fields))
            continue
        if incoming_at < _aware(existing.updated_at):
            continue
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.updated_at = incoming_at
        existing.seq = await next_seq(db)

    # ---- settlements
    for s in changes.settlements:
        if s.group_id not in allowed:
            rejected.append({"kind": "settlement", "id": s.id, "reason": "not_a_member"})
            continue
        incoming_at = parse_ts(s.updated_at)
        existing = await db.get(Settlement, s.id)
        fields = dict(
            group_id=s.group_id, from_member=s.from_member, to_member=s.to_member,
            amount_minor=s.amount_minor, currency=s.currency, method=s.method,
            note=s.note, settled_date=s.settled_date, deleted=s.deleted,
        )
        if existing is None:
            db.add(Settlement(id=s.id, created_by=user.id, created_at=incoming_at,
                              updated_at=incoming_at, seq=await next_seq(db), **fields))
            continue
        if incoming_at < _aware(existing.updated_at):
            continue
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.updated_at = incoming_at
        existing.seq = await next_seq(db)

    await db.flush()
    return rejected


async def pull(db: AsyncSession, user: User, since: int) -> Dict[str, Any]:
    """Everything in this account's groups that changed after `since`."""
    allowed = await visible_group_ids(db, user)
    if not allowed:
        return {"seq": since, "groups": [], "members": [], "expenses": [], "settlements": []}

    groups = (await db.scalars(
        select(Group).where(Group.id.in_(allowed), Group.seq > since).order_by(Group.seq)
    )).all()
    members = (await db.scalars(
        select(GroupMember).where(GroupMember.group_id.in_(allowed), GroupMember.seq > since)
        .order_by(GroupMember.seq)
    )).all()
    expenses = (await db.scalars(
        select(Expense).where(Expense.group_id.in_(allowed), Expense.seq > since)
        .order_by(Expense.seq)
    )).all()
    settlements = (await db.scalars(
        select(Settlement).where(Settlement.group_id.in_(allowed), Settlement.seq > since)
        .order_by(Settlement.seq)
    )).all()

    high = since
    for coll in (groups, members, expenses, settlements):
        for row in coll:
            high = max(high, int(row.seq or 0))

    return {
        "seq": high,
        "groups": [{
            "id": g.id, "name": g.name, "currency": g.currency,
            "created_by": g.created_by, "deleted": g.deleted,
            "updated_at": _iso(g.updated_at), "seq": g.seq,
        } for g in groups],
        "members": [{
            "id": m.id, "group_id": m.group_id, "name": m.name,
            "phone": m.phone_e164, "user_id": m.user_id, "role": m.role,
            "deleted": m.deleted, "updated_at": _iso(m.updated_at), "seq": m.seq,
        } for m in members],
        "expenses": [{
            "id": e.id, "group_id": e.group_id, "description": e.description,
            "amount_minor": e.amount_minor, "currency": e.currency,
            "category": e.category, "expense_date": e.expense_date,
            "split_type": e.split_type, "paid_by": e.paid_by,
            "payers": json.loads(e.payers_json or "{}"),
            "splits": json.loads(e.splits_json or "{}"),
            "values": json.loads(e.values_json or "{}"),
            "deleted": e.deleted, "updated_at": _iso(e.updated_at), "seq": e.seq,
        } for e in expenses],
        "settlements": [{
            "id": s.id, "group_id": s.group_id, "from_member": s.from_member,
            "to_member": s.to_member, "amount_minor": s.amount_minor,
            "currency": s.currency, "method": s.method, "note": s.note,
            "settled_date": s.settled_date, "deleted": s.deleted,
            "updated_at": _iso(s.updated_at), "seq": s.seq,
        } for s in settlements],
    }
