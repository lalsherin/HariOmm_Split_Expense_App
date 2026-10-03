"""Invite links: making, checking, joining, revoking — and everything that must
NOT happen with one."""
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.database import SessionLocal
from app.models import GroupInvite, GroupMember
from app.security import hash_token, utcnow

pytestmark = pytest.mark.asyncio

GID = "g-appdev"
ASHA, BALA, CHITRA, DEV = "9876533001", "9876533002", "9876533003", "9876533004"


def grp(**kw):
    return {"id": GID, "name": "App development", "currency": "INR", "deleted": False, **kw}


def mem(mid, name, phone=None, **kw):
    return {"id": mid, "group_id": GID, "name": name, "phone": phone,
            "role": "member", "deleted": False, **kw}


def exp(eid, amount, paid_by):
    return {"id": eid, "group_id": GID, "description": "Hosting", "amount_minor": amount,
            "currency": "INR", "category": "Other", "expense_date": "2026-10-01",
            "split_type": "equal", "paid_by": paid_by, "payers": {paid_by: amount},
            "splits": {paid_by: amount}, "values": {}, "deleted": False}


async def signed_in(phone, number, name):
    p = phone(number, name)
    await p.sign_in()
    return p


async def post(client, p, path, body, ok=True):
    r = await client.post(path, json=body, headers=p.headers if p else {})
    if ok:
        assert r.status_code == 200, r.text
    return r


async def owner_with_group(phone, client, extra_members=()):
    asha = await signed_in(phone, ASHA, "Asha")
    await asha.sync(groups=[grp()], members=[mem("m-asha", "Asha", "+91" + ASHA), *extra_members],
                    expenses=[exp("e1", 635800, "m-asha")])
    return asha


async def make_link(client, p, gid=GID):
    return (await post(client, p, "/invites", {"group_id": gid})).json()


async def member_rows(number):
    async with SessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(GroupMember).where(
            GroupMember.group_id == GID, GroupMember.phone_e164 == "+91" + number,
            GroupMember.deleted.is_(False)))


# ------------------------------------------------------------------ the flow


async def test_owner_shares_friend_joins_and_the_group_appears(phone, client):
    asha = await owner_with_group(phone, client)
    link = await make_link(client, asha)
    token = link["token"]
    assert link["path"] == "/join/" + token
    assert GID not in token and len(token) >= 20

    bala = await signed_in(phone, BALA, "Bala")
    pv = (await post(client, bala, "/invites/preview", {"token": token})).json()
    assert pv["status"] == "ok"
    assert pv["group"] == {"name": "App development", "currency": "INR",
                           "members": 1, "total_minor": 635800}
    assert "group_id" not in pv, "the id is only handed over once you are in"
    assert (await bala.sync())["group_ids"] == [], "previewing joins nothing"

    out = (await post(client, bala, "/invites/accept", {"token": token})).json()
    assert out["status"] == "joined" and out["group_id"] == GID
    got = await bala.sync()
    assert got["group_ids"] == [GID]
    assert [g["name"] for g in got["groups"]] == ["App development"]
    assert len(got["expenses"]) == 1

    # Asha still owns it, her row is untouched, and she sees Bala arrive.
    seen = await asha.sync()
    assert seen["groups"] == [] or seen["groups"][0]["created_by"] == asha.user["id"]
    asha.seq = 0
    full = await asha.sync()
    assert full["groups"][0]["created_by"] == asha.user["id"]
    rows = {m["name"]: m for m in full["members"]}
    assert set(rows) == {"Asha", "Bala"}
    assert rows["Bala"]["user_id"] == bala.user["id"] and rows["Bala"]["phone"] == "+91" + BALA


async def test_late_install_friend_registers_then_joins(phone, client):
    asha = await owner_with_group(phone, client)
    token = (await make_link(client, asha))["token"]
    # Chitra has no account when the link is made; she installs later.
    chitra = await signed_in(phone, "+91 98765 33003", "Chitra")
    assert (await chitra.sync())["group_ids"] == []
    out = (await post(client, chitra, "/invites/accept", {"token": token})).json()
    assert out["status"] == "joined"
    assert (await chitra.sync())["group_ids"] == [GID]


