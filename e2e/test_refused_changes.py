"""End-to-end check of the refused-change loop and its neighbours.

Each scenario runs two phones against a real server, then watches B for
WATCH seconds (long enough for two full long-poll cycles) and asserts:
  * how many server refusals B's toasts announced, by exact text,
  * that B is not stuck re-sending the same refused change,
  * which groups B shows at the end.
"""
import asyncio, sys
from playwright.async_api import async_playwright
from harness import Phone

A_NUM, B_NUM = None, None   # fresh pair of accounts per scenario, set in run()
WATCH = int(sys.argv[1]) if len(sys.argv) > 1 else 35
ONLY = sys.argv[2].split(",") if len(sys.argv) > 2 else None
GONE = "You're no longer in “Goa trip” — it has been removed from this phone"
OWNER = "Only the person who created “Goa trip” can delete it for everyone"


async def setup(browser):
    a = await Phone.open(browser, "Asha", A_NUM)
    b = await Phone.open(browser, "Bala", B_NUM)
    gid = await a.create_group("Goa trip", [["Bala", B_NUM]])
    await a.sync(); await b.sync(); await b.page.wait_for_timeout(300)
    assert "Goa trip" in await b.live(), await b.live()
    return a, b, gid


async def s_owner_deletes(a, b, gid):
    await a.delete_for_everyone(gid); await a.sync()
    return dict(toasts=[], live=[])

async def s_hide_then_owner_deletes(a, b, gid):
    await b.hide(gid); await b.sync()
    await a.delete_for_everyone(gid); await a.sync()
    return dict(toasts=[], live=[])

async def s_removed_then_hides(a, b, gid):          # the reported bug
    await a.remove_member(gid, B_NUM); await a.sync()
    await b.hide(gid)
    return dict(toasts=[], live=[])

async def s_hide_lands_after_removal_and_delete(a, b, gid):   # the reported bug, other order
    await b.page.route("**/sync", lambda r: r.abort())
    await b.hide(gid); await b.page.wait_for_timeout(1500)
    await a.remove_member(gid, B_NUM); await a.delete_for_everyone(gid); await a.sync()
    await b.page.unroute("**/sync")
    return dict(toasts=[], live=[])

async def s_stuck_37_phone_upgrades(a, b, gid):
    """A phone already caught in the loop under 3.7: the removal is in its local
    list, the server refuses it. After the update it must go quiet."""
    await a.remove_member(gid, B_NUM); await a.sync()
    await b.app("gid => { LS.set('sl.hidden', [gid]); LS.set('sl.hiddenRefused', []); }", gid)
    await b.reload()
    return dict(toasts=[], live=[])

async def s_removed_then_writes(a, b, gid):
    """B was taken out, doesn't know, and adds an expense: told once, clearly,
    and the group goes away instead of refusing every later edit."""
    await a.remove_member(gid, B_NUM); await a.sync()
    await b.app("""gid => { const g = S.groups.find(x => x.id === gid);
        g.name = "Goa trip"; saveGroup(g); }""", gid)
    return dict(toasts=[GONE], live=[])

async def s_readded_after_refused_removal(a, b, gid):
    await a.remove_member(gid, B_NUM); await a.sync()
    await b.hide(gid); await b.page.wait_for_timeout(3000)
    assert await b.live() == []
    await a.app("""([gid, p]) => { const g = S.groups.find(x => x.id === gid);
        g.members.push({ id: uid("m"), name: "Bala", phone: p, updatedAt: nowISO() }); saveGroup(g); }""", [gid, B_NUM])
    await a.sync()
    await b.app("() => { SYNC.fullPull = true; }"); await b.sync()
    return dict(toasts=[], live=["Goa trip"])

async def s_non_creator_delete_refused(a, b, gid):
    """B's phone wrongly thinks it may delete for everyone (no owner recorded)."""
    await b.app("gid => { S.groups.find(x => x.id === gid).ownerId = null; }", gid)
    await b.delete_for_everyone(gid); await b.sync()
    return dict(toasts=[OWNER], live=["Goa trip"])

async def s_member_hides_normally(a, b, gid):
    await b.hide(gid); await b.sync()
    return dict(toasts=[], live=[])


SCENARIOS = [s_owner_deletes, s_hide_then_owner_deletes, s_removed_then_hides,
             s_hide_lands_after_removal_and_delete, s_stuck_37_phone_upgrades,
             s_removed_then_writes, s_readded_after_refused_removal,
             s_non_creator_delete_refused, s_member_hides_normally]


_n = [0]
async def run(browser, fn):
    global A_NUM, B_NUM
    _n[0] += 1
    A_NUM, B_NUM = "+9198%02d000001" % _n[0], "+9198%02d000002" % _n[0]
    a, b, gid = await setup(browser)
    exp = await fn(a, b, gid)
    await b.page.wait_for_timeout(WATCH * 1000)
    shown = [t["m"] for t in await b.page.evaluate("window.__toasts")]
    refusalish = [m for m in shown if "refused" in m or "no longer in" in m
                  or "can delete it for everyone" in m or "accepted by the server" in m]
    # the server's own view of it: how many rows it refused in the last half of the watch
    b.rejected = 0
    await b.page.wait_for_timeout(WATCH * 500)
    late_rejects = b.rejected
    live = await b.live()
    problems = []
    if refusalish != exp["toasts"]:
        problems.append(f"toasts {refusalish!r} != expected {exp['toasts']!r}")
    if late_rejects:
        problems.append(f"still being refused: {late_rejects} rows in the last {WATCH//2}s")
    if live != exp["live"]:
        problems.append(f"B shows {live!r}, expected {exp['live']!r}")
    status = "PASS" if not problems else "FAIL"
    print(f"{status}  {fn.__name__[2:]:40s} syncs={b.syncs:3d}  " + ("; ".join(problems) or "ok"), flush=True)
    await a.ctx.close(); await b.ctx.close()
    return not problems


async def main():
    async with async_playwright() as p:
        br = await p.chromium.launch()
        ok = True
        for fn in SCENARIOS:
            if ONLY and fn.__name__[2:] not in ONLY:
                continue
            ok &= await run(br, fn)
        await br.close()
    print("ALL PASS" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)

asyncio.run(main())
