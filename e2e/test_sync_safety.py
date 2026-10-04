"""End to end: a group never disappears because of a sync, network, sign-in or
server problem (3.17).

The real phone build against a real local server, taken down, brought back
(with and without its data), answering with errors, empty lists and garbage,
or unreachable for one phone only. In every case the group must still be on
the phone — in storage AND on screen — and "Synced" must only appear once the
server has really confirmed it. Real removals (owner deletes, owner takes you
out, you remove it from your own view) must still work.

    ./run.sh syncsafety
    python3 test_sync_safety.py exact_online_offline_online      # one only
"""
import asyncio
import os
import random
import subprocess
import sys

from playwright.async_api import async_playwright

from harness import Phone, SERVER

ONLY = sys.argv[1].split(",") if len(sys.argv) > 1 else None
BASE = random.randint(100, 899)
_n = [0]
NAME = "Oct 04, 7.11pm"


def number():
    _n[0] += 1
    return "+919%03d%02d%04d" % (BASE, _n[0] % 100, random.randint(1000, 9999))


def api(cmd, db=None):
    env = dict(os.environ)
    if db:
        env["E2E_DB"] = db
    subprocess.run(["./api.sh", cmd], check=True, env=env)


def check(cond, msg, problems):
    if not cond:
        problems.append(msg)


async def until(fn, secs=40):
    for _ in range(int(secs * 4)):
        if await fn():
            return True
        await asyncio.sleep(0.25)
    return False


async def state(p):
    """What is stored, what is on screen, what is waiting, what the bar says."""
    return await p.page.evaluate("""() => {
      const t = window.__t;
      const stored = JSON.parse(localStorage.getItem('sl.groups') || '[]');
      return {
        stored: stored.filter(g => !g.revoked && !g.deleted).map(g => g.name),
        aside: stored.filter(g => g.revoked).map(g => g.name),
        ui: t('liveGroups().map(g => g.name)'),
        drawer: Array.from(document.querySelectorAll('#rail .gn, #rail .rg-name, #rail [data-gid]')).length,
        pending: t('(d => d.groups.length + d.expenses.length + d.settlements.length)(dirtySet())'),
        sync: t('SYNC.state'),
        bar: ((document.querySelector('#syncBar') || {}).innerText || '').replace('Account', '').trim()
      };
    }""")


async def on_server(p, name):
    """Does the server have this group for this account? (asked directly)"""
    return await p.page.evaluate("""async (name) => {
      const id = JSON.parse(localStorage.getItem('sl.identity'));
      const r = await fetch(JSON.parse(localStorage.getItem('sl.server')) + '/sync', { method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + id.accessToken },
        body: JSON.stringify({ since: 0, changes: {} }) });
      const d = await r.json();
      return (d.groups || []).some(g => g.name === name && !g.deleted);
    }""", name)


async def make_group(p, name, friend_phone=None, amount=130000):
    """A group with Rahul and one expense (Rahul paid ₹1,300 for me), as the app makes them."""
    return await p.app("""([name, amount, friend]) => {
      const me = myIdentity();
      const g = { id: uid("g"), name, currency: "INR", createdAt: nowISO(), ownerId: myUserId(), members: [] };
      const row = { id: uid("m"), name: me.name, phone: me.mobile, updatedAt: nowISO() };
      g.members.push(row); LS.set(meKey(g.id), row.id);
      const f = { id: uid("m"), name: "Rahul", phone: friend, updatedAt: nowISO() };
      g.members.push(f);
      saveGroup(g); selectGroup(g.id);
      saveExpense({ id: uid("e"), gid: g.id, description: "Dinner", amount, category: "Food",
        date: todayStr(), splitType: "exact", paidBy: f.id, payers: { [f.id]: amount },
        splits: { [row.id]: amount }, values: {} });
      return g.id;
    }""", [name, amount, friend_phone or number()])


async def synced(p, secs=40):
    """Wait for a real, complete sync: Synced and nothing waiting."""
    await p.app("() => syncNow(true)")
    return await until(lambda: p.app("() => SYNC.state === 'ok' && !(d => d.groups.length + d.expenses.length + d.settlements.length)(dirtySet())"), secs)


async def offline(p):
    """This phone loses its connection (the server itself stays up)."""
    await p.page.route(SERVER + "/**", lambda route: route.abort("internetdisconnected"))
    await p.app("() => syncNow(true)")
    await until(lambda: p.app("() => SYNC.state === 'offline'"), 20)


async def online(p):
    await p.page.unroute(SERVER + "/**")


