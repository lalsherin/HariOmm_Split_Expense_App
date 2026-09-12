import os
import pathlib
import sys

import pytest
import pytest_asyncio

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Must be set before the app is imported: config is cached and the engine is
# built at import time.
DB_FILE = ROOT / "test_split_ledger.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_FILE}"
os.environ["REQUIRE_OTP"] = "false"
os.environ["RL_AUTH_PER_NUMBER"] = "1000"
os.environ["RL_AUTH_PER_IP"] = "1000"
os.environ["RL_SYNC_PER_USER"] = "10000"

from httpx import ASGITransport, AsyncClient          # noqa: E402
from app.database import SessionLocal, engine          # noqa: E402
from app.main import app                               # noqa: E402
from app.models import Base, Counter                   # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def fresh_db():
    """Every test starts on an empty schema."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        db.add(Counter(name="sync", value=0))
        await db.commit()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def pytest_sessionfinish(session, exitstatus):
    try:
        DB_FILE.unlink(missing_ok=True)
    except OSError:
        pass


class Phone:
    """Signed-in test actor."""

    def __init__(self, client, number, name):
        self.client = client
        self.number = number
        self.name = name
        self.access = None
        self.refresh = None
        self.user = None
        self.seq = 0

    async def sign_in(self, **extra):
        r = await self.client.post("/auth/sign-in", json={
            "mobile_number": self.number, "name": self.name, **extra})
        assert r.status_code == 200, r.text
        body = r.json()
        self.access = body["access_token"]
        self.refresh = body["refresh_token"]
        self.user = body["user"]
        return body

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.access}"}

    async def sync(self, **changes):
        payload = {"since": self.seq, "changes": {
            "groups": changes.get("groups", []),
            "members": changes.get("members", []),
            "expenses": changes.get("expenses", []),
            "settlements": changes.get("settlements", []),
        }}
        r = await self.client.post("/sync", json=payload, headers=self.headers)
        assert r.status_code == 200, r.text
        body = r.json()
        self.seq = body["seq"]
        return body


@pytest.fixture
def phone(client):
    def make(number, name):
        return Phone(client, number, name)
    return make
