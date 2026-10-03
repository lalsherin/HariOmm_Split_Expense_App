"""End to end: Share group → invite link → join.

Real phone pages against a real local server. The Android bridge is a
stand-in with MainActivity's exact methods: shareText(subject, text) records
what would go to the share sheet, and pendingLink() returns the link the app
was "opened with" once, as MainActivity does after onCreate / onNewIntent.

    ./run.sh invites
"""
import asyncio
import os
import random
import sqlite3
import sys
import time

from playwright.async_api import async_playwright

from harness import Phone, SERVER

ONLY = sys.argv[1].split(",") if len(sys.argv) > 1 else None
BASE = random.randint(100, 899)
_n = [0]

BRIDGE = """
  window.__shared = []; window.__link = window.__link || "";
  window.AndroidBridge = {
    pickContact() {},
    shareText(subject, text) { window.__shared.push({ subject, text }); },
    pendingLink() { const l = window.__link; window.__link = ""; return l; }
  };"""


def numbers(k):
    _n[0] += 1
    return ["9%03d%02d%04d" % (BASE, _n[0], i) for i in range(1, k + 1)]


async def until(fn, seconds, every=0.25):
    end = time.time() + seconds
    while time.time() < end:
        v = await fn()
        if v:
            return v
        await asyncio.sleep(every)
    return await fn()


async def owner_with_group(br, a_num, others=()):
    a = await Phone.open(br, "Sherin", "+91" + a_num, init=BRIDGE)
    gid = await a.create_group("App development", [list(o) for o in others])
    await a.app("""gid => { const g = S.groups.find(x => x.id === gid);
      const me = g.members.find(m => m.phone === myPhone());
      saveExpense({ id: uid("e"), gid, description: "Hosting", amount: 635800, category: "Other",
        date: todayStr(), splitType: "equal", paidBy: me.id, payers: { [me.id]: 635800 },
        splits: { [me.id]: 635800 }, values: {} }); }""", gid)
    await a.sync()
    await a.app("gid => openGroup(gid)", gid)
    return a, gid


async def share_link(a):
    """Tap Share in the open group, wait for the link, tap Share…"""
    await a.page.click(".topbar button[aria-label='Share group']")
    await a.page.wait_for_function("document.querySelector('#modalRoot input[aria-label=\"Invite link\"]').value.includes('/join/')", timeout=15000)
    link = await a.page.input_value("#modalRoot input[aria-label='Invite link']")
    await a.page.click("#modalRoot button:has-text('Share…')")
    shared = await a.page.evaluate("window.__shared")
    await a.page.click("#modalRoot button:has-text('Close')")
    return link, shared


async def deliver_link(p, link):
    """The link arrives while the app is running (onNewIntent)."""
    await p.page.evaluate("l => { window.__link = l; window.__linkArrived(); }", link)


async def modal_text(p):
    # a fresh install is offered a passcode first; the person says "Not now"
    for _ in range(20):
        if await p.page.is_visible("#lockScreen button:has-text('Not now')"):
            await p.page.click("#lockScreen button:has-text('Not now')")
            break
        if await p.page.is_visible("#modalRoot .modal"):
            break
        await p.page.wait_for_timeout(250)
    await p.page.wait_for_selector("#modalRoot .modal", timeout=15000)
    return await p.page.text_content("#modalRoot .modal")


def check(cond, msg, problems):
    if not cond:
        problems.append(msg)


# ------------------------------------------------------------------ scenarios


