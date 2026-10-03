"""End to end: choosing several contacts in one go.

The page is the phone build's own page. The Android bridge is replaced by a
stand-in with the same three methods and the same data format as
MainActivity/Contacts.smali (rows of "name,number,contactId", each field
percent-encoded, newline-separated), so everything from the tap on Contacts to
the group reaching the server is the real code path. Only the address book is
made up.

    ./run.sh contacts
"""
import asyncio
import os
import random
import sys
import time
from urllib.parse import quote

from playwright.async_api import async_playwright

from harness import Phone

ONLY = sys.argv[1].split(",") if len(sys.argv) > 1 else None
BASE = random.randint(100, 899)
_n = [0]


def fresh_owner():
    _n[0] += 1
    return "9%03d%02d0000" % (BASE, _n[0])


# name, number as saved in the address book, contact id
BOOK = [
    ("Suthan Kumar", "+91 98945 86224", "1"),
    ("", "9786365455", "2"),                      # saved with no name
    ("Muralidhar", "098400 12345", "3"),
    ("Vijay", "+91-98844-12345", "4"),
    ("John", "90000 00001", "5"),
    ("John", "90000 00002", "6"),                 # same name, different person
    ("Suthan (work)", "+919894586224", "7"),      # Suthan's number saved twice
    ("Pizza place", "123", "8"),                  # not a mobile number
    ("Anu", "98765 22222", "9"),
]


def book_text(rows):
    return "\n".join(",".join(quote(f, safe="") for f in r) for r in rows)


def bridge(rows, answer=None, with_multi=True):
    """A stand-in for MainActivity's AndroidBridge."""
    payload = answer if answer is not None else book_text(rows)
    multi = """
        askContacts() { window.__asked = (window.__asked || 0) + 1;
                        setTimeout(() => window.__contactsReady && window.__contactsReady(), 20); },
        contacts() { return window.__book; },""" if with_multi else ""
    return f"""
      window.__book = {payload!r};
      window.__singles = 0;
      window.AndroidBridge = {{{multi}
        pickContact() {{ window.__singles++;
          setTimeout(() => window.__contactPicked(encodeURIComponent("Anu"), encodeURIComponent("98765 22222")), 20); }}
      }};"""


async def new_group_dialog(p, name="Goa Trip"):
    await p.app("() => openGroupModal(null)")
    await p.page.fill("input[placeholder^='Goa trip']", name)


async def open_picker(p):
    await p.page.click("#modalRoot button:has-text('Contacts')")
    await p.page.wait_for_selector(".cpick", timeout=5000)


async def tap(p, label):
    await p.page.click(f".cp-row:has(.nm:text-is('{label}'))")


async def done_text(p):
    return (await p.page.text_content(".cpick .btn-primary")).strip()


async def picked(p):
    return await p.page.eval_on_selector_all(".cp-chip .nm", "els => els.map(e => e.textContent)")


async def ticked(p):
    return await p.page.eval_on_selector_all(".cp-row.on .nm", "els => els.map(e => e.textContent)")


async def dialog_members(p):
    return await p.page.eval_on_selector_all("#modalRoot .memberline .mi", """els => els.map(e => [
        e.querySelector('.nm').firstChild.textContent, e.querySelector('.ph').textContent])""")


async def press_done(p):
    await p.page.click(".cpick .btn-primary")
    await p.page.wait_for_selector(".cpick", state="detached", timeout=3000)


def check(cond, msg, problems):
    if not cond:
        problems.append(msg)


# ------------------------------------------------------------------ scenarios


async def s_acceptance_three_contacts_then_create(br):
    """The acceptance flow, start to finish, and on to the server."""
    owner = await Phone.open(br, "Asha", "+91" + fresh_owner(), init=bridge(BOOK))
    problems = []
    await new_group_dialog(owner)
    await open_picker(owner)
    for i, who in enumerate(["Suthan Kumar", "Vijay", "Muralidhar"], 1):
        await tap(owner, who)
        check(await owner.page.is_visible(".cpick"), f"picker closed after selecting {who}", problems)
        check(await done_text(owner) == f"Done ({i})", f"after {who}: button says {await done_text(owner)!r}", problems)
    check(await picked(owner) == ["Suthan Kumar", "Vijay", "Muralidhar"], f"chips {await picked(owner)}", problems)
    await press_done(owner)
    members = await dialog_members(owner)
    names = [m[0] for m in members]
    check(names == ["Asha", "Suthan Kumar", "Vijay", "Muralidhar"], f"dialog shows {names}", problems)
    check(await owner.page.is_visible("#modalRoot button:has-text('Create group')"),
          "the group was created without pressing Create group", problems)
    await owner.page.click("#modalRoot button:has-text('Create group')")
    await owner.sync()
    saved = await owner.app("() => S.groups[0].members.map(m => [m.name, m.phone])")
    check(saved[1:] == [["Suthan Kumar", "+919894586224"], ["Vijay", "+919884412345"],
                        ["Muralidhar", "+919840012345"]], f"saved members {saved}", problems)
    # synchronised: Vijay installs later and finds the group
    vijay = await Phone.install(br, "Vijay", "98844 12345")
    async def arrived():
        return await vijay.live()
    end = time.time() + 15
    while time.time() < end and not await arrived():
        await asyncio.sleep(0.3)
    check(await vijay.live() == ["Goa Trip"], f"Vijay's phone shows {await vijay.live()}", problems)
    others = await vijay.app("() => S.groups[0] ? S.groups[0].members.map(m => m.phone).sort() : []")
    check(len(others) == 4 and "+919894586224" in others, f"Vijay sees members {others}", problems)
    return problems


