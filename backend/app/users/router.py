"""User-facing reads. Deliberately thin: another member's phone number is
never returned outside the groups you share with them."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import current_user
from ..models import LoginHistory, User
from ..schemas import UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return UserOut.model_validate(user)


@router.get("/me/logins")
async def my_logins(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(
        select(LoginHistory).where(LoginHistory.user_id == user.id)
        .order_by(LoginHistory.login_time.desc()).limit(50)
    )).all()
    return {"success": True, "logins": [{
        "login_time": r.login_time.isoformat() if r.login_time else None,
        "platform": r.platform, "device_information": r.device_information,
        "login_status": r.login_status,
    } for r in rows]}
