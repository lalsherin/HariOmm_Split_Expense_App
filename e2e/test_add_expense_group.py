"""End to end: Home's Add expense asks which group; nothing is pre-selected.

Every expense here is entered through the real Add expense dialog (amount,
description, Add expense) and checked by which group it was saved to, on the
phone and on the server.

    ./run.sh addexp
"""
import asyncio
import random
import sys

from playwright.async_api import async_playwright

from harness import Phone

ONLY = sys.argv[1].split(",") if len(sys.argv) > 1 else None
BASE = random.randint(100, 899)
_n = [0]


def number():
    _n[0] += 1
    return "+919%03d%02d0001" % (BASE, _n[0])


async def setup(br, names=("Group A", "Group B", "Group C")):
    a = await Phone.open(br, "Sherin", number())
    ids = {}
    for i, n in enumerate(names):
        friend = number().replace("+91", "")[:-1] + str(i)     # fresh per scenario
        ids[n] = await a.create_group(n, [["Friend %d" % i, friend]])
    await a.sync()
    await a.app("() => { S.section = 'home'; render(); }")
    return a, ids


async def fill_and_save(p, desc, amount):
    """The unchanged Add expense dialog: description, amount, Add expense."""
    await p.page.wait_for_selector("#modalRoot input[placeholder^='Dinner at']")
    await p.page.fill("#modalRoot input[placeholder^='Dinner at']", desc)
    await p.page.fill("#modalRoot input[placeholder='0.00'] >> nth=0", str(amount))
    await p.page.click("#modalRoot .modal-ft button:has-text('Add expense')")
    await p.page.wait_for_selector("#modalRoot .modal", state="detached")


async def expense_group(p, desc):
    return await p.app("d => (S.expenses.find(e => e.description === d && !e.deleted) || {}).gid || null", desc)


async def global_add(p):
    await p.page.click("#bnav button[data-sec='home']")
    await p.page.click("#view .quick button:has-text('Add expense')")
    await p.page.wait_for_selector("#modalRoot .modal")
    title = (await p.page.text_content("#modalRoot .modal-hd")).strip()
    return title


async def chooser_groups(p):
    return await p.page.eval_on_selector_all("#modalRoot .pickgrp .gn", "els => els.map(e => e.textContent)")


async def pick(p, name):
    await p.page.click(f"#modalRoot .pickgrp:has(.gn:text-is('{name}'))")


async def use_group(p, gid, desc, amount):
    """Open the group (Groups → card) and add an expense from inside it."""
    await p.page.click("#bnav button[data-sec='groups']")
    if await p.page.is_visible("#detailBack"):
        await p.page.click("#detailBack")
    await p.page.click(f".gcard:has(.gn:text-is('{await p.app('id => S.groups.find(g => g.id === id).name', gid)}')) .open")
    await p.page.click(".topbar button:has-text('Add expense')")
    await fill_and_save(p, desc, amount)


def check(cond, msg, problems):
    if not cond:
        problems.append(msg)


