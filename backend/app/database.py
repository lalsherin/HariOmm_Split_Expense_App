"""Engine, session factory, and the global sync sequence."""
import os

from sqlalchemy import select, text, update
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings
from .models import Base, Counter

_settings = get_settings()

_connect_args = {}
if _settings.database_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

# Connection pooling. The default pool is right for Render + Neon direct.
#
# DB_POOL=null turns pooling off — one connection per checkout, closed after.
# Two reasons it exists: a pooler in transaction mode in front of the database
# wants it, and the test suite needs it, because pytest gives each test its own
# event loop while a pooled asyncpg connection belongs to the loop that opened
# it. Without this the suite cannot be run against real PostgreSQL at all, and
# "it passes on SQLite" is a weaker claim than it looks.
_pool_args = {}
if os.environ.get("DB_POOL", "").lower() == "null":
    _pool_args["poolclass"] = NullPool
else:
    _pool_args["pool_pre_ping"] = True

engine = create_async_engine(
    _settings.database_url,
    echo=False,
    connect_args=_connect_args,
    **_pool_args,
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# Columns added to tables that already exist in a live database.
#
# `create_all` creates missing TABLES. It does not add missing COLUMNS to a
# table that is already there, so a new column on `users` would exist in the
# models, be selected by every query, and not exist in Neon — every request
# would fail with UndefinedColumn. This closes that gap for the only kind of
# change it can close safely: adding a nullable column with no default, which
# in Postgres is a catalogue update and does not rewrite the table.
#
# Anything else — renaming, dropping, changing a type, backfilling — needs
# Alembic and a considered migration. This is a narrow tool, deliberately.
_ADDED_COLUMNS = [
    # table,   column,          postgres type,              sqlite type
    ("users", "last_seen_at", "TIMESTAMP WITH TIME ZONE", "TIMESTAMP"),
    ("users", "app_version",  "VARCHAR(20)",              "VARCHAR(20)"),
]


async def _ensure_columns(conn) -> None:
    dialect = conn.dialect.name
    for table, column, pg_type, lite_type in _ADDED_COLUMNS:
        if dialect == "postgresql":
            await conn.execute(text(
                f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{column}" {pg_type}'
            ))
            continue
        # SQLite has no ADD COLUMN IF NOT EXISTS: look first.
        rows = await conn.execute(text(f"PRAGMA table_info({table})"))
        if column in {r[1] for r in rows}:
            continue
        await conn.execute(text(
            f'ALTER TABLE "{table}" ADD COLUMN "{column}" {lite_type}'
        ))


async def init_db() -> None:
    """Create missing tables, then add any missing columns to existing ones.

    Both steps are idempotent and additive: nothing is dropped, nothing is
    rewritten, and running this against a database that is already correct is a
    no-op. Safe to run on every boot, which is exactly when it runs.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_columns(conn)
    async with SessionLocal() as db:
        row = await db.get(Counter, "sync")
        if row is None:
            db.add(Counter(name="sync", value=0))
            await db.commit()


async def next_seq(db: AsyncSession) -> int:
    """Claim the next global sync sequence number.

    Done as an UPDATE ... RETURNING-style read-after-write inside the caller's
    transaction so two concurrent writers cannot be handed the same number.
    """
    await db.execute(
        update(Counter).where(Counter.name == "sync").values(value=Counter.value + 1)
    )
    value = await db.scalar(select(Counter.value).where(Counter.name == "sync"))
    return int(value or 0)


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
