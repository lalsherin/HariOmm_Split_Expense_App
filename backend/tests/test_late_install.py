"""Being added to a group before you have the app.

The rule: membership belongs to the mobile number, held on the server. When
someone installs weeks later and signs in with that number, every group they
are currently in is theirs at once. Nothing about it depends on when they
installed, on anything stored on their phone, or on the person who added them
being online.

Every test here starts the late joiner on a brand-new "phone": cursor 0,
nothing local, a first sign-in. `group_ids` is the server's complete answer to
"which groups am I in right now?", added in 3.9.
"""
import asyncio
import os
import pathlib
import socket
import subprocess
import sys
import time

import httpx
import pytest

pytestmark = pytest.mark.asyncio

ASHA, BALA, CHITRA, DEV = "9876511001", "9876511002", "9876511003", "9876511004"
E164 = {n: "+91" + n for n in (ASHA, BALA, CHITRA, DEV)}


def grp(gid, name, **kw):
    return {"id": gid, "name": name, "currency": "INR", "deleted": False, **kw}


def mem(gid, mid, name, phone=None, **kw):
    return {"id": mid, "group_id": gid, "name": name, "phone": phone,
            "role": "member", "deleted": False, **kw}


def exp(gid, eid, desc, amount, paid_by, **kw):
    return {"id": eid, "group_id": gid, "description": desc, "amount_minor": amount,
            "currency": "INR", "category": "Food & drink", "expense_date": "2026-10-01",
            "split_type": "equal", "paid_by": paid_by, "payers": {paid_by: amount},
            "splits": {paid_by: amount}, "values": {}, "deleted": False, **kw}


def live(body):
    """What the app would show: groups that are not deleted, not removed from
    this account's view, and that the account is in."""
    ids = set(body["group_ids"])
    return sorted(g["name"] for g in body["groups"]
                  if not g["deleted"] and g["id"] in ids and g["id"] not in body["hidden"])


async def signed_in(phone, number, name):
    p = phone(number, name)
    await p.sign_in()
    return p


async def make_group(owner, gid, name, others=()):
    """Owner creates a group with themselves plus `others` [(mid, name, number)]."""
    members = [mem(gid, f"m-{gid}-owner", owner.name, owner.number)]
    members += [mem(gid, mid, n, num) for mid, n, num in others]
    out = await owner.sync(groups=[grp(gid, name)], members=members)
    assert not out["rejected"], out["rejected"]


# --- Test 1: the exact scenario --------------------------------------------


async def test_1_added_before_installing_then_signs_in(phone):
    """Asha makes Goa Trip and adds Bala's number. Bala has no account, no
    session, no device. Later Bala installs and signs in with that number,
    typed differently — and Goa Trip is there on the first sync."""
    asha = await signed_in(phone, ASHA, "Asha")
    await make_group(asha, "g-goa", "Goa Trip", [("m-bala", "Bala", "98765 11002")])
    await asha.sync(expenses=[exp("g-goa", "e1", "Villa", 900000, "m-g-goa-owner")])

    bala = phone("+91 98765 11002", "Bala")          # first install
    body = await bala.sign_in()
    assert body["created"] is True, "Bala had no account before"
    got = await bala.sync()

    assert live(got) == ["Goa Trip"]
    assert got["group_ids"] == ["g-goa"]
    assert [e["description"] for e in got["expenses"]] == ["Villa"]
    rows = [m for m in got["members"] if m["phone"] == E164[BALA]]
    assert len(rows) == 1, "the placeholder was linked, not duplicated"
    assert rows[0]["user_id"] == bala.user["id"]
    assert rows[0]["id"] == "m-bala"

    # Safe to repeat: sign in again, sync again, sync from scratch again.
    await bala.sign_in()
    again = await bala.sync()
    assert again["group_ids"] == ["g-goa"] and again["rejected"] == []
    bala.seq = 0
    full = await bala.sync()
    assert live(full) == ["Goa Trip"]
    assert len([m for m in full["members"] if m["phone"] == E164[BALA]]) == 1


async def test_1b_one_account_per_number_however_it_is_typed(phone, client):
    for spelling in ("+91 98765 11002", "098765 11002", "9876511002", "+919876511002"):
        p = phone(spelling, "Bala")
        await p.sign_in()
        assert p.user["mobile_number"] == E164[BALA]
    from app.database import SessionLocal
    from app.models import User
    from sqlalchemy import func, select
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 1


