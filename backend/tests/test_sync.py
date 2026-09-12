"""The feature this whole backend exists for: one person creates a group and
adds someone from their contacts; that person opens the app on their own phone
and finds the group, its members and every expense already there.
"""
import pytest

pytestmark = pytest.mark.asyncio

GID = "g-goa-2026"


def group(name="Goa Trip 2026", **kw):
    return {"id": GID, "name": name, "currency": "INR", "deleted": False, **kw}


def member(mid, name, phone=None, **kw):
    return {"id": mid, "group_id": GID, "name": name, "phone": phone,
            "role": "member", "deleted": False, **kw}


def expense(eid, desc, amount, paid_by, splits, **kw):
    return {"id": eid, "group_id": GID, "description": desc, "amount_minor": amount,
            "currency": "INR", "category": "Food & drink", "expense_date": "2026-07-16",
            "split_type": "equal", "paid_by": paid_by, "payers": {paid_by: amount},
            "splits": splits, "values": {}, "deleted": False, **kw}


async def test_a_group_reaches_the_person_added_from_contacts(phone):
    sherin = phone("9876543210", "Sherin")
    await sherin.sign_in()

    # Sherin makes the group and adds Anu from her contacts
    await sherin.sync(
        groups=[group()],
        members=[member("m-sherin", "Sherin", "+919876543210"),
                 member("m-anu", "Anu", "98765 00002")],
        expenses=[expense("e1", "Dinner at Thalassa", 124500, "m-sherin",
                          {"m-sherin": 62250, "m-anu": 62250})],
    )

    # Anu installs the app on her own phone and signs in for the first time
    anu = phone("+919876500002", "Anu")
    body = await anu.sign_in()
    assert body["created"] is True

    got = await anu.sync()
    assert [g["name"] for g in got["groups"]] == ["Goa Trip 2026"]
    assert {m["name"] for m in got["members"]} == {"Sherin", "Anu"}
    assert len(got["expenses"]) == 1
    e = got["expenses"][0]
    assert e["description"] == "Dinner at Thalassa"
    assert e["amount_minor"] == 124500
    assert e["splits"] == {"m-sherin": 62250, "m-anu": 62250}

    # the number Sherin typed was normalised before it was matched
    anu_row = next(m for m in got["members"] if m["name"] == "Anu")
    assert anu_row["phone"] == "+919876500002"
    assert anu_row["user_id"] == anu.user["id"]


async def test_both_people_can_add_and_each_sees_the_other(phone):
    sherin = phone("9876543210", "Sherin")
    await sherin.sign_in()
    await sherin.sync(groups=[group()],
                      members=[member("m-sherin", "Sherin", "+919876543210"),
                               member("m-anu", "Anu", "+919876500002")])

    anu = phone("+919876500002", "Anu")
    await anu.sign_in()
    await anu.sync()

    # Anu adds an expense from her phone
    await anu.sync(expenses=[expense("e-anu", "Scooter rental", 64000, "m-anu",
                                     {"m-sherin": 32000, "m-anu": 32000})])

    # Sherin picks it up on hers
    got = await sherin.sync()
    assert [e["description"] for e in got["expenses"]] == ["Scooter rental"]

    # and a settlement travels the other way
    await sherin.sync(settlements=[{
        "id": "s1", "group_id": GID, "from_member": "m-anu", "to_member": "m-sherin",
        "amount_minor": 32000, "currency": "INR", "method": "UPI", "note": "",
        "settled_date": "2026-08-06", "deleted": False}])
    got = await anu.sync()
    assert len(got["settlements"]) == 1
    assert got["settlements"][0]["method"] == "UPI"


async def test_a_stranger_cannot_touch_or_read_the_group(phone):
    sherin = phone("9876543210", "Sherin")
    await sherin.sign_in()
    await sherin.sync(groups=[group()],
                      members=[member("m-sherin", "Sherin", "+919876543210")],
                      expenses=[expense("e1", "Flights", 482000, "m-sherin",
                                        {"m-sherin": 482000})])

    stranger = phone("9000000001", "Nosy")
    await stranger.sign_in()

    got = await stranger.sync()
    assert got["groups"] == [] and got["expenses"] == []

    # and writing into someone else's group is refused, not silently accepted
    pushed = await stranger.sync(expenses=[expense("e-bad", "Not mine", 100, "m-sherin",
                                                   {"m-sherin": 100})])
    assert pushed["rejected"], "write into a foreign group should be rejected"
    assert pushed["rejected"][0]["reason"] == "not_a_member"

    back = await sherin.sync()
    assert all(e["description"] != "Not mine" for e in back["expenses"])


