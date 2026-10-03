"""End to end: being added to a group before you have the app.

Each scenario uses real phone pages (the APK's own page) against a real local
server. The late joiner is always a brand-new install — empty storage — that
signs in through the real sign-in screen. Nothing is copied between phones:
whatever the late joiner sees came from the server.

    ./run.sh late            (run.sh starts the server and the page host)
"""
import asyncio
import os
import random
import subprocess
import sys
import time

from playwright.async_api import async_playwright

from harness import Phone

HERE = os.path.dirname(os.path.abspath(__file__))
ONLY = sys.argv[1].split(",") if len(sys.argv) > 1 else None
BASE = random.randint(100, 899)           # fresh numbers on every run
_n = [0]


def numbers(k):
    """k unused 10-digit Indian mobile numbers."""
    _n[0] += 1
    return ["9%03d%02d%04d" % (BASE, _n[0], i) for i in range(1, k + 1)]


def spaced(n):                 # "98765 43210"
    return n[:5] + " " + n[5:]


async def until(fn, seconds, every=0.25):
    end = time.time() + seconds
    while time.time() < end:
        v = await fn()
        if v:
            return v
        await asyncio.sleep(every)
    return await fn()


async def owner(browser, number, name="Asha"):
    return await Phone.open(browser, name, "+91" + number)


async def add_expense(p, gid, desc, amount):
    await p.app("""([gid, desc, amount]) => {
      const g = S.groups.find(x => x.id === gid);
      const me = g.members.find(m => m.phone === myPhone());
      saveExpense({ id: uid("e"), gid, description: desc, amount, category: "Other",
        date: "2026-10-01", splitType: "equal", paidBy: me.id, payers: { [me.id]: amount },
        splits: { [me.id]: amount }, values: {} });
    }""", [gid, desc, amount])


async def readd(p, gid, name, number):
    await p.app("""([gid, n, ph]) => { const g = S.groups.find(x => x.id === gid);
      g.members.push({ id: uid("m"), name: n, phone: ph, updatedAt: nowISO() }); saveGroup(g); }""",
                [gid, name, "+91" + number])


def check(cond, msg, problems):
    if not cond:
        problems.append(msg)


# ------------------------------------------------------------------ scenarios


async def s_exact_late_install(br):
    """The acceptance scenario, word for word."""
    a_num, b_num = numbers(2)
    a = await owner(br, a_num)
    gid = await a.create_group("Goa Trip", [["Bala", spaced(b_num)]])   # B has no app
    await add_expense(a, gid, "Villa deposit", 1200000)
    await a.sync()
    await asyncio.sleep(3)                                              # time passes
    b = await Phone.install(br, "Bala", "+91 " + spaced(b_num))         # B installs now

    seen_empty = False
    async def arrived():
        nonlocal seen_empty
        # Only what is on screen once the sign-in screen has closed.
        behind = await b.page.evaluate("!document.getElementById('authScreen').hidden")
        if not behind and "Start your first group" in await b.text():
            seen_empty = True
        return await b.live()
    got = await until(arrived, 15, every=0.1)
    problems = []
    check(got == ["Goa Trip"], f"B shows {got}", problems)
    check(not seen_empty, "B was told to start a first group before the server answered", problems)
    exps = await b.app("() => S.expenses.filter(e => !e.deleted).map(e => e.description)")
    check(exps == ["Villa deposit"], f"B's expenses {exps}", problems)
    mine = await b.app("() => S.groups[0].members.filter(m => m.phone === myPhone()).length")
    check(mine == 1, f"B appears {mine} times in the member list", problems)
    # repeatable: sync, sync, reopen
    await b.sync(); await b.sync(); await b.reload(); await b.page.wait_for_timeout(2500)
    check(await b.live() == ["Goa Trip"], "repeat syncs / reopen changed the list", problems)
    check(await b.app("() => S.groups.length") == 1, "duplicate group rows", problems)
    return problems


async def s_four_groups(br):
    a_num, b_num = numbers(2)
    a = await owner(br, a_num)
    names = ["Goa Trip", "Chennai Trip", "Family Expenses", "Office Dinner"]
    for n in names:
        await a.create_group(n, [["Bala", b_num]])
    await a.sync()
    b = await Phone.install(br, "Bala", b_num)
    got = await until(lambda: _sorted_live(b, 4), 15)
    return [] if got == sorted(names) else [f"B shows {got}"]


async def _sorted_live(p, want):
    v = sorted(await p.live())
    return v if len(v) >= want else None