# --- Test 2: several groups -------------------------------------------------


async def test_2_four_groups_before_installing_all_arrive(phone):
    asha = await signed_in(phone, ASHA, "Asha")
    names = {"g-goa": "Goa Trip", "g-chennai": "Chennai Trip",
             "g-family": "Family Expenses", "g-office": "Office Dinner"}
    for gid, name in names.items():
        await make_group(asha, gid, name, [(f"m-bala-{gid}", "Bala", E164[BALA])])

    bala = await signed_in(phone, BALA, "Bala")
    got = await bala.sync()
    assert live(got) == sorted(names.values())
    assert sorted(got["group_ids"]) == sorted(names)


# --- Test 3: only your own groups --------------------------------------------


async def test_3_membership_decides_not_everything(phone):
    """A: Asha, Bala, Chitra.  B: Bala, Dev.  C: Chitra, Dev.
    Bala installs last and gets A and B, never C."""
    asha = await signed_in(phone, ASHA, "Asha")
    dev = await signed_in(phone, DEV, "Dev")
    await make_group(asha, "g-a", "Group A",
                     [("m-a-bala", "Bala", E164[BALA]), ("m-a-chitra", "Chitra", E164[CHITRA])])
    await make_group(dev, "g-b", "Group B", [("m-b-bala", "Bala", E164[BALA])])
    await make_group(dev, "g-c", "Group C", [("m-c-chitra", "Chitra", E164[CHITRA])])
    await dev.sync(expenses=[exp("g-c", "e-c", "Secret", 100, "m-g-c-owner")])

    bala = await signed_in(phone, BALA, "Bala")
    got = await bala.sync()
    assert live(got) == ["Group A", "Group B"]
    assert sorted(got["group_ids"]) == ["g-a", "g-b"]
    assert all(e["group_id"] != "g-c" for e in got["expenses"])
    assert all(m["group_id"] != "g-c" for m in got["members"])

    # and cannot reach in by writing to it either
    out = await bala.sync(expenses=[exp("g-c", "e-x", "Sneaky", 1, "m-c-chitra")])
    assert out["rejected"] == [{"kind": "expense", "id": "e-x", "reason": "not_a_member"}]


# --- Test 4: persisted, not remembered: a real server, restarted -----------


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_server(db_url, port):
    env = dict(os.environ, DATABASE_URL=db_url, REQUIRE_OTP="false",
               RL_AUTH_PER_NUMBER="1000", RL_AUTH_PER_IP="1000", RL_SYNC_PER_USER="10000")
    env.pop("DB_POOL", None)
    root = pathlib.Path(__file__).resolve().parents[1]
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port),
         "--log-level", "warning"],
        cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    proc.kill()
    raise RuntimeError("server did not start")


def _sign_in(base, number, name):
    r = httpx.post(f"{base}/auth/sign-in", json={"mobile_number": number, "name": name})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _sync(base, token, since=0, **changes):
    body = {"since": since, "wait": 0, "changes": {
        k: changes.get(k, []) for k in ("groups", "members", "expenses", "settlements", "hidden")}}
    r = httpx.post(f"{base}/sync", json=body, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()


async def test_4_membership_survives_a_server_restart(tmp_path):
    """Asha adds Bala; the server process is stopped (as Render does when it
    sleeps or redeploys) and a new one started on the same database; Bala
    signs in for the first time and gets the group. Nothing was held in
    memory. Uses TEST_DATABASE_URL (real Postgres) when that is set."""
    db_url = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path}/restart.db"
    port = _free_port()
    base = f"http://127.0.0.1:{port}"

    def run():
        proc = _start_server(db_url, port)
        try:
            asha = _sign_in(base, "+919876519001", "Asha")
            out = _sync(base, asha, groups=[grp("g-restart", "Goa Trip")], members=[
                mem("g-restart", "m-r-asha", "Asha", "+919876519001"),
                mem("g-restart", "m-r-bala", "Bala", "98765 19002")])
            assert not out["rejected"]
        finally:
            proc.terminate()
            proc.wait(10)

        proc = _start_server(db_url, port)          # a different process
        try:
            bala = _sign_in(base, "+919876519002", "Bala")
            got = _sync(base, bala)
            return live(got)
        finally:
            proc.terminate()
            proc.wait(10)

    assert await asyncio.to_thread(run) == ["Goa Trip"]


