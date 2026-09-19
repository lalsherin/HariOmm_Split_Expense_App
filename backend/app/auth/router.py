"""Auth endpoints."""
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..deps import current_user
from ..middleware.rate_limit import client_ip, enforce
from ..models import OtpChallenge, User, new_id, utcnow
from ..phone import InvalidPhoneNumber, normalise
from ..schemas import (
    RefreshRequest, RequestOtpRequest, SignInRequest, SignInResponse,
    SimpleResponse, UserOut,
)
from ..security import as_aware, check_otp, hash_otp, in_minutes, new_otp
from . import service
from .otp_service import OTPService

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
otp_service = OTPService(settings)


def _normalise_or_400(raw: str) -> str:
    try:
        return normalise(raw, settings.default_country_code)
    except InvalidPhoneNumber as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


async def _limit_auth(db: AsyncSession, request: Request, mobile: str) -> None:
    await enforce(db, f"auth:num:{mobile}", settings.rl_auth_per_number,
                  settings.rl_auth_per_number_window)
    await enforce(db, f"auth:ip:{client_ip(request)}", settings.rl_auth_per_ip,
                  settings.rl_auth_per_ip_window)


@router.post("/request-otp", response_model=dict)
async def request_otp(
    body: RequestOtpRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    """Send a verification code.

    Only meaningful when REQUIRE_OTP is on. The response never says whether
    the number already has an account (spec section 10).
    """
    mobile = _normalise_or_400(body.mobile_number)
    await _limit_auth(db, request, mobile)

    if not settings.require_otp:
        await db.commit()
        return {"success": True, "message": "Verification is turned off on this server.",
                "otp_required": False}

    recent = await db.scalar(
        select(OtpChallenge)
        .where(OtpChallenge.mobile_number == mobile, OtpChallenge.consumed_at.is_(None))
        .order_by(OtpChallenge.created_at.desc())
    )
    if recent is not None:
        age = (utcnow() - as_aware(recent.created_at)).total_seconds()
        if age < settings.otp_resend_cooldown_seconds:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Wait {int(settings.otp_resend_cooldown_seconds - age)}s before asking for another code.",
            )
        recent.consumed_at = utcnow()      # supersede it; only one live code

    code = new_otp(settings.otp_length)
    db.add(OtpChallenge(
        id=new_id(),
        mobile_number=mobile,
        code_hash=hash_otp(code, mobile),
        expires_at=in_minutes(settings.otp_expiry_minutes),
    ))
    otp_service.deliver(mobile, code)
    await db.commit()

    out = {"success": True, "message": "Verification code sent successfully.",
           "otp_required": True}
    if otp_service.echo_codes:
        out["dev_otp"] = code            # console provider only
    return out


@router.post("/sign-in", response_model=SignInResponse)
async def sign_in(
    body: SignInRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    """Register or log in. One endpoint for both, as the spec asks.

    With REQUIRE_OTP off this trusts the number as given — that is the
    documented, chosen trade-off for this deployment.
    """
    mobile = _normalise_or_400(body.mobile_number)
    await _limit_auth(db, request, mobile)
    ip = client_ip(request)

    if settings.require_otp:
        if not body.otp:
            await service.record_login(db, None, mobile, ip, body.device_information,
                                       body.platform, "otp_missing")
            await db.commit()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter the verification code.")

        challenge = await db.scalar(
            select(OtpChallenge)
            .where(OtpChallenge.mobile_number == mobile, OtpChallenge.consumed_at.is_(None))
            .order_by(OtpChallenge.created_at.desc())
        )
        if challenge is None or as_aware(challenge.expires_at) < utcnow():
            await service.record_login(db, None, mobile, ip, body.device_information,
                                       body.platform, "otp_expired")
            await db.commit()
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "That code has expired. Ask for a new one.")

        if challenge.attempts >= settings.otp_max_attempts:
            challenge.consumed_at = utcnow()
            await service.record_login(db, None, mobile, ip, body.device_information,
                                       body.platform, "otp_attempts_exceeded")
            await db.commit()
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                "Too many wrong codes. Ask for a new one.")

        if not check_otp(body.otp, mobile, challenge.code_hash):
            challenge.attempts += 1
            await service.record_login(db, None, mobile, ip, body.device_information,
                                       body.platform, "otp_wrong")
            await db.commit()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "That code isn't right.")

        challenge.consumed_at = utcnow()        # one-time use, immediately

    user, created = await service.register_or_login(db, mobile, body.name)
    if settings.require_otp and not user.mobile_verified:
        user.mobile_verified = True
    # Signing in is the one moment the build is guaranteed to be reported,
    # since a session lasts 30 days and a phone may not sign in again for
    # weeks. Every authenticated request refreshes it after that.
    version = request.headers.get("x-app-version")
    if version:
        user.app_version = str(version).strip()[:20]
    user.last_seen_at = utcnow()

    await service.claim_memberships(db, user)
    access, refresh, _ = await service.issue_session(
        db, user, settings, body.device_information, body.platform
    )
    await service.record_login(db, user, mobile, ip, body.device_information,
                               body.platform, "success")
    await db.commit()

    return SignInResponse(
        access_token=access,
        refresh_token=refresh,
        access_expires_in=settings.access_token_minutes * 60,
        user=UserOut.model_validate(user),
        created=created,
    )


@router.post("/refresh-token", response_model=SignInResponse)
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    result = await service.rotate_session(db, body.refresh_token, settings)
    await db.commit()
    if result is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in again.")
    access, refresh, user = result
    return SignInResponse(
        access_token=access,
        refresh_token=refresh,
        access_expires_in=settings.access_token_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/logout", response_model=SimpleResponse)
async def logout(authorization: str = Header(None), db: AsyncSession = Depends(get_db)):
    if authorization and authorization.lower().startswith("bearer "):
        await service.revoke_by_access(db, authorization.split(" ", 1)[1].strip())
        await db.commit()
    return SimpleResponse(message="Signed out.")


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return UserOut.model_validate(user)
