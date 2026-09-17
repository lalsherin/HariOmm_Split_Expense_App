"""Configuration. Everything comes from the environment; nothing is hardcoded."""
import os
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters libpq understands and asyncpg does not. SQLAlchemy hands
# anything it does not recognise straight to asyncpg.connect() as a keyword
# argument, so leaving these in place fails at the first connection with a
# TypeError that says nothing about the real cause.
_LIBPQ_ONLY = {"channel_binding", "options", "target_session_attrs",
               "application_name", "connect_timeout", "sslrootcert"}
_TLS_OFF = {"disable", "allow", "false", "0", "off", "no"}


def normalise_database_url(raw: str) -> str:
    """Accept the connection string a host actually gives you.

    Neon, Render, Supabase and Heroku all print a psycopg-style URL:

        postgresql://user:pw@host/db?sslmode=require&channel_binding=require

    This server talks asyncpg, which uses a different driver name and rejects
    libpq's TLS parameters. Translating here means the URL can be pasted into
    the host's dashboard unedited, which is one fewer thing to get wrong at
    two in the morning.
    """
    if not raw:
        return raw
    url = raw.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    if not url.startswith("postgresql+asyncpg://"):
        return url                       # sqlite, or a driver already spelled out

    parts = urlsplit(url)
    keep, tls = [], False
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key in ("sslmode", "ssl"):
            tls = value.lower() not in _TLS_OFF
        elif key in _LIBPQ_ONLY:
            continue
        else:
            keep.append((key, value))
    if tls:
        keep.append(("ssl", "require"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(keep), parts.fragment))


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
        self.database_url: str = normalise_database_url(os.getenv(
            "DATABASE_URL", "sqlite+aiosqlite:///./split_ledger.db"
        ))

        # Identity
        self.default_country_code: str = os.getenv("DEFAULT_COUNTRY_CODE", "+91")

        # Sessions
        self.access_token_minutes: int = _int("ACCESS_TOKEN_MINUTES", 60)
        self.refresh_token_days: int = _int("REFRESH_TOKEN_DAYS", 30)

        # How long after a refresh token is spent a repeat of it is read as a
        # dropped reply rather than a stolen token.
        #
        # A phone gives up on a request after 20 seconds. A sleeping free-tier
        # instance takes 30-60 to wake. So a refresh can very easily be
        # processed here while the phone has already walked away, leaving it
        # holding a token this server considers spent. Without a grace window
        # the next attempt looks like theft, every session for that number is
        # revoked, and the phone is silently signed out for good.
        # Set to 0 to disable the grace window entirely.
        self.refresh_grace_seconds: int = _int("REFRESH_GRACE_SECONDS", 120)

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