async def test_the_cursor_only_returns_what_changed(phone):
    sherin = phone("9876543210", "Sherin")
    await sherin.sign_in()
    await sherin.sync(groups=[group()],
                      members=[member("m-sherin", "Sherin", "+919876543210")])
    quiet = await sherin.sync()
    assert quiet["groups"] == [] and quiet["members"] == []

    await sherin.sync(expenses=[expense("e1", "Villa", 360000, "m-sherin",
                                        {"m-sherin": 360000})])
    after = await sherin.sync()
    assert after["expenses"] == []          # already delivered in the push round


async def test_last_writer_wins_on_a_clash(phone):
    sherin = phone("9876543210", "Sherin")
    await sherin.sign_in()
    await sherin.sync(groups=[group()],
                      members=[member("m-sherin", "Sherin", "+919876543210"),
                               member("m-anu", "Anu", "+919876500002")],
                      expenses=[expense("e1", "Dinner", 100000, "m-sherin",
                                        {"m-sherin": 100000},
                                        updated_at="2026-07-16T10:00:00Z")])
    anu = phone("+919876500002", "Anu")
    await anu.sign_in()
    await anu.sync()

    # Anu edits it later than Sherin did -> Anu's version stands
    await anu.sync(expenses=[expense("e1", "Dinner at Thalassa", 124500, "m-sherin",
                                     {"m-sherin": 62250, "m-anu": 62250},
                                     updated_at="2026-07-16T12:00:00Z")])
    # Sherin's phone had been offline with an older edit -> it must not win
    await sherin.sync(expenses=[expense("e1", "Dinner (stale)", 999, "m-sherin",
                                        {"m-sherin": 999},
                                        updated_at="2026-07-16T09:00:00Z")])

    fresh = phone("9000000009", "Observer")
    await fresh.sign_in()
    # observer is not a member, so read it back through Anu instead
    anu.seq = 0
    got = await anu.sync()
    e = next(x for x in got["expenses"] if x["id"] == "e1")
    assert e["description"] == "Dinner at Thalassa"
    assert e["amount_minor"] == 124500


async def test_a_deletion_travels(phone):
    sherin = phone("9876543210", "Sherin")
    await sherin.sign_in()
    await sherin.sync(groups=[group()],
                      members=[member("m-sherin", "Sherin", "+919876543210"),
                               member("m-anu", "Anu", "+919876500002")],
                      expenses=[expense("e1", "Dinner", 100000, "m-sherin",
                                        {"m-sherin": 100000})])
    anu = phone("+919876500002", "Anu")
    await anu.sign_in()
    got = await anu.sync()
    assert len(got["expenses"]) == 1

    await sherin.sync(expenses=[expense("e1", "Dinner", 100000, "m-sherin",
                                        {"m-sherin": 100000}, deleted=True,
                                        updated_at="2030-01-01T00:00:00Z")])
    got = await anu.sync()
    assert got["expenses"][0]["deleted"] is True      # tombstone, not silence


async def test_being_added_later_hands_over_the_whole_history(phone):
    """Divya joins after the trip is already logged and still gets everything."""
    sherin = phone("9876543210", "Sherin")
    await sherin.sign_in()
    await sherin.sync(groups=[group()],
                      members=[member("m-sherin", "Sherin", "+919876543210")],
                      expenses=[expense("e1", "Flights", 482000, "m-sherin",
                                        {"m-sherin": 482000}),
                                expense("e2", "Villa", 360000, "m-sherin",
                                        {"m-sherin": 360000})])
    await sherin.sync(members=[member("m-divya", "Divya", "9876500004")])

    divya = phone("9876500004", "Divya")
    await divya.sign_in()
    got = await divya.sync()
    assert len(got["groups"]) == 1
    assert {e["description"] for e in got["expenses"]} == {"Flights", "Villa"}


async def test_a_bad_number_on_a_member_keeps_the_name(phone):
    sherin = phone("9876543210", "Sherin")
    await sherin.sign_in()
    out = await sherin.sync(groups=[group()],
                            members=[member("m-x", "No Number", "not a phone")])
    assert not out["rejected"]
    got = await sherin.sync()
    sherin.seq = 0
    got = await sherin.sync()
    row = next(m for m in got["members"] if m["id"] == "m-x")
    assert row["name"] == "No Number" and row["phone"] is None


async def test_sync_needs_a_token(client):
    r = await client.post("/sync", json={"since": 0, "changes": {}})
    assert r.status_code == 401