async def s_exact_scenario(br):
    """The acceptance scenario, step by step (also tests 1, 2, 3 and 10)."""
    a, ids = await setup(br)
    problems = []
    await use_group(a, ids["Group A"], "Lunch A", 300)              # 1. use Group A
    await use_group(a, ids["Group B"], "Lunch B", 400)              # 2. use Group B
    check(await a.app("() => S.gid") == ids["Group B"], "last used is not Group B", problems)
    title = await global_add(a)                                     # 3-4. Home, global Add expense
    check(title.startswith("Select group"), f"5. opened {title!r} instead of the group choice", problems)
    check(not await a.page.is_visible("#modalRoot input[placeholder^='Dinner at']"),
          "5. the expense form opened with a group already chosen", problems)
    check(await a.page.locator("#modalRoot .pickgrp[aria-pressed='true'], #modalRoot .pickgrp.on").count() == 0,
          "5. a group is pre-selected in the chooser", problems)
    await pick(a, "Group A")                                        # 6. choose A by hand
    await fill_and_save(a, "Taxi", 250)                             # 7. create the expense
    check(await expense_group(a, "Taxi") == ids["Group A"],         # 8. it belongs to A
          f"8. saved to {await expense_group(a, 'Taxi')}, not Group A", problems)
    await a.sync()
    server = await a.page.evaluate("""async () => { const id = JSON.parse(localStorage.getItem('sl.identity'));
        const r = await fetch(JSON.parse(localStorage.getItem('sl.server')) + '/sync', { method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + id.accessToken },
          body: JSON.stringify({ since: 0, changes: {} }) });
        const d = await r.json(); const e = d.expenses.find(x => x.description === 'Taxi'); return e && e.group_id; }""")
    check(server == ids["Group A"], f"8. server has Taxi in {server}", problems)
    title = await global_add(a)                                     # 9-10. Home, global again
    check(title.startswith("Select group"), f"11. second time opened {title!r}", problems)  # 11
    await a.page.click("#modalRoot button:has-text('Cancel')")
    # The phone's Back history stays in step with what is open (3.13 fix):
    # nothing left over to swallow the next Back, and still on the app's page.
    await a.page.wait_for_timeout(300)
    hist = await a.page.evaluate("({ url: location.href, stack: window.__t('backStack.length'), pend: window.__t('pendingPops') })")
    check(hist["url"].endswith("/index.html") and hist["stack"] == 0 and hist["pend"] == 0, f"back history out of step: {hist}", problems)
    return problems


async def s_card_plus_and_group_detail_unchanged(br):
    """Tests 4 and 5: no chooser when the group is already known."""
    a, ids = await setup(br)
    problems = []
    await a.page.click(".gcard:has(.gn:text-is('Group C')) button.add")
    title = (await a.page.text_content("#modalRoot .modal-hd")).strip()
    check(not title.startswith("Select group"), f"card + asked for a group: {title!r}", problems)
    await fill_and_save(a, "Card plus", 120)
    check(await expense_group(a, "Card plus") == ids["Group C"], "card + saved to the wrong group", problems)
    await use_group(a, ids["Group B"], "Inside B", 90)
    check(await expense_group(a, "Inside B") == ids["Group B"], "in-group Add expense saved elsewhere", problems)
    await a.page.click("#bnav button[data-sec='bills']")
    await a.page.click(".topbar button:has-text('Add expense')")
    title = (await a.page.text_content("#modalRoot .modal-hd")).strip()
    check(not title.startswith("Select group"), f"Bills' Add expense asked for a group: {title!r}", problems)
    return problems


async def s_cancel_and_back(br):
    """Test 6: Cancel, Back and tapping outside open nothing and save nothing."""
    a, ids = await setup(br)
    problems = []
    count = lambda: a.app("() => S.expenses.filter(e => !e.deleted).length")
    before = await count()
    for how in ("cancel", "back", "outside"):
        await global_add(a)
        if how == "cancel":
            await a.page.click("#modalRoot button:has-text('Cancel')")
        elif how == "back":
            await a.page.go_back(); await a.page.wait_for_timeout(250)
        else:
            await a.page.mouse.click(5, 5); await a.page.wait_for_timeout(150)
        check(not await a.page.is_visible("#modalRoot .modal"), f"{how}: something is still open", problems)
        sec = await a.page.get_attribute("#bnav button[aria-current='page']", "data-sec")
        check(sec == "home", f"{how}: left Home for {sec}", problems)
    check(await count() == before, "an expense was created", problems)
    # and no group was chosen behind the scenes: the next one still asks
    title = await global_add(a)
    check(title.startswith("Select group"), "after cancelling, the next Add expense skipped the choice", problems)
    return problems