async def s_membership_matrix(br):
    """A: Asha, Bala, Chitra.  B: Bala, Dev.  C: Chitra, Dev."""
    a_num, b_num, c_num, d_num = numbers(4)
    a = await owner(br, a_num)
    d = await owner(br, d_num, "Dev")
    await a.create_group("Group A", [["Bala", b_num], ["Chitra", c_num]])
    await d.create_group("Group B", [["Bala", b_num]])
    await d.create_group("Group C", [["Chitra", c_num]])
    await a.sync(); await d.sync()
    b = await Phone.install(br, "Bala", b_num)
    got = await until(lambda: _sorted_live(b, 2), 15)
    await b.page.wait_for_timeout(1500)
    got = sorted(await b.live())
    known = await b.app("() => S.groups.map(g => g.name).sort()")
    problems = []
    check(got == ["Group A", "Group B"], f"B shows {got}", problems)
    check("Group C" not in known, "Group C reached B's phone at all", problems)
    return problems


async def s_server_restart(br):
    a_num, b_num = numbers(2)
    a = await owner(br, a_num)
    await a.create_group("Goa Trip", [["Bala", b_num]])
    await a.sync()
    await a.ctx.close()
    subprocess.run([os.path.join(HERE, "api.sh"), "restart"], check=True)   # new process, same DB
    b = await Phone.install(br, "Bala", b_num)
    got = await until(b.live, 15)
    return [] if got == ["Goa Trip"] else [f"after a server restart B shows {got}"]


async def s_server_asleep_at_first_sign_in(br):
    """Render free tier: the first requests hang and fail for ~45s while it
    wakes. B must never be told there are no groups, must not be told they
    were signed out, and the group must arrive once the server is up."""
    a_num, b_num = numbers(2)
    a = await owner(br, a_num)
    await a.create_group("Goa Trip", [["Bala", b_num]])
    await a.sync()
    b = await Phone.install(br, "Bala", b_num, asleep_for=45)
    t0 = time.time()
    screens = set()
    got = []
    while time.time() - t0 < 120:
        if await b.page.evaluate("!document.getElementById('authScreen').hidden"):
            await asyncio.sleep(0.5)
            continue
        txt = await b.text()
        for marker in ("Start your first group", "Finding your groups", "Waiting for the server"):
            if marker in txt:
                screens.add(marker)
        got = await b.live()
        if got:
            break
        await asyncio.sleep(0.5)
    took = time.time() - t0
    toasts = [t["m"] for t in await b.page.evaluate("window.__toasts")]
    problems = []
    check(got == ["Goa Trip"], f"B shows {got} after {took:.0f}s", problems)
    check("Start your first group" not in screens, "B was told to start a first group while the server slept", problems)
    check(screens & {"Finding your groups", "Waiting for the server"}, f"no waiting state shown: {screens}", problems)
    check(not any("Signed out" in m for m in toasts), f"told 'signed out': {toasts}", problems)
    check(took < 45 + 40, f"took {took:.0f}s after the server woke at 45s", problems)
    print(f"      (group arrived {took:.0f}s after tapping Continue; server woke at 45s; screens {sorted(screens)})")
    return problems


async def s_deleted_before_install(br):
    a_num, b_num = numbers(2)
    a = await owner(br, a_num)
    gid = await a.create_group("Group X", [["Bala", b_num]])
    await a.sync()
    await a.delete_for_everyone(gid); await a.sync()
    b = await Phone.install(br, "Bala", b_num)
    await b.page.wait_for_timeout(4000)
    problems = []
    check(await b.live() == [], f"B shows {await b.live()}", problems)
    check("Start your first group" in await b.text(), "after the server answered, B should be offered to start a group", problems)
    return problems


async def s_removed_before_install(br):
    a_num, b_num = numbers(2)
    a = await owner(br, a_num)
    gid = await a.create_group("Group X", [["Bala", b_num]])
    await a.sync()
    await a.remove_member(gid, "+91" + b_num); await a.sync()
    b = await Phone.install(br, "Bala", b_num)
    await b.page.wait_for_timeout(4000)
    return [] if await b.live() == [] else [f"B shows {await b.live()}"]


async def _b_with_group_x(br):
    a_num, b_num = numbers(2)
    a = await owner(br, a_num)
    gid = await a.create_group("Group X", [["Bala", b_num]])
    await a.sync()
    b = await Phone.install(br, "Bala", b_num)
    assert await until(b.live, 15) == ["Group X"]
    return a, b, gid, a_num, b_num


