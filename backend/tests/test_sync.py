"""The feature this whole backend exists for: one person creates a group and
adds someone from their contacts; that person opens the app on their own phone
and finds the group, its members and every expense already there.
"""
import asyncio

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


# --- waiting, instead of asking again in two minutes -------------------------


async def test_a_waiting_phone_is_told_the_moment_a_group_appears(phone):
    """The point of the whole thing: Anu's app is open and idle, Sherin makes a
    group, and Anu's phone hears about it within a second — not on its next
    two-minute poll."""
    sherin = phone("9876543210", "Sherin")
    anu = phone("9876500002", "Anu")
    await sherin.sign_in()
    await anu.sign_in()
    await anu.sync()                       # up to date, nothing pending

    async def anu_waits():
        started = asyncio.get_event_loop().time()
        out = await anu.sync(wait=10)
        return out, asyncio.get_event_loop().time() - started

    waiting = asyncio.create_task(anu_waits())
    await asyncio.sleep(0.3)               # Anu is now holding the line open
    await sherin.sync(groups=[group()],
                      members=[member("m-sherin", "Sherin", "+919876543210"),
                               member("m-anu", "Anu", "9876500002")])
    out, took = await asyncio.wait_for(waiting, timeout=12)

    assert [g["name"] for g in out["groups"]] == ["Goa Trip 2026"]
    assert took < 5, f"took {took:.1f}s — that is a poll, not a wait"


async def test_a_wait_with_nothing_to_report_gives_up_on_its_own(phone):
    """Nobody does anything: the request comes back empty at the end of the
    wait rather than hanging until the phone times out."""
    sherin = phone("9876543210", "Sherin")
    await sherin.sign_in()
    await sherin.sync()

    started = asyncio.get_event_loop().time()
    out = await sherin.sync(wait=2)
    took = asyncio.get_event_loop().time() - started

    assert not out["groups"] and not out["expenses"]
    assert 1.0 < took < 6.0, f"came back after {took:.1f}s"


async def test_a_phone_with_something_to_send_is_never_held(phone):
    """A wait only ever applies to an empty request. Anything being pushed is
    answered at once, or adding an expense would feel frozen."""
    sherin = phone("9876543210", "Sherin")
    await sherin.sign_in()
    started = asyncio.get_event_loop().time()
    await sherin.sync(wait=10, groups=[group()],
                      members=[member("m-sherin", "Sherin", "+919876543210")])
    assert asyncio.get_event_loop().time() - started < 2


async def test_a_silly_wait_is_capped(phone):
    """A client asking for an hour gets the server's maximum, so a stuck or
    hostile caller cannot pin a connection down."""
    from app.sync.router import MAX_WAIT
    sherin = phone("9876543210", "Sherin")
    await sherin.sign_in()
    await sherin.sync()
    started = asyncio.get_event_loop().time()
    await sherin.sync(wait=100000)
    took = asyncio.get_event_loop().time() - started
    assert took < MAX_WAIT + 4, f"held for {took:.1f}s, cap is {MAX_WAIT}s"


# --- who may delete a group ---------------------------------------------------


async def _goa_with_anu(phone):
    """Sherin makes the group and adds Anu; both are signed in and synced."""
    sherin = phone("9876543210", "Sherin")
    anu = phone("9876500002", "Anu")
    await sherin.sign_in()
    await anu.sign_in()
    await sherin.sync(
        groups=[group()],
        members=[member("m-sherin", "Sherin", "+919876543210"),
                 member("m-anu", "Anu", "9876500002")],
        expenses=[expense("e1", "Dinner at Thalassa", 124500, "m-sherin",
                          {"m-sherin": 62250, "m-anu": 62250})],
    )
    await anu.sync()
    return sherin, anu


async def test_a_member_cannot_delete_the_group_for_everyone(phone):
    """Anu did not create the group, so her delete is refused. On her own phone
    the app hides it locally and never sends this at all — but an older build,
    or a hand-made request, must not be able to wipe out Sherin's records."""
    sherin, anu = await _goa_with_anu(phone)

    out = await anu.sync(groups=[group(deleted=True, updated_at="2027-01-01T00:00:00+00:00")])
    assert out["rejected"] == [{"kind": "group", "id": GID, "reason": "not_the_creator"}]

    sherin.seq = 0
    got = await sherin.sync()
    assert [g["deleted"] for g in got["groups"]] == [False], "Sherin lost her group"


async def test_a_refused_delete_does_not_gut_the_group_on_the_way_past(phone):
    """Deleting a group tombstones everything inside it, and those rows travel
    in the same request. Refusing only the group would leave it standing and
    empty, which is worse than either outcome."""
    sherin, anu = await _goa_with_anu(phone)
    later = "2027-01-01T00:00:00+00:00"

    out = await anu.sync(
        groups=[group(deleted=True, updated_at=later)],
        members=[member("m-sherin", "Sherin", "+919876543210", deleted=True, updated_at=later),
                 member("m-anu", "Anu", "9876500002", deleted=True, updated_at=later)],
        expenses=[expense("e1", "Dinner at Thalassa", 124500, "m-sherin",
                          {"m-sherin": 62250, "m-anu": 62250},
                          deleted=True, updated_at=later)],
    )
    assert all(r["reason"] == "not_the_creator" for r in out["rejected"])
    assert len(out["rejected"]) == 4

    sherin.seq = 0
    got = await sherin.sync()
    assert [g["deleted"] for g in got["groups"]] == [False]
    assert [e["deleted"] for e in got["expenses"]] == [False], "the expense was deleted anyway"
    assert [m["deleted"] for m in got["members"]] == [False, False]