def kept(st, name, problems, label):
    check(name in st["stored"], f"{label}: not in storage {st}", problems)
    check(name in st["ui"], f"{label}: not on screen {st}", problems)
    check(not st["aside"], f"{label}: set aside {st['aside']}", problems)


# ---------------------------------------------------------------- scenarios

async def s_exact_online_offline_online(br):
    """The reported sequence, with the server going away and coming back."""
    p = await Phone.open(br, "Sherin", number())
    problems = []
    await make_group(p, NAME)
    check(await synced(p), "1: never synced", problems)
    st = await state(p); kept(st, NAME, problems, "1 online")
    check(st["bar"] == "Synced", f"1: bar {st['bar']!r}", problems)
    api("stop")
    await p.app("() => syncNow(true)")
    await until(lambda: p.app("() => SYNC.state === 'offline'"), 25)
    st = await state(p); kept(st, NAME, problems, "2 offline")
    check(st["bar"] == "Offline — saved here", f"2: bar {st['bar']!r}", problems)
    api("start")
    check(await synced(p, 60), "3: never synced again", problems)
    st = await state(p); kept(st, NAME, problems, "3 back online")
    check(st["bar"] == "Synced", f"3: bar {st['bar']!r}", problems)
    check(await on_server(p, NAME), "3: not on the server", problems)
    return problems


async def s_offline_group_sign_out_sign_in(br):
    """The screenshots: made offline → 'Not signed in' → signed in → 'Synced'."""
    p = await Phone.open(br, "Sherin", number())
    problems = []
    await synced(p)
    await offline(p)
    await make_group(p, NAME)
    st = await state(p); kept(st, NAME, problems, "offline")
    check(st["pending"] >= 2, f"offline: not pending {st}", problems)
    await p.page.click("#railBtn"); await p.page.wait_for_timeout(250)
    await p.page.click("#syncBar button:has-text('Account')")
    await p.page.click("#modalRoot .modal-ft button:has-text('Sign out')")
    msg = await p.page.text_content("#modalRoot .modal")
    check("haven't reached the server yet" in msg, f"sign-out warning missing: {msg!r}", problems)
    await p.page.click("#modalRoot .modal-ft button:has-text('Sign out')")
    await p.page.wait_for_timeout(800)
    st = await state(p)
    check(st["sync"] == "off" and NAME in st["stored"] and st["pending"] >= 2, f"signed out: {st}", problems)
    await online(p)
    await p.page.fill("#authPhone", p.mobile.replace("+91", ""))
    await p.page.fill("#authName", "Sherin")
    await p.page.click("#authGo")
    await p.page.wait_for_timeout(500)
    check(await synced(p, 60), "never synced after signing in", problems)
    st = await state(p); kept(st, NAME, problems, "signed in again")
    check(st["bar"] == "Synced", f"bar {st['bar']!r}", problems)
    check(await on_server(p, NAME), "never reached the server", problems)
    return problems


async def s_server_lost_its_data(br):
    """Server comes back empty (wrong/fresh database): the phone restores it."""
    p = await Phone.open(br, "Sherin", number())
    problems = []
    await make_group(p, NAME)
    await synced(p)
    api("stop")
    fresh = "/tmp/split-e2e-empty-%d.db" % random.randint(1, 10**9)
    api("start", fresh)
    try:
        check(await synced(p, 60), "never synced with the empty server", problems)
        st = await state(p); kept(st, NAME, problems, "empty server")
        check(await on_server(p, NAME), "not restored to the empty server", problems)
        exp = await p.page.evaluate("""async () => {
          const id = JSON.parse(localStorage.getItem('sl.identity'));
          const r = await fetch(JSON.parse(localStorage.getItem('sl.server')) + '/sync', { method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + id.accessToken },
            body: JSON.stringify({ since: 0, changes: {} }) });
          return (await r.json()).expenses.map(e => e.amount_minor); }""")
        check(exp == [130000], f"expenses on the restored server {exp}", problems)
    finally:
        api("stop"); api("start")
        os.path.exists(fresh) and os.remove(fresh)
    return problems


