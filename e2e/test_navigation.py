"""End to end: the bottom navigation bar.

Real phone page (the APK's own, including its Back-button history handling)
against a real local server, at several screen widths.

    ./run.sh nav
"""
import asyncio
import random
import sys

from playwright.async_api import async_playwright

from harness import Phone

ONLY = sys.argv[1].split(",") if len(sys.argv) > 1 else None
BASE = random.randint(100, 899)
_n = [0]
SECTIONS = ["home", "groups", "analytics", "bills", "balances"]


def number():
    _n[0] += 1
    return "+919%03d%02d0001" % (BASE, _n[0])


async def add_expense(p, gid, desc, amount):
    await p.app("""([gid, desc, amount]) => {
      const g = S.groups.find(x => x.id === gid);
      const ids = g.members.filter(m => !m.deleted).map(m => m.id);
      const me = g.members.find(m => m.phone === myPhone());
      const per = Math.floor(amount / ids.length); const splits = {};
      ids.forEach((id, i) => splits[id] = per + (i === 0 ? amount - per * ids.length : 0));
      saveExpense({ id: uid("e"), gid, description: desc, amount, category: "Food & drink",
        date: todayStr(), splitType: "equal", paidBy: me.id, payers: { [me.id]: amount }, splits, values: {} });
    }""", [gid, desc, amount])


async def setup(br, width=412, height=915, expenses=2):
    a = await Phone.open(br, "Sherin", number())
    await a.page.set_viewport_size({"width": width, "height": height})
    g1 = await a.create_group("App development", [["Suthan", "9811100002"], ["Murali", "9811100003"]])
    for i in range(expenses):
        await add_expense(a, g1, f"Bill {i + 1}", 30000 + i * 100)
    g2 = await a.create_group("Sirsi trip", [["Murali", "9811100003"]])
    await add_expense(a, g2, "Bus", 145000)
    await a.sync()
    await a.reload()                                    # a fresh launch
    return a, g1, g2


async def tap(p, sec):
    await p.page.click(f"#bnav button[data-sec='{sec}']")
    await p.page.wait_for_timeout(120)


async def state(p):
    return await p.page.evaluate("""() => {
      const cur = [...document.querySelectorAll('#bnav button[aria-current="page"]')].map(b => b.dataset.sec);
      return { active: cur, bars: document.querySelectorAll('#bnav').length,
               buttons: document.querySelectorAll('#bnav button').length,
               title: document.getElementById('groupName').textContent,
               view: document.getElementById('view').innerText };
    }""")


def check(cond, msg, problems):
    if not cond:
        problems.append(msg)


EXPECT = {     # what each section must show, from the screens that already existed
    "home": ["Recent groups", "Owed to you"],
    "groups": ["App development", "Sirsi trip"],
    "analytics": [],                                  # filled per test (group-specific)
    "bills": ["Bill 1"],
    "balances": ["Across your groups", "Your position in"],
}


async def s_sections_individually(br):
    """Tests 1–5: launch on Home; each tab selects itself and shows its screen."""
    a, g1, g2 = await setup(br)
    await a.app(f"() => selectGroup('{g1}')")
    problems = []
    st = await state(a)
    check(st["active"] == ["home"], f"on launch active={st['active']}", problems)
    check("Recent groups" in st["view"], "Home content missing on launch", problems)
    for sec in SECTIONS:
        await tap(a, sec)
        st = await state(a)
        check(st["active"] == [sec], f"{sec}: active={st['active']}", problems)
        for text in EXPECT[sec]:
            check(text.lower() in st["view"].lower(), f"{sec}: '{text}' not shown", problems)
        if sec == "analytics":
            check("No numbers to chart yet" not in st["view"] and len(st["view"]) > 40,
                  "analytics shows nothing for a group with expenses", problems)
        if sec in ("analytics", "bills", "balances"):
            check(st["title"] == "App development", f"{sec}: title {st['title']!r}", problems)
        aria = await a.page.get_attribute(f"#bnav button[data-sec='{sec}']", "aria-current")
        check(aria == "page", f"{sec}: no aria-current for screen readers", problems)
    return problems


async def s_switch_repeatedly(br):
    """Test 6: Home Groups Analytics Bills Balances Home Groups, then 40 random taps."""
    a, g1, g2 = await setup(br)
    problems = []
    seq = ["home", "groups", "analytics", "bills", "balances", "home", "groups"]
    rng = random.Random(3)
    seq += [rng.choice(SECTIONS) for _ in range(40)]
    errors = []
    a.page.on("pageerror", lambda e: errors.append(str(e)))
    for sec in seq:
        await tap(a, sec)
        st = await state(a)
        if st["active"] != [sec] or st["bars"] != 1 or st["buttons"] != 5:
            problems.append(f"after {sec}: {st['active']} bars={st['bars']} buttons={st['buttons']}")
            break
        if sec == "home" and st["view"].count("Recent groups") != 1:
            problems.append("Home content duplicated"); break
    check(not errors, f"page errors: {errors}", problems)
    syncs_before = a.syncs
    for sec in SECTIONS * 3:
        await tap(a, sec)
    check(a.syncs - syncs_before <= 3, f"switching tabs made {a.syncs - syncs_before} server calls", problems)
    return problems