async def s_t1_one_contact(br):
    p = await Phone.open(br, "Asha", "+91" + fresh_owner(), init=bridge(BOOK))
    await new_group_dialog(p); await open_picker(p)
    await tap(p, "Anu")
    problems = []
    check(await done_text(p) == "Done (1)", await done_text(p), problems)
    await press_done(p)
    check([m[0] for m in await dialog_members(p)] == ["Asha", "Anu"], str(await dialog_members(p)), problems)
    return problems


async def s_t3_toggle(br):
    p = await Phone.open(br, "Asha", "+91" + fresh_owner(), init=bridge(BOOK))
    await new_group_dialog(p); await open_picker(p)
    await tap(p, "Suthan Kumar"); await tap(p, "Vijay"); await tap(p, "Suthan Kumar")
    problems = []
    check(await ticked(p) == ["Vijay"], f"ticked {await ticked(p)}", problems)
    check(await picked(p) == ["Vijay"], f"chips {await picked(p)}", problems)
    check(await done_text(p) == "Done (1)", await done_text(p), problems)
    await tap(p, "Vijay")
    check(await done_text(p) == "Done", f"with nothing selected: {await done_text(p)}", problems)
    check(await p.page.is_disabled(".cpick .btn-primary"), "Done is enabled with nothing selected", problems)
    return problems


async def s_t4_search_keeps_selection(br):
    p = await Phone.open(br, "Asha", "+91" + fresh_owner(), init=bridge(BOOK))
    await new_group_dialog(p); await open_picker(p)
    await tap(p, "Suthan Kumar"); await tap(p, "Muralidhar")
    q = ".cpick input[placeholder='Search by name or number']"
    problems = []
    await p.page.fill(q, "vijay"); await p.page.wait_for_timeout(100)
    visible = await p.page.eval_on_selector_all(".cp-row:not([hidden]) .nm", "els => els.map(e => e.textContent)")
    check(visible == ["Vijay"], f"search 'vijay' shows {visible}", problems)
    await tap(p, "Vijay")
    await p.page.fill(q, "9786"); await p.page.wait_for_timeout(100)
    visible = await p.page.eval_on_selector_all(".cp-row:not([hidden]) .nm", "els => els.map(e => e.textContent)")
    check(visible == ["+91 97863 65455"], f"search '9786' shows {visible}", problems)
    await p.page.fill(q, "nobody here"); await p.page.wait_for_timeout(100)
    check(await p.page.is_visible(".cp-empty"), "no 'no match' message", problems)
    await p.page.fill(q, ""); await p.page.wait_for_timeout(100)
    check(sorted(await ticked(p)) == ["Muralidhar", "Suthan Kumar", "Vijay"], f"after clearing: {await ticked(p)}", problems)
    check(await done_text(p) == "Done (3)", await done_text(p), problems)
    await press_done(p)
    names = [m[0] for m in await dialog_members(p)]
    check(names == ["Asha", "Suthan Kumar", "Muralidhar", "Vijay"], f"dialog shows {names}", problems)
    return problems


async def s_t5_duplicates(br):
    """One number is one person: tapping twice is a toggle, and the same number
    saved under two contacts is listed once."""
    p = await Phone.open(br, "Asha", "+91" + fresh_owner(), init=bridge(BOOK))
    await new_group_dialog(p); await open_picker(p)
    problems = []
    suthans = await p.page.eval_on_selector_all(".cp-row .ph", "els => els.filter(e => e.textContent === '+91 98945 86224').length")
    check(suthans == 1, f"Suthan's number listed {suthans} times", problems)
    check(not await p.page.is_visible(".cp-row:has-text('Pizza place')"), "a non-mobile number was offered", problems)
    await tap(p, "Suthan Kumar"); await tap(p, "Suthan Kumar"); await tap(p, "Suthan Kumar")
    check(await picked(p) == ["Suthan Kumar"], f"chips {await picked(p)}", problems)
    await press_done(p)
    # and again from a second opening: already in the group, so not offered
    await open_picker(p)
    row = ".cp-row:has(.nm:text-is('Suthan Kumar'))"
    check(await p.page.is_disabled(row), "Suthan offered again although already in the group", problems)
    check("In group" in (await p.page.text_content(row)), "no 'In group' label", problems)
    await p.page.click(".cpick button:has-text('Cancel')")
    members = [m[1] for m in await dialog_members(p)]
    check(members.count("+91 98945 86224") == 1, f"members {members}", problems)
    return problems