# --- Tests 5 and 6: the current state decides, not the history --------------


async def test_5_group_deleted_before_installing_does_not_appear(phone):
    asha = await signed_in(phone, ASHA, "Asha")
    await make_group(asha, "g-x", "Group X", [("m-x-bala", "Bala", E164[BALA])])
    await asha.sync(groups=[grp("g-x", "Group X", deleted=True,
                                updated_at="2027-01-01T00:00:00+00:00")])

    bala = await signed_in(phone, BALA, "Bala")
    got = await bala.sync()
    assert live(got) == []
    # The tombstone is sent, so a phone that already had it learns it is gone.
    assert all(g["deleted"] for g in got["groups"])


async def test_6_removed_before_installing_does_not_appear(phone):
    asha = await signed_in(phone, ASHA, "Asha")
    await make_group(asha, "g-x", "Group X", [("m-x-bala", "Bala", E164[BALA])])
    await asha.sync(members=[mem("g-x", "m-x-bala", "Bala", E164[BALA], deleted=True,
                                updated_at="2027-01-01T00:00:00+00:00")])

    bala = await signed_in(phone, BALA, "Bala")
    got = await bala.sync()
    assert got["group_ids"] == []
    assert got["groups"] == [] and got["expenses"] == []


# --- Tests 7, 8, 9: removing it from your own view sticks -------------------


async def _bala_has_group_x(phone):
    asha = await signed_in(phone, ASHA, "Asha")
    await make_group(asha, "g-x", "Group X", [("m-x-bala", "Bala", E164[BALA])])
    bala = await signed_in(phone, BALA, "Bala")
    assert live(await bala.sync()) == ["Group X"]
    return asha, bala


async def test_7_removed_from_view_stays_hidden_across_syncs(phone):
    asha, bala = await _bala_has_group_x(phone)
    out = await bala.sync(hidden=[{"group_id": "g-x", "hidden": True}])
    assert live(out) == []
    for _ in range(3):
        again = await bala.sync()
        assert live(again) == [] and again["hidden"] == ["g-x"]
    # still a member: hiding is not leaving
    assert again["group_ids"] == ["g-x"]


async def test_8_another_group_does_not_bring_it_back(phone):
    asha, bala = await _bala_has_group_x(phone)
    await bala.sync(hidden=[{"group_id": "g-x", "hidden": True}])
    await make_group(bala, "g-y", "Group Y", [("m-y-asha", "Asha", E164[ASHA])])
    await make_group(asha, "g-z", "Group Z", [("m-z-bala", "Bala", E164[BALA])])
    got = await bala.sync()
    bala.seq = 0
    full = await bala.sync()
    assert live(full) == ["Group Y", "Group Z"]


async def test_9_still_hidden_after_a_restart_or_reinstall(phone):
    asha, bala = await _bala_has_group_x(phone)
    await bala.sync(hidden=[{"group_id": "g-x", "hidden": True}])
    fresh = phone(BALA, "Bala")                       # app data cleared / new phone
    await fresh.sign_in()
    got = await fresh.sync()
    assert got["hidden"] == ["g-x"]
    assert live(got) == []


# --- Test 10 and the owner re-add cycle ------------------------------------


async def test_10_removed_then_added_back_is_visible_again(phone):
    """Added, sees it; removed, it leaves the list; added back, it returns —
    with what was written while Bala was out, which is older than Bala's
    cursor and so only reachable because group_ids says to ask again."""
    asha, bala = await _bala_has_group_x(phone)

    await asha.sync(members=[mem("g-x", "m-x-bala", "Bala", E164[BALA], deleted=True,
                                updated_at="2027-01-01T00:00:00+00:00")])
    gone = await bala.sync()
    assert gone["group_ids"] == [], "the removed member is told, by omission"

    await asha.sync(expenses=[exp("g-x", "e-out", "While Bala was out", 5000, "m-g-x-owner")])
    # Activity in another of Bala's groups moves Bala's cursor past it.
    await make_group(asha, "g-other", "Another trip", [("m-o-bala", "Bala", E164[BALA])])
    await bala.sync()

    await asha.sync(members=[mem("g-x", "m-x-bala-2", "Bala", E164[BALA],
                                updated_at="2027-01-02T00:00:00+00:00")])
    back = await bala.sync()
    assert back["group_ids"] == ["g-other", "g-x"]
    assert all(e["id"] != "e-out" for e in back["expenses"]), \
        "the delta alone misses it — which is why the phone re-asks in full"
    bala.seq = 0
    full = await bala.sync()
    assert live(full) == ["Another trip", "Group X"]
    assert "e-out" in {e["id"] for e in full["expenses"]}