async def s_group_detail(br):
    """Groups → App development → Balances → Groups → (still open) → list → Sirsi."""
    a, g1, g2 = await setup(br)
    problems = []
    await tap(a, "groups")
    await a.page.click(".gcard:has-text('App development') .open")
    st = await state(a)
    check(st["active"] == ["groups"], f"in detail active={st['active']}", problems)
    check(st["title"] == "App development", f"detail title {st['title']!r}", problems)
    check(await a.page.is_visible("#tabs .tab:has-text('Activity')"), "group's own tabs missing in detail", problems)
    await tap(a, "balances")
    st = await state(a)
    check(st["active"] == ["balances"] and st["title"] == "App development", f"balances: {st['active']} {st['title']}", problems)
    await tap(a, "groups")
    st = await state(a)
    check(st["title"] == "App development", "returning to Groups lost the open group", problems)
    await tap(a, "groups")                                   # tap again: back to the list
    st = await state(a)
    check(st["title"] == "Groups", f"second tap on Groups: {st['title']!r}", problems)
    await a.page.click(".gcard:has-text('Sirsi trip') .open")
    st = await state(a)
    check(st["title"] == "Sirsi trip" and st["active"] == ["groups"], f"opening Sirsi: {st}", problems)
    await tap(a, "bills")
    check("Bus" in (await state(a))["view"], "Bills did not follow the opened group", problems)
    return problems


async def s_back_button(br):
    """Android Back (history.back in the WebView): detail → list → Home → (exit)."""
    a, g1, g2 = await setup(br)
    problems = []
    await tap(a, "groups")
    await a.page.click(".gcard:has-text('App development') .open")
    await a.page.go_back(); await a.page.wait_for_timeout(250)
    st = await state(a)
    check(st["title"] == "Groups" and st["active"] == ["groups"], f"Back from detail: {st['title']} {st['active']}", problems)
    await a.page.go_back(); await a.page.wait_for_timeout(250)
    st = await state(a)
    check(st["active"] == ["home"], f"Back from Groups: {st['active']}", problems)
    can = await a.page.evaluate("history.length")
    # From Home the app has nothing left to unwind, so Android's Back exits.
    stack = await a.page.evaluate("typeof backStack === 'undefined' ? -1 : backStack.length")
    check(stack in (0, -1), f"history entries left on Home: {stack}", problems)
    # Bills → Back → Home; a dialog on top closes first
    await tap(a, "bills")
    await a.page.click(".topbar button:has-text('Add expense')")
    await a.page.wait_for_selector("#modalRoot .modal")
    await a.page.go_back(); await a.page.wait_for_timeout(250)
    check(not await a.page.is_visible("#modalRoot .modal"), "Back did not close the dialog first", problems)
    check((await state(a))["active"] == ["bills"], "Back from a dialog left Bills", problems)
    await a.page.go_back(); await a.page.wait_for_timeout(250)
    check((await state(a))["active"] == ["home"], "Back from Bills did not go Home", problems)
    # tab-hopping does not pile up history: one Back from anywhere is Home
    for sec in ["groups", "bills", "analytics", "balances", "bills"]:
        await tap(a, sec)
    await a.page.go_back(); await a.page.wait_for_timeout(250)
    check((await state(a))["active"] == ["home"], f"after hopping, Back went to {(await state(a))['active']}", problems)
    await a.page.wait_for_timeout(300)
    hist = await a.page.evaluate("({ stack: window.__t('backStack.length'), pend: window.__t('pendingPops'), url: location.href })")
    check(hist["stack"] == 0 and hist["pend"] == 0 and hist["url"].endswith("/index.html"), f"back history out of step: {hist}", problems)
    return problems


async def s_fixed_while_scrolling_and_nothing_hidden(br):
    """The bar stays put while a long list scrolls, and the last item can be
    scrolled clear of it."""
    a, g1, g2 = await setup(br, expenses=30)
    await a.app(f"() => selectGroup('{g1}')")
    await tap(a, "bills")
    problems = []
    before = await a.page.eval_on_selector("#bnav", "e => e.getBoundingClientRect().top")
    await a.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await a.page.wait_for_timeout(150)
    after = await a.page.eval_on_selector("#bnav", "e => e.getBoundingClientRect().top")
    vh = await a.page.evaluate("innerHeight")
    check(abs(before - after) < 1, f"bar moved while scrolling: {before} → {after}", problems)
    check(after > vh - 100, f"bar not at the bottom: top={after}, viewport={vh}", problems)
    last = await a.page.evaluate("""() => { const rows = document.querySelectorAll('#view .lrow, #view .xrow, #view [data-eid]');
        const all = document.querySelectorAll('#view *'); let el = null;
        for (const n of all) { if (n.offsetParent && n.textContent.trim() && !n.children.length) el = n; }
        return el ? el.getBoundingClientRect().bottom : 0; }""")
    check(last <= after + 0.5, f"last item ends at {last}, under the bar at {after}", problems)
    return problems