async def s_errors_never_delete(br):
    """503, 500, 401 (twice, so even signing in again fails), a timeout, a
    dropped connection, an empty 200, a non-JSON 200 and a valid answer with an
    empty list: the group stays, and only the real server's answer is Synced."""
    p = await Phone.open(br, "Sherin", number())
    problems = []
    await synced(p)
    await offline(p)
    await make_group(p, NAME)
    await online(p)
    answers = [("503", 503, '{"message":"Service waking up"}'), ("500", 500, '{"message":"boom"}'),
               ("401", 401, '{"message":"Not authenticated"}'), ("403", 403, '{"message":"Forbidden"}'),
               ("empty 200", 200, '{}'), ("non-JSON 200", 200, '<html>Render</html>'),
               ("empty list", 200, '{"seq":0,"groups":[],"members":[],"expenses":[],"settlements":[],"hidden":[],"group_ids":[]}'),
               ("timeout", None, "timedout"), ("connection reset", None, "connectionreset")]
    for label, code, body in answers:
        def make(code, body):
            async def h(route):
                if code is None:
                    await route.abort(body)
                else:
                    await route.fulfill(status=code, body=body, content_type="application/json")
            return h
        await p.page.route(SERVER + "/**", make(code, body))
        await p.app("() => syncNow(true)")
        await p.page.wait_for_timeout(200)
        st = await state(p)
        kept(st, NAME, problems, label)
        check(st["bar"] != "Synced", f"{label}: shows Synced {st}", problems)
        check(st["pending"] >= 2, f"{label}: pending changes lost {st}", problems)
        await p.page.unroute(SERVER + "/**")
    check(await synced(p, 60), "never synced with the real server", problems)
    st = await state(p); kept(st, NAME, problems, "real server")
    check(await on_server(p, NAME), "never reached the server", problems)
    return problems


async def s_cold_start(br):
    """A sleeping host: every request hangs past the app's deadline for a
    while, then the server answers. Nothing is lost, and it gets there."""
    p = await Phone.open(br, "Sherin", number())
    problems = []
    await synced(p)
    await offline(p)
    await make_group(p, NAME)
    await p.page.unroute(SERVER + "/**")
    loop = asyncio.get_event_loop()
    awake_at = loop.time() + 30

    async def sleepy(route):
        left = awake_at - loop.time()
        if left > 0:
            await asyncio.sleep(min(left, 21))
            if loop.time() < awake_at:
                return await route.abort("timedout")
        await route.continue_()
    await p.page.route(SERVER + "/**", sleepy)
    await p.app("() => syncNow(true)")
    st = await state(p); kept(st, NAME, problems, "asleep")
    check(st["bar"] != "Synced", f"asleep: Synced {st}", problems)
    check(await until(lambda: p.app("() => SYNC.state === 'ok' && !dirtySet().groups.length"), 90), "never woke up", problems)
    st = await state(p); kept(st, NAME, problems, "awake")
    await p.page.unroute(SERVER + "/**")
    check(await on_server(p, NAME), "never reached the server", problems)
    return problems


async def s_two_phones(br):
    """A makes Group A; B gets it. A goes offline and makes Group B: both stay.
    A comes back: Group B uploads, B receives it, nothing disappears."""
    a = await Phone.open(br, "Sherin", number())
    rahul = number()
    b = await Phone.open(br, "Rahul", rahul)
    problems = []
    await make_group(a, "Group A", rahul)
    await synced(a)
    check(await until(lambda: b.app("() => liveGroups().some(g => g.name === 'Group A')"), 30), "B never got Group A", problems)
    await offline(a)
    await make_group(a, "Group B", rahul)
    st = await state(a)
    check(sorted(st["ui"]) == ["Group A", "Group B"], f"A offline shows {st['ui']}", problems)
    await online(a)
    check(await synced(a, 60), "A never synced", problems)
    st = await state(a)
    check(sorted(st["ui"]) == ["Group A", "Group B"] and not st["aside"], f"A after reconnect {st}", problems)
    check(await until(lambda: b.app("() => liveGroups().some(g => g.name === 'Group B')"), 30), "B never got Group B", problems)
    check(sorted(await b.live()) == ["Group A", "Group B"], f"B shows {await b.live()}", problems)
    return problems


async def s_real_removals_still_work(br):
    """Owner deletes for everyone; a member removes one from their own view;
    the owner takes a member out. Each still disappears from the right phone,
    and never comes back by being re-sent."""
    a = await Phone.open(br, "Sherin", number())
    rahul = number()
    b = await Phone.open(br, "Rahul", rahul)
    problems = []
    g1 = await make_group(a, "Deleted by owner", rahul)
    g2 = await make_group(a, "Hidden by Rahul", rahul)
    g3 = await make_group(a, "Rahul taken out", rahul)
    await synced(a)
    check(await until(lambda: b.app("() => liveGroups().length === 3"), 30), f"B got {await b.live()}", problems)
    await a.delete_for_everyone(g1)
    await b.hide(g2)
    await a.remove_member(g3, rahul)
    await synced(a); await synced(b)
    await asyncio.sleep(2); await synced(b); await synced(b)
    check(await b.live() == [], f"B still shows {await b.live()}", problems)
    check(sorted(await a.live()) == ["Hidden by Rahul", "Rahul taken out"], f"A shows {await a.live()}", problems)
    # Rahul's phone sends nothing that brings any of them back on the server
    for _ in range(3):
        await synced(b); await synced(a)
    check(sorted(await a.live()) == ["Hidden by Rahul", "Rahul taken out"], f"A after more syncs {await a.live()}", problems)
    mine = await a.app("gid => S.groups.find(g => g.id === gid).members.filter(m => !m.deleted).map(m => m.name)", g3)
    check(mine == ["Sherin"], f"Rahul back in the group he was taken out of: {mine}", problems)
    check(await b.live() == [], f"B after more syncs {await b.live()}", problems)
    # and a server error afterwards changes nothing either way
    await b.page.route(SERVER + "/**", lambda r: r.fulfill(status=503, body="{}"))
    await b.app("() => syncNow(true)")
    await b.page.unroute(SERVER + "/**")
    check(await b.live() == [], f"B after a 503 {await b.live()}", problems)
    return problems