async def s_hidden_stays_hidden(br):
    """Tests 7, 8, 9: removed from view → sync, another group, app restart,
    and a second fresh install with the same number."""
    a, b, gid, a_num, b_num = await _b_with_group_x(br)
    await b.hide(gid); await b.sync(); await b.sync()
    problems = []
    check(await b.live() == [], "test 7: came back after syncing", problems)
    await b.create_group("Group Y", [["Asha", a_num]]); await b.sync()
    await a.create_group("Group Z", [["Bala", b_num]]); await a.sync()
    await b.page.wait_for_timeout(3000)
    check(sorted(await b.live()) == ["Group Y", "Group Z"], f"test 8: B shows {await b.live()}", problems)
    await b.reload(); await b.page.wait_for_timeout(3000)
    check(sorted(await b.live()) == ["Group Y", "Group Z"], f"test 9 (restart): B shows {await b.live()}", problems)
    b2 = await Phone.install(br, "Bala", b_num)
    got = await until(lambda: _sorted_live(b2, 2), 15)
    await b2.page.wait_for_timeout(1500)
    check(sorted(await b2.live()) == ["Group Y", "Group Z"], f"test 9 (reinstall): B shows {await b2.live()}", problems)
    return problems


async def s_removed_then_added_back(br):
    """Test 10 and the owner re-add cycle, with B's app open throughout."""
    a, b, gid, a_num, b_num = await _b_with_group_x(br)
    problems = []
    await a.remove_member(gid, "+91" + b_num); await a.sync()
    gone = await until(lambda: _is_empty(b), 25)
    check(gone, f"after removal B still shows {await b.live()}", problems)
    toasts = [t["m"] for t in await b.page.evaluate("window.__toasts")]
    check(any("no longer in “Group X”" in m for m in toasts), f"B was not told: {toasts}", problems)
    await add_expense(a, gid, "Dinner while Bala was out", 300000); await a.sync()
    await a.create_group("Another trip", [["Bala", b_num]]); await a.sync()   # moves B's cursor
    await b.page.wait_for_timeout(3000)
    await readd(a, gid, "Bala", b_num); await a.sync()
    back = await until(lambda: _has(b, "Group X"), 25)
    check(back, f"after re-adding B shows {await b.live()}", problems)
    await b.page.wait_for_timeout(2000)
    exps = await b.app(f"() => S.expenses.filter(e => e.gid === '{gid}' && !e.deleted).map(e => e.description)")
    check("Dinner while Bala was out" in exps, f"history written while out is missing: {exps}", problems)
    return problems


async def s_hidden_then_removed_then_added_back(br):
    """The server's rule: being added back cancels an earlier removal from
    view. The phone must follow it rather than re-hide the group."""
    a, b, gid, a_num, b_num = await _b_with_group_x(br)
    await b.hide(gid); await b.sync()
    await a.remove_member(gid, "+91" + b_num); await a.sync()
    await b.page.wait_for_timeout(3000)
    await readd(a, gid, "Bala", b_num); await a.sync()
    back = await until(lambda: _has(b, "Group X"), 25)
    await b.page.wait_for_timeout(2000)
    problems = []
    check(back, f"after re-adding B shows {await b.live()}", problems)
    check(await b.live() == ["Group X"], f"re-hidden afterwards: {await b.live()}", problems)
    return problems


async def _is_empty(p):
    return (await p.live()) == []


async def _has(p, name):
    return name in await p.live()


async def s_logout_login_and_account_switch(br):
    a, b, gid, a_num, b_num = await _b_with_group_x(br)
    c_num = numbers(1)[0]
    await a.create_group("Chitra's own", [["Chitra", c_num]]); await a.sync()
    problems = []
    # same number out and back in
    await b.app("() => signOut()")
    await b.app("([m, n]) => signIn(m, n)", ["+91" + b_num, "Bala"])
    await b.sync(); await b.page.wait_for_timeout(1000)
    check(await b.live() == ["Group X"], f"same number back in: {await b.live()}", problems)
    # a different number on the same phone
    await b.app("() => signOut()")
    await b.app("([m, n]) => signIn(m, n)", ["+91" + c_num, "Chitra"])
    await b.app("() => render()")
    check("Group X" not in await b.live(), "Chitra sees Bala's cached group before syncing", problems)
    await b.sync(); await b.page.wait_for_timeout(1500)
    check(await b.live() == ["Chitra's own"], f"Chitra sees {await b.live()}", problems)
    return problems


SCENARIOS = [s_exact_late_install, s_four_groups, s_membership_matrix, s_server_restart,
             s_deleted_before_install, s_removed_before_install, s_hidden_stays_hidden,
             s_removed_then_added_back, s_hidden_then_removed_then_added_back, s_logout_login_and_account_switch,
             s_server_asleep_at_first_sign_in]


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
                problems = [f"{type(e).__name__}: {e}"]
            await br.close()
            ok &= not problems
            print(f"{'PASS' if not problems else 'FAIL'}  {name:38s} " + ("; ".join(problems) or "ok"), flush=True)
    print("ALL PASS" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


asyncio.run(main())