async def s_full_flow_late_install(br):
    """Create group → Share → (WhatsApp/Gmail via the share sheet) → friend
    without the app installs, taps the link, signs in, sees the invite, taps
    Join → group appears, owner still owns it, no duplicate."""
    a_num, s_num, b_num = numbers(3)
    a, gid = await owner_with_group(br, a_num, [("Suthan", s_num)])
    problems = []
    link, shared = await share_link(a)
    check(link.startswith(SERVER + "/join/"), f"link {link}", problems)
    token = link.rsplit("/", 1)[1]
    check(gid not in link and len(token) >= 20, "link exposes the group id or is short", problems)
    check(len(shared) == 1, f"share sheet calls {shared}", problems)
    msg = shared[0]["text"] if shared else ""
    check(shared and shared[0]["subject"] == "You're invited to join my Split Buddy group", "subject", problems)
    check("“App development” on Split Buddy" in msg and link in msg, f"message: {msg!r}", problems)
    for secret in (gid, a_num, s_num, "6,358", "635800"):
        check(secret not in msg, f"message leaks {secret}", problems)

    # Bala has no app. He installs it and opens it from the link.
    b = await Phone.install(br, "Bala", b_num, init=BRIDGE.replace('window.__link || ""', repr(link)))
    text = await modal_text(b)
    check("You've been invited" in text and "App development" in text, f"invite modal: {text[:200]!r}", problems)
    check("2 members" in text and "6,358" in text, f"invite summary: {text!r}", problems)
    check(await b.live() == [], "joined before tapping Join", problems)
    await b.page.click("#modalRoot button:has-text('Join group')")
    got = await until(b.live, 15)
    check(got == ["App development"], f"Bala sees {got}", problems)
    title = await b.page.text_content("#groupName")
    check(title == "App development", f"after joining, screen shows {title!r}", problems)
    # the owner's phone: Bala arrives, Sherin still owns it, nobody duplicated
    await a.sync(); await a.page.wait_for_timeout(500)
    members = await a.app("gid => S.groups.find(g => g.id === gid).members.filter(m => !m.deleted).map(m => m.name).sort()", gid)
    check(members == ["Bala", "Sherin", "Suthan"], f"owner sees members {members}", problems)
    owner = await a.app("gid => S.groups.find(g => g.id === gid).ownerId === myUserId()", gid)
    check(owner, "ownership changed", problems)
    return problems


async def s_existing_user_and_repeat(br):
    """Bala already uses the app; the link arrives while it is open. Then the
    same link again: already a member, nothing duplicated. Then the owner taps
    their own link."""
    a_num, b_num = numbers(2)
    a, gid = await owner_with_group(br, a_num)
    link, _ = await share_link(a)
    b = await Phone.open(br, "Bala", "+91" + b_num, init=BRIDGE)
    problems = []
    await deliver_link(b, link)
    await modal_text(b)
    await b.page.click("#modalRoot button:has-text('Join group')")
    check(await until(b.live, 15) == ["App development"], f"Bala sees {await b.live()}", problems)
    await deliver_link(b, link)
    text = await modal_text(b)
    check("already a member" in text, f"second open: {text!r}", problems)
    await b.page.click("#modalRoot button:has-text('OK')")
    mine = await b.app("gid => S.groups.find(g => g.id === gid).members.filter(m => !m.deleted && m.phone === myPhone()).length", gid)
    check(mine == 1, f"Bala is in the group {mine} times", problems)
    await deliver_link(a, link)
    text = await modal_text(a)
    check("already the owner" in text, f"owner opening own link: {text!r}", problems)
    return problems


async def s_member_added_by_number_opens_link(br):
    a_num, b_num = numbers(2)
    a, gid = await owner_with_group(br, a_num, [("Bala", b_num)])
    link, _ = await share_link(a)
    b = await Phone.install(br, "Bala", b_num, init=BRIDGE.replace('window.__link || ""', repr(link)))
    text = await modal_text(b)
    problems = []
    check("already a member" in text, f"{text!r}", problems)
    await b.page.click("#modalRoot button:has-text('Open group')")
    check(await until(b.live, 15) == ["App development"], f"Bala sees {await b.live()}", problems)
    mine = await b.app("gid => S.groups.find(g => g.id === gid).members.filter(m => !m.deleted && m.phone === myPhone()).length", gid)
    check(mine == 1, f"duplicate membership: {mine}", problems)
    return problems


async def s_expired_deleted_invalid_revoked(br):
    a_num, b_num, c_num = numbers(3)
    a, gid = await owner_with_group(br, a_num)
    problems = []
    b = await Phone.open(br, "Bala", "+91" + b_num, init=BRIDGE)

    # expired: age the invite in the server's database
    link, _ = await share_link(a)
    token = link.rsplit("/", 1)[1]
    db = sqlite3.connect(os.environ["E2E_DB"])
    db.execute("update group_invites set expires_at = '2020-01-01 00:00:00.000000'"); db.commit(); db.close()
    await deliver_link(b, link)
    text = await modal_text(b)
    check("expired" in text, f"expired: {text!r}", problems)
    await b.page.click("#modalRoot button:has-text('OK')")
    check(await b.live() == [], "joined through an expired link", problems)

    # revoked: the owner makes a new link; the old one stops
    await a.app("gid => LS.set('sl.invite.' + gid, null)", gid)
    old_link, _ = await share_link(a)
    await a.page.click(".topbar button[aria-label='Share group']")
    await a.page.wait_for_function("document.querySelector('#modalRoot input[aria-label=\"Invite link\"]').value.includes('/join/')")
    await a.page.click("#modalRoot button:has-text('Make a new link')")
    await a.page.wait_for_function(f"document.querySelector('#modalRoot input[aria-label=\"Invite link\"]').value !== {old_link!r}")
    new_link = await a.page.input_value("#modalRoot input[aria-label='Invite link']")
    await a.page.click("#modalRoot button:has-text('Close')")
    await deliver_link(b, old_link)
    text = await modal_text(b)
    check("replaced by a newer one" in text, f"revoked: {text!r}", problems)
    await b.page.click("#modalRoot button:has-text('OK')")

    # invalid
    await deliver_link(b, SERVER + "/join/random-invalid-token-zz")
    text = await modal_text(b)
    check("isn't valid" in text, f"invalid: {text!r}", problems)
    await b.page.click("#modalRoot button:has-text('OK')")

    # deleted: the owner deletes the group for everyone, then the new link is opened
    await a.delete_for_everyone(gid); await a.sync()
    c = await Phone.install(br, "Chitra", c_num, init=BRIDGE.replace('window.__link || ""', repr(new_link)))
    text = await modal_text(c)
    check("no longer available" in text, f"deleted: {text!r}", problems)
    check(await c.live() == [] and await b.live() == [], "someone got into a deleted group", problems)
    return problems


