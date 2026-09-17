"""Split Ledger API."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth.router import router as auth_router
from .config import get_settings
from .database import init_db
from .middleware import errors
from .sync.router import router as sync_router
from .users.router import router as users_router

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

app = FastAPI(
    title="Split Ledger API",
    version="1.0.0",
    description="Mobile-number identity and cross-device sync for Split Ledger.",
)

# The Android app loads its page from file://, so its requests carry
# `Origin: null`. Credentials are sent as a bearer header, never as a cookie,
# so a wildcard origin does not expose anything to a hostile page.
_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

errors.install(app)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(sync_router)


@app.on_event("startup")
async def startup() -> None:
    await init_db()
    if not settings.require_otp:
        logging.getLogger("api").warning(
            "REQUIRE_OTP is off: anyone can sign in as any mobile number. "
            "Set REQUIRE_OTP=true and configure SMS_PROVIDER before this is public."
        )


@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok", "otp_required": settings.require_otp}