async def s_t6_chip_removal(br):
    p = await Phone.open(br, "Asha", "+91" + fresh_owner(), init=bridge(BOOK))
    await new_group_dialog(p); await open_picker(p)
    await tap(p, "Suthan Kumar"); await tap(p, "Vijay")
    await p.page.click(".cp-chip:has(.nm:text-is('Suthan Kumar')) .x")
    problems = []
    check(await picked(p) == ["Vijay"], f"chips {await picked(p)}", problems)
    check(await ticked(p) == ["Vijay"], f"ticked {await ticked(p)}", problems)
    check(await done_text(p) == "Done (1)", await done_text(p), problems)
    return problems


async def s_t7_cancel_and_back_add_nothing(br):
    p = await Phone.open(br, "Asha", "+91" + fresh_owner(), init=bridge(BOOK))
    await new_group_dialog(p)
    problems = []
    await open_picker(p); await tap(p, "Suthan Kumar"); await tap(p, "Vijay")
    await p.page.click(".cpick button:has-text('Cancel')")
    check(not await p.page.is_visible(".cpick"), "Cancel did not close", problems)
    check(len(await dialog_members(p)) == 1, f"Cancel added {await dialog_members(p)}", problems)
    # the phone's Back button (the phone build maps it to history.back)
    await open_picker(p); await tap(p, "Muralidhar")
    await p.page.evaluate("history.back()"); await p.page.wait_for_timeout(300)
    check(not await p.page.is_visible(".cpick"), "Back did not close the picker", problems)
    check(await p.page.is_visible("#modalRoot .modal"), "Back also closed the group dialog", problems)
    check(len(await dialog_members(p)) == 1, f"Back added {await dialog_members(p)}", problems)
    # reopening starts clean
    await open_picker(p)
    check(await done_text(p) == "Done" and await picked(p) == [], "a cancelled selection came back", problems)
    return problems


async def s_t8_existing_member_and_manual_entry(br):
    """Typed members and picked members are one list: the same number cannot
    go in twice whichever way it arrives."""
    p = await Phone.open(br, "Asha", "+91" + fresh_owner(), init=bridge(BOOK))
    await new_group_dialog(p)
    await p.page.fill("input[placeholder='Name']", "Vij")
    await p.page.fill("input[placeholder^='Mobile number']", "98844 12345")
    await p.page.click("#modalRoot button:text-is('Add')")
    await open_picker(p)
    problems = []
    check(await p.page.is_disabled(".cp-row:has(.nm:text-is('Vijay'))"), "typed member offered again", problems)
    await tap(p, "Anu"); await press_done(p)
    # and typing a number that was just picked is refused
    await p.page.fill("input[placeholder='Name']", "Anu again")
    await p.page.fill("input[placeholder^='Mobile number']", "+91 98765 22222")
    await p.page.click("#modalRoot button:text-is('Add')")
    phones = [m[1] for m in await dialog_members(p)]
    check(phones.count("+91 98765 22222") == 1, f"members {phones}", problems)
    check(len(phones) == 3, f"members {phones}", problems)
    return problems


async def s_t9_same_name(br):
    p = await Phone.open(br, "Asha", "+91" + fresh_owner(), init=bridge(BOOK))
    await new_group_dialog(p); await open_picker(p)
    johns = ".cp-row:has(.nm:text-is('John'))"
    problems = []
    check(await p.page.locator(johns).count() == 2, "the two Johns are not both listed", problems)
    await p.page.locator(johns).nth(1).click()
    check(await done_text(p) == "Done (1)", "tapping one John selected both", problems)
    await press_done(p)
    phones = [m[1] for m in await dialog_members(p)]
    check(phones[1:] == ["+91 90000 00002"], f"added {phones}", problems)
    await open_picker(p)
    check(not await p.page.is_disabled(johns + " >> nth=0"), "the other John was blocked as a duplicate", problems)
    check(await p.page.is_disabled(johns + " >> nth=1"), "the added John can be added again", problems)
    return problems


