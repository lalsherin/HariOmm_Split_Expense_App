"""The user registry: one row per person, keyed by their mobile number.

The table already existed — this covers the promises it has to keep, and the
two columns added to it (`last_seen_at`, `app_version`) including the part
that is easy to get wrong: adding a column to a table that is already live.
"""
import asyncio

import pytest
from sqlalchemy import func, select, text

from app.database import SessionLocal, _ensure_columns
from app.models import LoginHistory, User

pytestmark = pytest.mark.asyncio


async def count_users(mobile=None) -> int:
    async with SessionLocal() as db:
        q = select(func.count()).select_from(User)
        if mobile:
            q = q.where(User.mobile_number == mobile)
        return int(await db.scalar(q) or 0)


async def load(mobile: str) -> User:
    async with SessionLocal() as db:
        return await db.scalar(select(User).where(User.mobile_number == mobile))


# --- 1. a new person ---------------------------------------------------------


async def test_a_new_number_creates_exactly_one_account(phone):
    sherin = phone("9876543210", "Sherin")
    body = await sherin.sign_in()

    assert await count_users() == 1
    row = await load("+919876543210")
    assert row.id == body["user"]["id"]
    assert row.name == "Sherin"
    assert row.account_status == "active"
    assert row.created_at is not None
    assert row.last_login_at is not None
    assert body["created"] is True


# --- 2 & 3. the same person again --------------------------------------------


async def test_signing_in_again_is_the_same_account(phone):
    sherin = phone("9876543210", "Sherin")
    first = await sherin.sign_in()
    before = (await load("+919876543210")).last_login_at

    await asyncio.sleep(1.1)                    # so a changed timestamp is visible
    second = await sherin.sign_in()

    assert second["user"]["id"] == first["user"]["id"]
    assert second["created"] is False
    assert await count_users() == 1
    after = (await load("+919876543210")).last_login_at
    assert after > before, "last_login_at was not moved on"


async def test_ten_logins_leave_one_row(phone):
    sherin = phone("9876543210", "Sherin")
    ids = set()
    for _ in range(10):
        ids.add((await sherin.sign_in())["user"]["id"])
    assert len(ids) == 1
    assert await count_users() == 1
    # every attempt is still recorded, which is a different table on purpose
    async with SessionLocal() as db:
        logins = int(await db.scalar(select(func.count()).select_from(LoginHistory)) or 0)
    assert logins == 10


async def test_the_same_number_written_three_ways_is_one_person(phone):
    """The failure this guards against is one person ending up with three
    accounts and none of their groups."""
    for spelling in ["+91 98765 43210", "+919876543210", "09876543210"]:
        p = phone(spelling, "Sherin")
        await p.sign_in()
    assert await count_users() == 1
    assert (await load("+919876543210")) is not None


# --- 4. different people ------------------------------------------------------


async def test_two_numbers_are_two_accounts(phone):
    a = phone("9876543210", "Sherin")
    b = phone("9876500002", "Anu")
    ra, rb = await a.sign_in(), await b.sign_in()
    assert ra["user"]["id"] != rb["user"]["id"]
    assert await count_users() == 2


# --- 5. authentication that fails must not create anybody --------------------


async def test_a_wrong_code_does_not_create_an_account(client, monkeypatch):
    """With verification on, a bad code must leave no trace in the registry —
    or anyone could populate it with numbers they do not own."""
    from app.auth import router as auth_router
    monkeypatch.setattr(auth_router.settings, "require_otp", True)

    r = await client.post("/auth/sign-in", json={
        "mobile_number": "9876543210", "name": "Not Sherin", "otp": "0000"})
    assert r.status_code >= 400
    assert "access_token" not in r.text
    assert await count_users() == 0

    r = await client.post("/auth/sign-in", json={
        "mobile_number": "9876543210", "name": "Not Sherin"})
    assert r.status_code >= 400
    assert await count_users() == 0


async def test_an_unusable_number_is_refused_before_anything_is_written(client):
    r = await client.post("/auth/sign-in", json={"mobile_number": "hello", "name": "X"})
    assert r.status_code == 400
    assert await count_users() == 0


# --- 6. the database is not available ----------------------------------------