async def s_lists_exactly_the_live_groups(br):
    """Tests 7, 8, 9: all groups; not one removed from view; not a deleted one;
    and a group that arrives from the server after a late install."""
    a, ids = await setup(br, names=("Group A", "Group B", "Group C", "Group D"))
    problems = []
    await global_add(a)
    check(await chooser_groups(a) == ["Group A", "Group B", "Group C", "Group D"], f"all: {await chooser_groups(a)}", problems)
    await a.page.click("#modalRoot button:has-text('Cancel')")
    await a.hide(ids["Group B"]); await a.sync()                    # removed from my view
    await a.delete_for_everyone(ids["Group D"]); await a.sync()     # deleted for everyone
    await global_add(a)
    check(await chooser_groups(a) == ["Group A", "Group C"], f"after remove/delete: {await chooser_groups(a)}", problems)
    await a.page.click("#modalRoot button:has-text('Cancel')")
    # Bala was added to Group A by number and installs later: his chooser comes from the server
    friend = await a.app("id => S.groups.find(g => g.id === id).members.find(m => m.phone !== myPhone()).phone", ids["Group A"])
    b = await Phone.install(br, "Friend", friend)
    for _ in range(40):
        if await b.live():
            break
        await asyncio.sleep(0.25)
    if await b.page.is_visible("#lockScreen button:has-text('Not now')"):
        await b.page.click("#lockScreen button:has-text('Not now')")
    await global_add(b)
    check(await chooser_groups(b) == ["Group A"], f"late install sees {await chooser_groups(b)}", problems)
    return problems


async def s_same_names_and_many_groups(br):
    """Picking goes by id, so two groups with one name stay apart; with more
    than six groups there is a search box."""
    names = ("Trip", "Trip", "Flat", "Office", "Family", "Gym", "Cricket", "Book club")
    a, _ = await setup(br, names=names)
    problems = []
    ids = await a.app("() => liveGroups().filter(g => g.name === 'Trip').map(g => g.id)")
    await global_add(a)
    await a.page.locator("#modalRoot .pickgrp:has(.gn:text-is('Trip'))").nth(1).click()
    await fill_and_save(a, "Second trip", 75)
    got = await expense_group(a, "Second trip")
    shown = await a.app("() => liveGroups().filter(g => g.name === 'Trip').map(g => g.id)")
    check(got == shown[1], f"saved to {got}, expected the second Trip {shown[1]}", problems)
    await global_add(a)
    check(await a.page.is_visible("#modalRoot input[placeholder='Search groups']"), "no search with 8 groups", problems)
    await a.page.fill("#modalRoot input[placeholder='Search groups']", "fla")
    vis = await a.page.eval_on_selector_all("#modalRoot .pickgrp:not([hidden]) .gn", "els => els.map(e => e.textContent)")
    check(vis == ["Flat"], f"search 'fla' shows {vis}", problems)
    return problems


async def s_home_has_no_sync_row_drawer_does(br):
    a, ids = await setup(br)
    problems = []
    view = await a.page.text_content("#view")
    check("Synced" not in view and "Account" not in view, "Home still has the sync/Account row", problems)
    first = await a.page.evaluate("document.querySelector('#view .home').firstElementChild.className")
    check(first == "tiles", f"Home starts with {first!r}, not the summary cards", problems)
    await a.page.click("#railBtn"); await a.page.wait_for_timeout(250)
    bar = await a.page.text_content("#syncBar")
    check("Synced" in bar and "Account" in bar, f"drawer row: {bar!r}", problems)
    await a.page.click("#syncBar button:has-text('Account')")
    await a.page.wait_for_selector("#modalRoot .modal")
    check("Connection check" in await a.page.text_content("#modalRoot .modal"), "Account dialog lost Connection check", problems)
    return problems


SCENARIOS = [s_exact_scenario, s_card_plus_and_group_detail_unchanged, s_cancel_and_back,
             s_lists_exactly_the_live_groups, s_same_names_and_many_groups, s_home_has_no_sync_row_drawer_does]


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
            print(f"{'PASS' if not problems else 'FAIL'}  {name:40s} " + ("; ".join(problems) or "ok"), flush=True)
    print("ALL PASS" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


asyncio.run(main())