async def test_joining_twice_is_one_membership(phone, client):
    asha = await owner_with_group(phone, client)
    token = (await make_link(client, asha))["token"]
    bala = await signed_in(phone, BALA, "Bala")
    assert (await post(client, bala, "/invites/accept", {"token": token})).json()["status"] == "joined"
    again = (await post(client, bala, "/invites/accept", {"token": token})).json()
    assert again["status"] == "already_member"
    assert again["message"] == "You're already a member of this group."
    pv = (await post(client, bala, "/invites/preview", {"token": token})).json()
    assert pv["status"] == "already_member"
    assert await member_rows(BALA) == 1


async def test_someone_already_added_by_number_is_not_added_twice(phone, client):
    """Bala was added by number before installing. The invite claims that row
    rather than creating a second one."""
    asha = await owner_with_group(phone, client, [mem("m-bala", "Bala", BALA)])
    token = (await make_link(client, asha))["token"]
    bala = await signed_in(phone, BALA, "Bala")
    out = (await post(client, bala, "/invites/accept", {"token": token})).json()
    assert out["status"] == "already_member"
    assert await member_rows(BALA) == 1


async def test_the_owner_opening_their_own_link(phone, client):
    asha = await owner_with_group(phone, client)
    token = (await make_link(client, asha))["token"]
    pv = (await post(client, asha, "/invites/preview", {"token": token})).json()
    assert pv["status"] == "owner" and pv["message"] == "You are already the owner of this group."
    out = (await post(client, asha, "/invites/accept", {"token": token})).json()
    assert out["status"] == "owner"
    assert await member_rows(ASHA) == 1


async def test_any_member_can_share_but_a_stranger_cannot(phone, client):
    asha = await owner_with_group(phone, client, [mem("m-bala", "Bala", BALA)])
    bala = await signed_in(phone, BALA, "Bala")
    assert (await post(client, bala, "/invites", {"group_id": GID})).status_code == 200
    dev = await signed_in(phone, DEV, "Dev")
    r = await post(client, dev, "/invites", {"group_id": GID}, ok=False)
    assert r.status_code == 403
    r = await post(client, dev, "/invites", {"group_id": "g-does-not-exist"}, ok=False)
    assert r.status_code == 404


# ------------------------------------------------------------ links that fail


async def test_expired_link_joins_nobody(phone, client):
    asha = await owner_with_group(phone, client)
    token = (await make_link(client, asha))["token"]
    async with SessionLocal() as db:
        await db.execute(update(GroupInvite).values(expires_at=utcnow() - timedelta(minutes=1)))
        await db.commit()
    bala = await signed_in(phone, BALA, "Bala")
    out = (await post(client, bala, "/invites/accept", {"token": token})).json()
    assert out["status"] == "expired" and "expired" in out["message"]
    assert await member_rows(BALA) == 0
    assert (await bala.sync())["group_ids"] == []


async def test_deleted_group_cannot_be_joined(phone, client):
    asha = await owner_with_group(phone, client)
    token = (await make_link(client, asha))["token"]
    await asha.sync(groups=[grp(deleted=True, updated_at="2027-01-01T00:00:00+00:00")])
    bala = await signed_in(phone, BALA, "Bala")
    out = (await post(client, bala, "/invites/accept", {"token": token})).json()
    assert out["status"] == "deleted" and out["message"] == "This group is no longer available."
    assert await member_rows(BALA) == 0
    # and no new links for it either
    assert (await post(client, asha, "/invites", {"group_id": GID}, ok=False)).status_code == 404


async def test_invalid_tokens_say_nothing_more(phone, client):
    await owner_with_group(phone, client)
    bala = await signed_in(phone, BALA, "Bala")
    for bad in ["random-invalid-token", GID, "x" * 22, "../../etc/passwd", "a b c d e f g h i j k l m"]:
        out = (await post(client, bala, "/invites/accept", {"token": bad})).json()
        assert out == {"success": True, "status": "invalid", "message": "This invite link isn't valid."}
    assert await member_rows(BALA) == 0