async def test_a_failed_write_is_not_reported_as_a_successful_sign_in(client, monkeypatch):
    """The token is only issued after the row is committed. If the write
    fails, the caller must be told — not handed a session for an account that
    does not exist."""
    from app.auth import service as auth_service

    async def boom(*a, **kw):
        raise RuntimeError("database is away")

    monkeypatch.setattr(auth_service, "register_or_login", boom)
    with pytest.raises(RuntimeError):
        await client.post("/auth/sign-in", json={"mobile_number": "9876543210", "name": "S"})
    assert await count_users() == 0


# --- 7. one account cannot read another --------------------------------------


async def test_you_only_ever_get_your_own_record(phone, client):
    a = phone("9876543210", "Sherin")
    b = phone("9876500002", "Anu")
    ra, rb = await a.sign_in(), await b.sign_in()

    mine = await client.get("/users/me", headers=a.headers)
    assert mine.status_code == 200
    assert mine.json()["id"] == ra["user"]["id"]
    assert mine.json()["mobile_number"] == "+919876543210"

    theirs = await client.get("/users/me", headers=b.headers)
    assert theirs.json()["id"] == rb["user"]["id"]
    assert theirs.json()["mobile_number"] != "+919876543210"


async def test_there_is_no_endpoint_that_lists_everybody(client, phone):
    sherin = phone("9876543210", "Sherin")
    await sherin.sign_in()
    for path in ["/users", "/users/", "/users/all", "/auth/users"]:
        r = await client.get(path, headers=sherin.headers)
        assert r.status_code in (404, 405), f"{path} answered {r.status_code}"


async def test_the_record_needs_a_token(client):
    assert (await client.get("/users/me")).status_code == 401


# --- last seen, and which build they are on ----------------------------------


async def test_the_build_is_recorded_from_the_header(phone, client):
    sherin = phone("9876543210", "Sherin")
    await sherin.sign_in(headers={"X-App-Version": "3.5"})
    assert (await load("+919876543210")).app_version == "3.5"

    # and it follows them when they update, without signing in again
    await client.post("/sync", json={"since": 0, "changes": {}},
                      headers={**sherin.headers, "X-App-Version": "3.6"})
    assert (await load("+919876543210")).app_version == "3.6"


async def test_being_active_is_recorded_but_not_on_every_request(phone, client):
    """An app holding a sync request open makes hundreds of requests an hour.
    Each one must not be a database write."""
    sherin = phone("9876543210", "Sherin")
    await sherin.sign_in()
    first = (await load("+919876543210")).last_seen_at
    assert first is not None

    for _ in range(5):
        await client.post("/sync", json={"since": 0, "changes": {}}, headers=sherin.headers)
    assert (await load("+919876543210")).last_seen_at == first, \
        "last_seen_at is being written on every request"


async def test_it_does_move_once_it_is_stale(phone, client, monkeypatch):
    from app import deps
    monkeypatch.setattr(deps, "LAST_SEEN_EVERY", 0)       # everything is stale
    sherin = phone("9876543210", "Sherin")
    await sherin.sign_in()
    before = (await load("+919876543210")).last_seen_at
    await asyncio.sleep(1.1)
    await client.post("/sync", json={"since": 0, "changes": {}}, headers=sherin.headers)
    assert (await load("+919876543210")).last_seen_at > before


# --- adding a column to a table that already exists --------------------------


async def test_a_new_column_is_added_to_a_table_that_is_already_there():
    """`create_all` creates missing tables; it does not add missing columns.
    Without this step a new column would exist in the models, be named in
    every query, and not exist in the database — and every request would fail.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    import pathlib
    tmp = pathlib.Path("/tmp/colcheck.db")
    tmp.unlink(missing_ok=True)
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp}")
    try:
        async with eng.begin() as conn:
            # an older schema: users exists, without the two new columns
            await conn.execute(text(
                "CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, "
                "mobile_number VARCHAR(20), name VARCHAR(120))"))
            cols = {r[1] for r in await conn.execute(text("PRAGMA table_info(users)"))}
            assert "last_seen_at" not in cols and "app_version" not in cols

            await _ensure_columns(conn)
            cols = {r[1] for r in await conn.execute(text("PRAGMA table_info(users)"))}
            assert "last_seen_at" in cols and "app_version" in cols

            await _ensure_columns(conn)          # again: must be a no-op
            cols2 = {r[1] for r in await conn.execute(text("PRAGMA table_info(users)"))}
            assert cols2 == cols
    finally:
        await eng.dispose()
        tmp.unlink(missing_ok=True)