async def s_no_stale_overwrite(br):
    """A change made while a request is out (long poll held, or a sync in
    flight) is never lost when that older request comes back."""
    p = await Phone.open(br, "Sherin", number())
    problems = []
    await synced(p)
    # a held long poll is out; make a group in the middle of it
    await p.app("() => scheduleSync(50)")
    await p.page.wait_for_timeout(600)
    await make_group(p, "During the wait")
    # and two syncs racing (startup + reconnect style), with another group between
    r = asyncio.gather(p.app("() => syncNow(false)"), p.app("() => syncNow(true)"))
    await make_group(p, "Between two syncs")
    await r
    check(await synced(p, 40), "never settled", problems)
    st = await state(p)
    check(sorted(st["ui"]) == ["Between two syncs", "During the wait"] and not st["aside"], f"after the race {st}", problems)
    for n in ("During the wait", "Between two syncs"):
        check(await on_server(p, n), f"{n!r} never reached the server", problems)
    return problems


async def s_recovers_groups_316_set_aside(br):
    """Installing 3.17 over 3.16 brings back a group the old rule had set aside
    (it never reached the server), while a group the owner really took this
    person out of stays aside — and nothing is said about it."""
    owner = await Phone.open(br, "Asha", number())
    me_no = number()
    p = await Phone.open(br, "Sherin", me_no)
    problems = []
    gid_removed = await make_group(owner, "Removed for real", me_no)
    await synced(owner)
    await until(lambda: p.app("() => liveGroups().some(g => g.name === 'Removed for real')"), 30)
    await owner.remove_member(gid_removed, me_no)
    await synced(owner)
    # 3.16's state on this phone: a group made here that never reached the
    # server, set aside with nothing queued; and the real removal, set aside.
    await p.page.route(SERVER + "/**", lambda r: r.abort("internetdisconnected"))
    await make_group(p, NAME)
    await p.app("""() => { S.groups.forEach(g => { g.revoked = true; });
      LS.set('sl.dirty', { groups: [], expenses: [], settlements: [], hidden: [] });
      LS.set('sl.recheck317', false); localSave(); }""")
    st = await state(p)
    check(st["ui"] == [] and sorted(st["aside"]) == [NAME, "Removed for real"], f"3.16 state not set up: {st}", problems)
    await p.page.unroute(SERVER + "/**")
    await p.reload()                              # the first launch of 3.17
    check(await synced(p, 40), "never synced", problems)
    await asyncio.sleep(1); await synced(p)
    st = await state(p)
    check(st["ui"] == [NAME], f"after update, on screen {st['ui']}", problems)
    check(st["aside"] == ["Removed for real"], f"after update, set aside {st['aside']}", problems)
    check(await on_server(p, NAME), "recovered group never reached the server", problems)
    t = [x["m"] for x in await p.page.evaluate("window.__toasts")]
    check(not any("no longer in" in m for m in t), f"told about the old removal again: {t}", problems)
    mine = await owner.app("gid => S.groups.find(g => g.id === gid).members.filter(m => !m.deleted).length", gid_removed)
    check(mine == 1, f"the removed person was put back into the owner's group: {mine} members", problems)
    # once only
    check(await p.app("() => LS.get('sl.recheck317', false)") is True, "recheck flag not set", problems)
    return problems


SCENARIOS = [s_exact_online_offline_online, s_offline_group_sign_out_sign_in, s_server_lost_its_data,
             s_errors_never_delete, s_cold_start, s_two_phones, s_real_removals_still_work, s_no_stale_overwrite,
             s_recovers_groups_316_set_aside]


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
            print(f"{'PASS' if not problems else 'FAIL'}  {name:34s} " + ("; ".join(problems) or "ok"), flush=True)
    print("ALL PASS" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
