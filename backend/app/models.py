"""Database schema.

Every row that a phone can hold a copy of carries two sync columns:

  seq      a global, monotonically increasing integer stamped on every write.
           Clients ask for "everything with seq > my last seq", which is
           immune to clock skew between phones in a way that timestamps
           are not.
  deleted  a tombstone. Rows are never hard-deleted, because a phone that has
           been offline needs to learn that something went away.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Counter(Base):
    """Single-row table backing the global sync sequence."""
    __tablename__ = "counters"
    name = Column(String(32), primary_key=True)
    value = Column(BigInteger, nullable=False, default=0)


class User(Base):
    __tablename__ = "users"
    id = Column(String(36), primary_key=True, default=new_id)
    mobile_number = Column(String(20), nullable=False, unique=True, index=True)
    name = Column(String(120), nullable=False)
    mobile_verified = Column(Boolean, nullable=False, default=False)
    account_status = Column(String(16), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    # Last authenticated request from this account, written at most once every
    # LAST_SEEN_EVERY seconds so that an app holding a sync request open does
    # not turn into one database write per request.
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    # The build the phone last talked to us with, taken from the X-App-Version
    # header. Kept so that "which version is this person on?" is answerable
    # without asking them, which is most of the work in any sync complaint.
    app_version = Column(String(20), nullable=True)


class Session(Base):
    """A live sign-in. Tokens are stored only as SHA-256 hashes, so a dump of
    this table cannot be replayed against the API."""
    __tablename__ = "sessions"
    id = Column(String(36), primary_key=True, default=new_id)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    access_hash = Column(String(64), nullable=False, index=True)
    refresh_hash = Column(String(64), nullable=False, index=True)
    access_expires_at = Column(DateTime(timezone=True), nullable=False)
    refresh_expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    device_information = Column(String(200), nullable=True)
    platform = Column(String(40), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class LoginHistory(Base):
    __tablename__ = "login_history"
    id = Column(String(36), primary_key=True, default=new_id)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    mobile_number = Column(String(20), nullable=True)
    login_time = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    logout_time = Column(DateTime(timezone=True), nullable=True)
    device_information = Column(String(200), nullable=True)
    platform = Column(String(40), nullable=True)
    ip_address = Column(String(64), nullable=True)
    login_status = Column(String(24), nullable=False, default="success")


class OtpChallenge(Base):
    """Present so verification can be switched on with REQUIRE_OTP=true and an
    SMS provider, without a schema change. Codes are hashed, never stored."""
    __tablename__ = "otp_challenges"
    id = Column(String(36), primary_key=True, default=new_id)
    mobile_number = Column(String(20), nullable=False, index=True)
    code_hash = Column(String(64), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class RateLimit(Base):
    __tablename__ = "rate_limits"
    bucket = Column(String(160), primary_key=True)
    window_start = Column(DateTime(timezone=True), nullable=False)
    count = Column(Integer, nullable=False, default=0)


# ---------------------------------------------------------------- synced data

class Group(Base):
    __tablename__ = "groups"
    id = Column(String(64), primary_key=True)          # created on the phone
    name = Column(String(160), nullable=False)
    currency = Column(String(3), nullable=False, default="INR")
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    deleted = Column(Boolean, nullable=False, default=False)
    seq = Column(BigInteger, nullable=False, default=0, index=True)

    members = relationship("GroupMember", back_populates="group", lazy="selectin")


class GroupMember(Base):
    """A person in a group. `phone_e164` is what links a member to an account:
    whoever signs in with that number gets the group. `user_id` is filled in
    once that match happens."""
    __tablename__ = "group_members"
    id = Column(String(64), primary_key=True)
    group_id = Column(String(64), ForeignKey("groups.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    phone_e164 = Column(String(20), nullable=True, index=True)
    name = Column(String(120), nullable=False)
    role = Column(String(16), nullable=False, default="member")
    joined_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    deleted = Column(Boolean, nullable=False, default=False)
    seq = Column(BigInteger, nullable=False, default=0, index=True)

    group = relationship("Group", back_populates="members")

    __table_args__ = (Index("ix_member_group_phone", "group_id", "phone_e164"),)


class GroupHidden(Base):
    """One person has removed a group from their own view.

    This is NOT a deletion. The group carries on for everyone else, this
    person stays in it, and their share of every expense still counts. It is
    the difference the data model previously could not express: `Group.deleted`
    means gone for everybody, and this means gone for one account.

    It lives here rather than only on the phone so that it survives a
    reinstall, and so a second device belonging to the same person agrees. It
    is never sent to anybody else — the pull returns each account only its own
    list — because the whole point is that nobody is told.
    """
    __tablename__ = "group_hidden"
    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    group_id = Column(String(64), ForeignKey("groups.id"), primary_key=True)
    hidden_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Expense(Base):
    __tablename__ = "expenses"
    id = Column(String(64), primary_key=True)
    group_id = Column(String(64), ForeignKey("groups.id"), nullable=False, index=True)
    description = Column(String(300), nullable=False)
    amount_minor = Column(BigInteger, nullable=False)       # paise/cents, integer
    currency = Column(String(3), nullable=False, default="INR")
    category = Column(String(60), nullable=False, default="Other")
    expense_date = Column(String(10), nullable=False)        # YYYY-MM-DD
    split_type = Column(String(20), nullable=False, default="equal")
    paid_by = Column(String(64), nullable=True)              # member id
    payers_json = Column(Text, nullable=False, default="{}")  # {member_id: minor}
    splits_json = Column(Text, nullable=False, default="{}")  # {member_id: minor}
    values_json = Column(Text, nullable=False, default="{}")  # raw split inputs
    created_by = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    deleted = Column(Boolean, nullable=False, default=False)
    seq = Column(BigInteger, nullable=False, default=0, index=True)


class Settlement(Base):
    __tablename__ = "settlements"
    id = Column(String(64), primary_key=True)
    group_id = Column(String(64), ForeignKey("groups.id"), nullable=False, index=True)
    from_member = Column(String(64), nullable=False)
    to_member = Column(String(64), nullable=False)
    amount_minor = Column(BigInteger, nullable=False)
    currency = Column(String(3), nullable=False, default="INR")
    method = Column(String(40), nullable=True)
    note = Column(String(300), nullable=True)
    settled_date = Column(String(10), nullable=False)
    created_by = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    deleted = Column(Boolean, nullable=False, default=False)
    seq = Column(BigInteger, nullable=False, default=0, index=True)


__all__ = [
    "Base", "Counter", "User", "Session", "LoginHistory", "OtpChallenge",
    "RateLimit", "Group", "GroupMember", "GroupHidden", "Expense", "Settlement",
    "new_id", "utcnow",
]