async def s_t10_large_book(br):
    """3,000 contacts: opening, selecting across a long scroll, and searching
    stay quick, and selections survive scrolling."""
    rng = random.Random(7)
    first = ["Arun", "Bala", "Chitra", "Deepa", "Elango", "Farah", "Ganesh", "Hari", "Indu", "Jaya"]
    rows = [(f"{rng.choice(first)} {i:04d}", f"9{rng.randint(100000000, 999999999)}", str(i)) for i in range(3000)]
    rows += BOOK
    p = await Phone.open(br, "Asha", "+91" + fresh_owner(), init=bridge(rows))
    await new_group_dialog(p)
    problems = []
    t = time.time(); await open_picker(p); opened = time.time() - t
    n = await p.page.locator(".cp-row").count()
    check(n >= 3000, f"only {n} rows", problems)
    await tap(p, "Arun 0000") if await p.page.locator(".cp-row:has(.nm:text-is('Arun 0000'))").count() else None
    first_row = p.page.locator(".cp-row:not(.in)").first
    await first_row.click()
    await p.page.eval_on_selector(".cp-list", "e => e.scrollTop = e.scrollHeight")
    last_row = p.page.locator(".cp-row:not(.in)").last
    t = time.time(); await last_row.click(); tapped = time.time() - t
    await p.page.eval_on_selector(".cp-list", "e => e.scrollTop = 0")
    check(len(await ticked(p)) >= 2, f"after scrolling: {await ticked(p)}", problems)
    q = ".cpick input[placeholder='Search by name or number']"
    t = time.time()
    await p.page.fill(q, "chitra 01"); await p.page.wait_for_timeout(50)
    await p.page.wait_for_function("document.querySelectorAll('.cp-row:not([hidden])').length < 3000")
    searched = time.time() - t
    await p.page.fill(q, "")
    print(f"      (3,009 contacts: picker open {opened*1000:.0f} ms, tap {tapped*1000:.0f} ms, search {searched*1000:.0f} ms)")
    check(opened < 3, f"opening took {opened:.1f}s", problems)
    check(searched < 1.5, f"search took {searched:.1f}s", problems)
    return problems


async def s_permission_refused_falls_back(br):
    p = await Phone.open(br, "Asha", "+91" + fresh_owner(), init=bridge(BOOK, answer="!"))
    await new_group_dialog(p); await open_picker(p)
    problems = []
    check("access to your contacts" in await p.page.text_content(".cpick"), "no explanation shown", problems)
    await p.page.click(".cpick button:has-text('Pick one contact instead')")
    await p.page.wait_for_timeout(300)
    check(await p.page.evaluate("window.__singles") == 1, "phone's own picker not opened", problems)
    check([m[0] for m in await dialog_members(p)] == ["Asha", "Anu"], str(await dialog_members(p)), problems)
    return problems


async def s_regression_older_bridge_single_flow(br):
    """An APK without the new bridge methods: Contacts is the one-at-a-time
    picker, exactly as before, and Create group still works end to end."""
    p = await Phone.open(br, "Asha", "+91" + fresh_owner(), init=bridge(BOOK, with_multi=False))
    await new_group_dialog(p, "Old way")
    await p.page.click("#modalRoot button:has-text('Contacts')")
    await p.page.wait_for_timeout(300)
    problems = []
    check(not await p.page.is_visible(".cpick"), "new picker shown on an old bridge", problems)
    check([m[0] for m in await dialog_members(p)] == ["Asha", "Anu"], str(await dialog_members(p)), problems)
    await p.page.click("#modalRoot button:has-text('Create group')")
    await p.sync()
    check(await p.live() == ["Old way"], f"live {await p.live()}", problems)
    return problems


SCENARIOS = [s_acceptance_three_contacts_then_create, s_t1_one_contact, s_t3_toggle,
             s_t4_search_keeps_selection, s_t5_duplicates, s_t6_chip_removal,
             s_t7_cancel_and_back_add_nothing, s_t8_existing_member_and_manual_entry,
             s_t9_same_name, s_t10_large_book, s_permission_refused_falls_back,
             s_regression_older_bridge_single_flow]


async def main():
    ok = True
    async with async_playwright() as pw:
        for fn in SCENARIOS:
            name = fn.__name__[2:]
            if ONLY and name not in ONLY:
                continue
            br = await pw.chromium.launch()
            try:
                problems = await fn(br)
            except Exception as e:                       # noqa: BLE001
                problems = [f"{type(e).__name__}: {str(e).splitlines()[0]}"]
            await br.close()
            ok &= not problems
            print(f"{'PASS' if not problems else 'FAIL'}  {name:42s} " + ("; ".join(problems) or "ok"), flush=True)
    print("ALL PASS" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


asyncio.run(main())