async def s_paste_link_and_copy(br):
    """No deep link at all: copy the link on one phone, paste it into Groups →
    'Join a group with an invite link' on the other."""
    a_num, b_num = numbers(2)
    a, gid = await owner_with_group(br, a_num)
    await a.ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin="http://127.0.0.1:8080")
    await a.page.click(".topbar button[aria-label='Share group']")
    await a.page.wait_for_function("document.querySelector('#modalRoot input[aria-label=\"Invite link\"]').value.includes('/join/')")
    link = await a.page.input_value("#modalRoot input[aria-label='Invite link']")
    await a.page.click("#modalRoot button:has-text('Copy link')")
    problems = []
    copied = await a.page.evaluate("navigator.clipboard.readText()")
    check(copied == link, f"clipboard has {copied!r}", problems)
    b = await Phone.open(br, "Bala", "+91" + b_num, init=BRIDGE)
    await b.page.click("#bnav button[data-sec='groups']")
    await b.page.click("button:has-text('Join a group with an invite link')")
    await b.page.fill("#modalRoot input[aria-label='Invite link']", "Hey, join us: " + link + " thanks!")
    await b.page.click("#modalRoot button:has-text('Continue')")
    await modal_text(b)
    await b.page.click("#modalRoot button:has-text('Join group')")
    check(await until(b.live, 15) == ["App development"], f"Bala sees {await b.live()}", problems)
    return problems


async def s_browser_page_and_app_link_file(br):
    """What a link shows in a browser, and the file Android checks before
    opening /join links in the app."""
    a_num, = numbers(1)
    a, gid = await owner_with_group(br, a_num)
    link, _ = await share_link(a)
    problems = []
    page = await a.ctx.new_page()
    r = await page.goto(link)
    body = await page.content()
    check(r.status == 200, f"page status {r.status}", problems)
    check("Join “App development”" in body, "group name missing", problems)
    href = await page.get_attribute("a.btn", "href")
    check(href.startswith("intent://join/" + link.rsplit("/", 1)[1]) and "package=com.sherinlal.splitledger" in href,
          f"Open in Split Buddy goes to {href}", problems)
    for secret in (gid, a_num, "6,358"):
        check(secret not in body, f"page leaks {secret}", problems)
    r = await page.goto(SERVER + "/.well-known/assetlinks.json")
    check(r.status == 200 and "com.sherinlal.splitledger" in await page.content(), "assetlinks.json", problems)
    r = await page.goto(SERVER + "/join/random-invalid-token-zz")
    check(r.status == 404 and "isn't valid" in await page.content(), "invalid link page", problems)
    return problems


async def s_offline_owner_cannot_make_link(br):
    a_num, = numbers(1)
    a, gid = await owner_with_group(br, a_num)
    await a.page.route(SERVER + "/**", lambda r: r.abort())
    await a.app("gid => LS.set('sl.invite.' + gid, null)", gid)
    await a.page.click(".topbar button[aria-label='Share group']")
    await a.page.wait_for_timeout(1500)
    problems = []
    txt = await a.page.text_content("#modalRoot .modal")
    check("Can't reach the server" in txt, f"offline share: {txt!r}", problems)
    check(await a.page.is_disabled("#modalRoot button:has-text('Share…')"), "Share… enabled with no link", problems)
    return problems


SCENARIOS = [s_full_flow_late_install, s_existing_user_and_repeat, s_member_added_by_number_opens_link,
             s_expired_deleted_invalid_revoked, s_paste_link_and_copy, s_browser_page_and_app_link_file,
             s_offline_owner_cannot_make_link]


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