async def test_10b_added_back_after_hiding_clears_the_hide(phone):
    asha, bala = await _bala_has_group_x(phone)
    await bala.sync(hidden=[{"group_id": "g-x", "hidden": True}])
    await asha.sync(members=[mem("g-x", "m-x-bala", "Bala", E164[BALA], deleted=True,
                                updated_at="2027-01-01T00:00:00+00:00")])
    await asha.sync(members=[mem("g-x", "m-x-bala-2", "Bala", E164[BALA],
                                updated_at="2027-01-02T00:00:00+00:00")])
    bala.seq = 0
    got = await bala.sync()
    assert got["hidden"] == [] and live(got) == ["Group X"]


# --- identity and security --------------------------------------------------


async def test_changing_a_members_number_moves_the_group_to_the_new_number(phone):
    """The number is the identity. Correcting Bala's number to Chitra's takes
    the group away from Bala — even before Chitra has an account."""
    asha, bala = await _bala_has_group_x(phone)
    await asha.sync(members=[mem("g-x", "m-x-bala", "Chitra", E164[CHITRA],
                                updated_at="2027-01-01T00:00:00+00:00")])
    assert (await bala.sync())["group_ids"] == []

    chitra = await signed_in(phone, CHITRA, "Chitra")
    assert live(await chitra.sync()) == ["Group X"]


async def test_logging_out_and_in_again_keeps_the_groups(phone, client):
    asha, bala = await _bala_has_group_x(phone)
    r = await client.post("/auth/logout", headers=bala.headers)
    assert r.status_code == 200
    r = await client.post("/sync", json={"since": 0, "changes": {}}, headers=bala.headers)
    assert r.status_code == 401, "the old session is gone"
    await bala.sign_in()
    bala.seq = 0
    assert live(await bala.sync()) == ["Group X"]


async def test_a_waiting_phone_hears_promptly_that_it_was_removed(phone):
    """Bala's app is open and holding a request. Being removed changes no row
    Bala can see, so before 3.9 the hold ran out its full 15s; now the change
    in group_ids ends it."""
    asha, bala = await _bala_has_group_x(phone)
    await bala.sync()

    async def remove_soon():
        await asyncio.sleep(1.0)
        await asha.sync(members=[mem("g-x", "m-x-bala", "Bala", E164[BALA], deleted=True,
                                    updated_at="2027-01-01T00:00:00+00:00")])

    started = asyncio.get_event_loop().time()
    task = asyncio.create_task(remove_soon())
    got = await bala.sync(wait=12)
    await task
    took = asyncio.get_event_loop().time() - started
    assert got["group_ids"] == []
    assert took < 6, f"held for {took:.1f}s after the removal"


async def test_a_removal_before_the_wait_began_is_still_reported_at_once(phone):
    """The removal lands between two of Bala's requests. The next request must
    not be held — the phone has not heard yet — and after it has been told,
    the one after that waits normally instead of spinning."""
    asha, bala = await _bala_has_group_x(phone)
    await bala.sync()
    await asha.sync(members=[mem("g-x", "m-x-bala", "Bala", E164[BALA], deleted=True,
                                updated_at="2027-01-01T00:00:00+00:00")])
    t = asyncio.get_event_loop().time()
    got = await bala.sync(wait=5)
    assert asyncio.get_event_loop().time() - t < 2, "held although the phone had not been told"
    assert got["group_ids"] == []
    t = asyncio.get_event_loop().time()
    await bala.sync(wait=2)
    assert asyncio.get_event_loop().time() - t >= 1.5, "reported the same change twice"
