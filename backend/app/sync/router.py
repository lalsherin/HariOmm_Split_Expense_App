"""Sync endpoint."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..deps import current_user
from ..middleware.rate_limit import enforce
from ..models import User
from ..schemas import SyncRequest, SyncResponse
from . import service

router = APIRouter(prefix="/sync", tags=["sync"])
settings = get_settings()


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
    return SyncResponse(rejected=rejected, **out)
