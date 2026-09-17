"""Engine, session factory, and the global sync sequence."""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings
from .models import Base, Counter

_settings = get_settings()

_connect_args = {}
if _settings.database_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_async_engine(
    _settings.database_url,
    echo=False,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create tables if they are missing.

    Fine for first deploy and for the test suite. A real change to a live
    schema wants Alembic; there are no migrations in this repo yet, which is
    called out in the README rather than pretended away.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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