async def s_screen_sizes(br):
    """412, 360, 320 and 280 px wide (280 is a 360dp phone at its largest
    display size). Nothing overlaps, nothing scrolls sideways."""
    problems = []
    for w, h in [(412, 915), (360, 780), (320, 640), (280, 600)]:
        a, g1, g2 = await setup(br, width=w, height=h, expenses=1)
        for sec in SECTIONS:
            await tap(a, sec)
            m = await a.page.evaluate("""() => {
              const nav = document.getElementById('bnav'), r = nav.getBoundingClientRect();
              const btns = [...nav.querySelectorAll('button')].map(b => b.getBoundingClientRect());
              const lbls = [...nav.querySelectorAll('.lbl')];
              let overlap = false;
              for (let i = 1; i < btns.length; i++) if (btns[i].left < btns[i-1].right - 0.5) overlap = true;
              const minTap = Math.min(...btns.map(b => Math.min(b.width, b.height)));
              const clipped = lbls.filter(l => l.scrollWidth > l.clientWidth + 1).map(l => l.textContent);
              return { navW: r.width, vw: innerWidth, sideScroll: document.documentElement.scrollWidth > innerWidth + 1,
                       overlap, minTap, clipped, bottom: r.bottom, vh: innerHeight };
            }""")
            tag = f"{w}px {sec}"
            check(abs(m["navW"] - m["vw"]) < 1, f"{tag}: bar is {m['navW']} wide of {m['vw']}", problems)
            check(not m["sideScroll"], f"{tag}: page scrolls sideways", problems)
            check(not m["overlap"], f"{tag}: nav items overlap", problems)
            check(m["minTap"] >= 44, f"{tag}: tap target only {m['minTap']:.0f}px", problems)
            check(not m["clipped"], f"{tag}: labels cut off {m['clipped']}", problems)
            check(abs(m["bottom"] - m["vh"]) < 1, f"{tag}: bar not on the bottom edge", problems)
        await a.ctx.close()
    return problems


async def s_overlays_cover_the_bar(br):
    """Dialogs, the drawer and the passcode screen sit above the bar, so a
    half-finished expense can't be abandoned by tapping a tab."""
    a, g1, g2 = await setup(br)
    problems = []
    await tap(a, "bills")
    await a.page.click(".topbar button:has-text('Add expense')")
    top = await a.page.evaluate("""() => { const r = document.getElementById('bnav').getBoundingClientRect();
        const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return el.closest('#bnav') ? 'bnav' : 'covered'; }""")
    check(top == "covered", "the bar can be tapped through an open dialog", problems)
    await a.page.click("#modalRoot button:has-text('Cancel')")
    await a.page.click("#railBtn")
    await a.page.wait_for_timeout(300)
    left = await a.page.evaluate("""() => { const el = document.elementFromPoint(40, innerHeight - 30);
        return el.closest('#bnav') ? 'bnav' : (el.closest('#rail') ? 'rail' : 'other'); }""")
    check(left == "rail", f"drawer does not cover the bar: {left}", problems)
    return problems


async def s_drawer_still_works(br):
    """The drawer keeps its groups, New group, Account/sync status, passcode,
    backup and theme; picking a group there switches what Bills shows."""
    a, g1, g2 = await setup(br)
    problems = []
    await tap(a, "bills")
    await a.page.click("#railBtn")
    await a.page.wait_for_timeout(250)
    for sel, what in [("#newGroupBtn", "New group"), ("#syncBar", "sync status"), ("#themeBtn", "theme"),
                      ("#backupBtn", "backup"), ("#groupList .gitem", "group list")]:
        check(await a.page.locator(sel).count() > 0, f"drawer lost {what}", problems)
    check("Synced" in (await a.page.text_content("#syncBar") or ""), "sync status not shown in the drawer", problems)
    await a.page.click("#groupList .gitem:has-text('Sirsi trip')")
    await a.page.wait_for_timeout(250)
    st = await state(a)
    check(st["active"] == ["bills"] and st["title"] == "Sirsi trip", f"drawer pick: {st['active']} {st['title']}", problems)
    check("Bus" in st["view"], "Bills did not switch group", problems)
    await tap(a, "home")
    # 3.13: sync status and Account live in the drawer only, not on Home
    view = await a.page.text_content("#view")
    check(await a.page.locator("#homeStatus").count() == 0 and "Account" not in view and "Synced" not in view,
          "Home still shows the sync/Account row", problems)
    return problems


SCENARIOS = [s_sections_individually, s_switch_repeatedly, s_group_detail, s_back_button,
             s_fixed_while_scrolling_and_nothing_hidden, s_screen_sizes, s_overlays_cover_the_bar,
             s_drawer_still_works]


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