async def test_owner_revokes_old_links_stop_new_link_works(phone, client):
    asha = await owner_with_group(phone, client, [mem("m-bala", "Bala", BALA)])
    old = (await make_link(client, asha))["token"]
    bala = await signed_in(phone, BALA, "Bala")
    r = await post(client, bala, "/invites/revoke", {"group_id": GID}, ok=False)
    assert r.status_code == 403, "only the owner revokes"
    assert (await post(client, asha, "/invites/revoke", {"group_id": GID})).json()["revoked"] == 1
    new = (await make_link(client, asha))["token"]
    chitra = await signed_in(phone, CHITRA, "Chitra")
    assert (await post(client, chitra, "/invites/accept", {"token": old})).json()["status"] == "revoked"
    assert (await post(client, chitra, "/invites/accept", {"token": new})).json()["status"] == "joined"


async def test_joining_needs_a_signed_in_account(client, phone):
    asha = await owner_with_group(phone, client)
    token = (await make_link(client, asha))["token"]
    for path in ("/invites/accept", "/invites/preview"):
        r = await client.post(path, json={"token": token})
        assert r.status_code == 401
    assert await member_rows(BALA) == 0


async def test_the_token_is_stored_only_as_a_hash(phone, client):
    asha = await owner_with_group(phone, client)
    token = (await make_link(client, asha))["token"]
    async with SessionLocal() as db:
        row = await db.scalar(select(GroupInvite))
    assert row.token_hash == hash_token(token) and token not in row.token_hash


async def test_joining_after_removing_it_from_view_brings_it_back(phone, client):
    asha = await owner_with_group(phone, client, [mem("m-bala", "Bala", BALA)])
    bala = await signed_in(phone, BALA, "Bala")
    await bala.sync(hidden=[{"group_id": GID, "hidden": True}])
    # Asha takes Bala out; later Bala joins again through a link.
    await asha.sync(members=[mem("m-bala", "Bala", BALA, deleted=True,
                                updated_at="2027-01-01T00:00:00+00:00")])
    token = (await make_link(client, asha))["token"]
    assert (await post(client, bala, "/invites/accept", {"token": token})).json()["status"] == "joined"
    bala.seq = 0
    got = await bala.sync()
    assert got["group_ids"] == [GID] and got["hidden"] == []


async def test_sharing_changes_no_membership(phone, client):
    asha = await owner_with_group(phone, client, [mem("m-bala", "Bala", BALA)])
    asha.seq = 0
    before = await asha.sync()
    for _ in range(3):
        await make_link(client, asha)
    asha.seq = 0
    after = await asha.sync()
    assert before["members"] == after["members"] and before["group_ids"] == after["group_ids"]


# ------------------------------------------------------------ public pages


async def test_join_page_shows_only_the_group_name(phone, client):
    asha = await owner_with_group(phone, client, [mem("m-bala", "Bala", BALA)])
    await asha.sync(groups=[grp(name='<script>alert(1)</script> & co',
                                updated_at="2027-01-01T00:00:00+00:00")])
    token = (await make_link(client, asha))["token"]
    r = await client.get("/join/" + token)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    page = r.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co" in page and "<script>alert" not in page
    assert "intent://join/" + token in page and "package=com.sherinlal.splitledger" in page
    for secret in (GID, BALA, ASHA, "6358", asha.user["id"]):
        assert secret not in page, f"{secret} leaked into the page"


async def test_join_page_for_bad_links(phone, client):
    asha = await owner_with_group(phone, client)
    r = await client.get("/join/not-a-real-token-at-all")
    assert r.status_code == 404 and "isn't valid" in r.text
    token = (await make_link(client, asha))["token"]
    await asha.sync(groups=[grp(deleted=True, updated_at="2027-01-01T00:00:00+00:00")])
    r = await client.get("/join/" + token)
    assert r.status_code == 410 and "no longer available" in r.text and "App development" not in r.text


async def test_assetlinks_names_the_app_and_its_certificate(client):
    r = await client.get("/.well-known/assetlinks.json")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    t = r.json()[0]["target"]
    assert t["package_name"] == "com.sherinlal.splitledger"
    assert t["sha256_cert_fingerprints"][0].startswith("A6:C3:30:2C")
