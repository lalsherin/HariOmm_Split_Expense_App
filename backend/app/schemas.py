"""Request and response shapes. Pydantic rejects anything malformed before it
reaches a handler."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ------------------------------------------------------------------- auth
class SignInRequest(BaseModel):
    mobile_number: str = Field(..., max_length=24)
    name: Optional[str] = Field(None, max_length=120)
    otp: Optional[str] = Field(None, max_length=8)
    device_information: Optional[str] = Field(None, max_length=200)
    platform: Optional[str] = Field(None, max_length=40)


class RequestOtpRequest(BaseModel):
    mobile_number: str = Field(..., max_length=24)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., max_length=200)


class UserOut(BaseModel):
    """One account's own record. Returned to that account and nowhere else —
    there is no endpoint anywhere that lists users or returns somebody else's
    row, and adding one would hand out a list of mobile numbers."""
    model_config = ConfigDict(from_attributes=True)
    id: str
    mobile_number: str
    name: str
    mobile_verified: bool
    account_status: str
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    app_version: Optional[str] = None


class SignInResponse(BaseModel):
    success: bool = True
    access_token: str
    refresh_token: str
    access_expires_in: int
    user: UserOut
    created: bool = False


class SimpleResponse(BaseModel):
    success: bool = True
    message: str = ""


# ------------------------------------------------------------------- sync
class GroupIn(BaseModel):
    id: str = Field(..., max_length=64)
    name: str = Field(..., max_length=160)
    currency: str = Field("INR", max_length=3)
    deleted: bool = False
    updated_at: Optional[str] = None


class MemberIn(BaseModel):
    id: str = Field(..., max_length=64)
    group_id: str = Field(..., max_length=64)
    name: str = Field(..., max_length=120)
    phone: Optional[str] = Field(None, max_length=24)
    role: str = Field("member", max_length=16)
    deleted: bool = False
    updated_at: Optional[str] = None


class ExpenseIn(BaseModel):
    id: str = Field(..., max_length=64)
    group_id: str = Field(..., max_length=64)
    description: str = Field(..., max_length=300)
    amount_minor: int = Field(..., ge=0)
    currency: str = Field("INR", max_length=3)
    category: str = Field("Other", max_length=60)
    expense_date: str = Field(..., max_length=10)
    split_type: str = Field("equal", max_length=20)
    paid_by: Optional[str] = Field(None, max_length=64)
    payers: Dict[str, int] = Field(default_factory=dict)
    splits: Dict[str, int] = Field(default_factory=dict)
    values: Dict[str, Any] = Field(default_factory=dict)
    deleted: bool = False
    updated_at: Optional[str] = None


class SettlementIn(BaseModel):
    id: str = Field(..., max_length=64)
    group_id: str = Field(..., max_length=64)
    from_member: str = Field(..., max_length=64)
    to_member: str = Field(..., max_length=64)
    amount_minor: int = Field(..., ge=0)
    currency: str = Field("INR", max_length=3)
    method: Optional[str] = Field(None, max_length=40)
    note: Optional[str] = Field(None, max_length=300)
    settled_date: str = Field(..., max_length=10)
    deleted: bool = False
    updated_at: Optional[str] = None


class HiddenIn(BaseModel):
    """One account removing a group from its own view, or putting it back."""
    group_id: str = Field(..., max_length=64)
    hidden: bool = True


class SyncChanges(BaseModel):
    groups: List[GroupIn] = Field(default_factory=list)
    members: List[MemberIn] = Field(default_factory=list)
    expenses: List[ExpenseIn] = Field(default_factory=list)
    settlements: List[SettlementIn] = Field(default_factory=list)
    hidden: List[HiddenIn] = Field(default_factory=list)


class SyncRequest(BaseModel):
    since: int = 0
    changes: SyncChanges = Field(default_factory=SyncChanges)
    # Seconds to hold the request open when there is nothing new yet, so a
    # phone with the app on screen hears about a change within about a second
    # instead of on its next poll. 0 answers immediately, as before.
    wait: int = 0


class SyncResponse(BaseModel):
    success: bool = True
    seq: int
    groups: List[Dict[str, Any]] = Field(default_factory=list)
    members: List[Dict[str, Any]] = Field(default_factory=list)
    expenses: List[Dict[str, Any]] = Field(default_factory=list)
    settlements: List[Dict[str, Any]] = Field(default_factory=list)
    rejected: List[Dict[str, Any]] = Field(default_factory=list)
    # Every group THIS account has removed from its own view, in full rather
    # than as a delta — there are only ever a handful, and a complete list is
    # something the phone can simply adopt instead of having to reconcile.
    hidden: List[str] = Field(default_factory=list)