async def test_the_creator_can_still_delete_it_for_everyone(phone):
    """The other half of the rule — and the part that must not regress."""
    sherin, anu = await _goa_with_anu(phone)

    out = await sherin.sync(groups=[group(deleted=True, updated_at="2027-01-01T00:00:00+00:00")])
    assert not out["rejected"]

    got = await anu.sync()
    assert [g["deleted"] for g in got["groups"]] == [True]


async def test_a_member_can_still_delete_an_ordinary_expense(phone):
    """The rule is about deleting the whole group. Everyday editing is
    untouched: any member may still remove an expense."""
    sherin, anu = await _goa_with_anu(phone)
    out = await anu.sync(expenses=[expense("e1", "Dinner at Thalassa", 124500, "m-sherin",
                                           {"m-sherin": 62250, "m-anu": 62250},
                                           deleted=True,
                                           updated_at="2027-01-01T00:00:00+00:00")])
    assert not out["rejected"]
    got = await sherin.sync()
    assert [e["deleted"] for e in got["expenses"]] == [True]


async def test_the_creator_is_reported_so_the_app_knows_whose_button_it_is(phone):
    """The app decides which of the two delete buttons to show from this."""
    sherin, anu = await _goa_with_anu(phone)
    anu.seq = 0
    got = await anu.sync()
    assert got["groups"][0]["created_by"] == sherin.user["id"]


# --- removing a group from your own view, without touching anyone else's -----


async def test_a_member_can_hide_a_group_for_themselves_only(phone):
    """The other half of the delete rule. Anu removes the group from her own
    view; Sherin's copy is untouched, and she is not removed from the group."""
    sherin, anu = await _goa_with_anu(phone)

    out = await anu.sync(hidden=[{"group_id": GID, "hidden": True}])
    assert not out["rejected"]
    assert out["hidden"] == [GID]

    # Sherin is told nothing at all — not that it happened, not that she left.
    sherin.seq = 0
    got = await sherin.sync()
    assert got["hidden"] == [], "Anu's choice leaked to Sherin"
    assert [g["deleted"] for g in got["groups"]] == [False]
    assert [m["deleted"] for m in got["members"]] == [False, False]


async def test_hiding_survives_a_reinstall(phone):
    """The point of keeping this on the server. A phone that has lost
    everything local asks for the whole picture and is told, again, which
    groups this account does not want to see."""
    sherin, anu = await _goa_with_anu(phone)
    await anu.sync(hidden=[{"group_id": GID, "hidden": True}])

    fresh = phone("9876500002", "Anu")          # same number, nothing local
    await fresh.sign_in()
    got = await fresh.sync()
    assert got["hidden"] == [GID]
    assert len(got["groups"]) == 1, "the group itself is still there, just hidden"


async def test_putting_it_back(phone):
    sherin, anu = await _goa_with_anu(phone)
    await anu.sync(hidden=[{"group_id": GID, "hidden": True}])
    out = await anu.sync(hidden=[{"group_id": GID, "hidden": False}])
    assert out["hidden"] == []


async def test_hiding_is_idempotent(phone):
    """The phone may send the same thing twice — a retry after a reply it
    never saw. Twice must mean the same as once."""
    sherin, anu = await _goa_with_anu(phone)
    await anu.sync(hidden=[{"group_id": GID, "hidden": True}])
    out = await anu.sync(hidden=[{"group_id": GID, "hidden": True}])
    assert out["hidden"] == [GID]


async def test_removing_is_one_way_on_the_server(phone):
    """Nothing the server sends may take a removal back. Sending the same
    removal twice, or a later unrelated sync, must leave it in place."""
    sherin, anu = await _goa_with_anu(phone)
    await anu.sync(hidden=[{"group_id": GID, "hidden": True}])
    for _ in range(3):
        out = await anu.sync()
        assert out["hidden"] == [GID], "an ordinary sync un-removed it"


async def test_being_added_back_clears_the_removal(phone):
    """Removal is permanent, which would otherwise make re-adding someone a
    dead end: a member of a group they can never see, with no way out."""
    sherin, anu = await _goa_with_anu(phone)
    await anu.sync(hidden=[{"group_id": GID, "hidden": True}])
    assert (await anu.sync())["hidden"] == [GID]

    # Sherin drops her, then adds her again — a brand-new member row
    await sherin.sync(members=[member("m-anu", "Anu", "9876500002", deleted=True,
                                      updated_at="2027-01-01T00:00:00+00:00")])
    await sherin.sync(members=[member("m-anu-2", "Anu", "9876500002",
                                      updated_at="2027-01-02T00:00:00+00:00")])
    assert (await anu.sync())["hidden"] == [], "she still cannot see the group"


async def test_you_cannot_hide_someone_elses_group(phone):
    outsider = phone("9876500009", "Nobody")
    await outsider.sign_in()
    out = await outsider.sync(hidden=[{"group_id": "g-not-mine", "hidden": True}])
    assert out["rejected"] == [{"kind": "hidden", "id": "g-not-mine", "reason": "not_a_member"}]
