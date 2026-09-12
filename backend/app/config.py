"""Configuration. Everything comes from the environment; nothing is hardcoded."""
import os
from functools import lru_cache


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


class Settings:
    def __init__(self) -> None:
        # postgresql+asyncpg://user:pass@host/db in production.
        # sqlite+aiosqlite:// is used by the test suite.
        self.database_url: str = os.getenv(
            "DATABASE_URL", "sqlite+aiosqlite:///./split_ledger.db"
        )

        # Identity
        self.default_country_code: str = os.getenv("DEFAULT_COUNTRY_CODE", "+91")

        # Sessions
        self.access_token_minutes: int = _int("ACCESS_TOKEN_MINUTES", 60)
        self.refresh_token_days: int = _int("REFRESH_TOKEN_DAYS", 30)

        # OTP. REQUIRE_OTP is the switch that turns verification on. It is off
        # for now by deliberate choice: sign-in is mobile number + name only,
        # which means anyone who types a number becomes that person. Turning it
        # on needs no code change, only an SMS provider below.
        self.require_otp: bool = _bool("REQUIRE_OTP", False)
        self.otp_length: int = _int("OTP_LENGTH", 4)
        self.otp_expiry_minutes: int = _int("OTP_EXPIRY_MINUTES", 5)
        self.otp_max_attempts: int = _int("OTP_MAX_ATTEMPTS", 5)
        self.otp_resend_cooldown_seconds: int = _int("OTP_RESEND_COOLDOWN_SECONDS", 30)

        # SMS provider. "console" logs the code instead of sending it.
        self.sms_provider: str = os.getenv("SMS_PROVIDER", "console")
        self.sms_api_key: str = os.getenv("SMS_API_KEY", "")
        self.sms_api_secret: str = os.getenv("SMS_API_SECRET", "")
        self.sms_sender_id: str = os.getenv("SMS_SENDER_ID", "")

        # Rate limits (requests per window, seconds)
        self.rl_auth_per_number: int = _int("RL_AUTH_PER_NUMBER", 10)
        self.rl_auth_per_number_window: int = _int("RL_AUTH_PER_NUMBER_WINDOW", 3600)
        self.rl_auth_per_ip: int = _int("RL_AUTH_PER_IP", 30)
        self.rl_auth_per_ip_window: int = _int("RL_AUTH_PER_IP_WINDOW", 3600)
        self.rl_sync_per_user: int = _int("RL_SYNC_PER_USER", 600)
        self.rl_sync_per_user_window: int = _int("RL_SYNC_PER_USER_WINDOW", 3600)

        self.cors_origins: str = os.getenv("CORS_ORIGINS", "*")
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")


@lru_cache
def get_settings() -> Settings:
    return Settings()
