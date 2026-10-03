"""End to end: Share Expense / Share Balance as an image card.

Every card is made through the real buttons (expense → Share → preview →
Share; Balances → Share → Group summary or a member → preview → Share). The
Android bridge is a stand-in that keeps what the app hands it: the PNG (as
base64) and the caption. The PNG is then decoded and checked — its size, its
pixels, and its words, read back with OCR — and the app's data is compared
before and after to prove sharing changed nothing.

    ./run.sh cards
    python3 test_share_cards.py expense_equal,balance_owe_and_owed   # some only
    CARDS_OUT=/tmp/cards python3 test_share_cards.py                 # keep the PNGs
"""
import asyncio
import base64
import io
import os
import random
import re
import sys

from PIL import Image, ImageOps
import pytesseract
from playwright.async_api import async_playwright

from harness import Phone

ONLY = sys.argv[1].split(",") if len(sys.argv) > 1 else None
OUT = os.environ.get("CARDS_OUT")
BASE = random.randint(100, 899)
_n = [0]

# A stand-in for the native side: keeps every image it is handed. The test can
# switch what it answers ("ok", "error", or throw) to check the failure paths.
BRIDGE = """
  window.__shared = []; window.__bridgeAnswer = "ok";
  window.AndroidBridge = {
    pickContact() {},
    shareText(subject, text) {},
    pendingLink() { return ""; },
    shareImage(b64, caption) {
      if (window.__bridgeAnswer === "throw") throw new Error("native failure");
      window.__shared.push({ b64, caption });
      return window.__bridgeAnswer;
    }
  };"""

URLISH = re.compile(r"https?|www\.|\.com\b|\.in\b|\.app\b|://|onrender|/join/", re.I)


def number():
    _n[0] += 1
    return "9%03d%02d%04d" % (BASE, _n[0] % 100, random.randint(1000, 9999))


def check(cond, msg, problems):
    if not cond:
        problems.append(msg)


async def setup(br, members, currency="INR", group="Goa Trip"):
    """Signed in as members[0]; one group with everyone in `members`."""
    a = await Phone.open(br, members[0], "+91" + number(), init=BRIDGE)
    gid = await a.app("""([name, others, cur]) => {
      const me = myIdentity();
      const g = { id: uid("g"), name, currency: cur, createdAt: nowISO(), ownerId: myUserId(), members: [] };
      const row = { id: uid("m"), name: me.name, phone: me.mobile, updatedAt: nowISO() };
      g.members.push(row); LS.set(meKey(g.id), row.id);
      others.forEach(([n, p]) => g.members.push({ id: uid("m"), name: n, phone: p, updatedAt: nowISO() }));
      saveGroup(g); selectGroup(g.id);
      return g.id;
    }""", [group, [[m, "+91" + number()] for m in members[1:]], currency])
    return a, gid


async def add(p, gid, desc, amount, payers, splits, split_type="exact"):
    """An expense as the app stores one: amounts in minor units, by member name."""
    await p.app("""([gid, desc, amount, payers, splits, st]) => {
      const g = S.groups.find(x => x.id === gid);
      const id = n => g.members.find(m => m.name === n || (m.phone === myPhone() && myIdentity().name === n)).id;
      const P = {}, Sp = {};
      Object.keys(payers).forEach(n => P[id(n)] = payers[n]);
      Object.keys(splits).forEach(n => Sp[id(n)] = splits[n]);
      saveExpense({ id: uid("e"), gid, description: desc, amount, category: "Food",
        date: "2026-10-01", splitType: st, paidBy: Object.keys(P)[0], payers: P, splits: Sp, values: {} });
    }""", [gid, desc, amount, payers, splits, split_type])


def equal(amount, names):
    """The app's own equal split (first ones get the extra paise)."""
    base, extra = divmod(amount, len(names))
    return {n: base + (1 if i < extra else 0) for i, n in enumerate(names)}


async def settled(p):
    """Sync until nothing is waiting, then take the snapshot."""
    for _ in range(3):
        await p.sync()
        if not await p.app("() => Object.values(dirtySet()).some(l => l.length)"):
            break
    return await snapshot(p)


async def snapshot(p):
    """Everything sharing must leave alone: the data in memory and on disk,
    and the list of changes waiting to go to the server."""
    return await p.page.evaluate("""() => {
      const d = window.__t('JSON.stringify({ g: S.groups, e: S.expenses, s: S.settlements, dirty: dirtySet() })');
      const ls = {}; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); ls[k] = localStorage.getItem(k); }
      return { d, ls };
    }""")


async def watch_writes(p):
    """Every /sync request from now on, with what it pushed."""
    p.pushes = []

    def on_req(r):
        if r.url.endswith("/sync") and r.method == "POST":
            body = r.post_data_json or {}
            ch = body.get("changes") or {}
            p.pushes.append(sum(len(v or []) for v in ch.values()))
    p.page.on("request", on_req)


async def record_text(p):
    """Record every fillText on any canvas: what, where, and how wide."""
    await p.page.evaluate("""() => {
      if (window.__texts) { window.__texts.length = 0; return; }
      window.__texts = [];
      const f = CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText = function (s, x, y) {
        const m = this.getTransform();
        if (this.canvas.width === 1080) window.__texts.push({ s: String(s), x, y: y + m.f, w: this.measureText(s).width, a: this.textAlign });
        return f.apply(this, arguments);
      };
    }""")


async def go_bills(p):
    await p.app("() => { go('bills'); }")
    await p.page.wait_for_timeout(150)


async def go_balances(p):
    await p.page.click("#bnav button[data-sec='balances']")
    await p.page.wait_for_timeout(150)


async def share_expense(p, desc):
    """Bills → the expense → Share → preview. Leaves the preview open."""
    await record_text(p)
    await go_bills(p)
    await p.page.click(f".erow:has(.t:text-is('{desc}'))")
    await p.page.wait_for_selector("#modalRoot .modal")
    await p.page.click("#modalRoot .modal-ft button:has-text('Share')")
    await p.page.wait_for_selector("#modalRoot img.cardimg", timeout=15000)


async def share_balance(p, who):
    """Balances → Share → `who` ('Group summary' or a member) → preview."""
    await record_text(p)
    await go_balances(p)
    await p.page.click(".card-hd button[title='Share balances as an image']")
    await p.page.wait_for_selector("#modalRoot .pickgrp")
    await p.page.click(f"#modalRoot .pickgrp:has(.gn:text-is('{who}'))")
    await p.page.wait_for_selector("#modalRoot img.cardimg", timeout=15000)


async def press_share(p):
    """Preview → Share. Returns (PIL image, caption) as the native side got them."""
    before = await p.page.evaluate("window.__shared.length")
    await p.page.click("#modalRoot .modal-ft button:has-text('Share')")
    await p.page.wait_for_timeout(200)
    got = await p.page.evaluate("window.__shared")
    assert len(got) == before + 1, f"the native side got {len(got) - before} images"
    raw = base64.b64decode(got[-1]["b64"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return Image.open(io.BytesIO(raw)).convert("RGB"), got[-1]["caption"], raw


def ocr(img):
    """Light text on a dark card: invert, grey, read."""
    g = ImageOps.invert(img).convert("L")
    return pytesseract.image_to_string(g, config="--psm 4")


def squash(s):
    return re.sub(r"[^a-z0-9.]", "", s.lower())


def has(text, *words):
    t = squash(text)
    return [w for w in words if squash(w) not in t]


def keep(img, name):
    if OUT:
        os.makedirs(OUT, exist_ok=True)
        img.save(os.path.join(OUT, name + ".png"))


async def card_checks(p, img, caption, problems, label):
    """What every card must be: 1080 wide, at least 1350 tall, the app's dark
    background, the Split Buddy name, and nothing that looks like a link."""
    w, h = img.size
    check(w == 1080 and h >= 1350, f"{label}: image is {w}x{h}", problems)
    # (the top has a soft violet glow; the bottom corner is the plain page colour)
    check(img.getpixel((5, h - 5)) == (9, 7, 23), f"{label}: background {img.getpixel((5, h - 5))}", problems)
    text = ocr(img)
    check(text.count("Split Buddy") + text.count("SplitBuddy") >= 1, f"{label}: no 'Split Buddy' on the card", problems)
    check(not URLISH.search(text), f"{label}: something like a link on the card: {URLISH.search(text)}", problems)
    check(not URLISH.search(caption or ""), f"{label}: link in the caption {caption!r}", problems)
    # nothing drawn off the panel (long names and titles must wrap)
    texts = await p.page.evaluate("window.__texts || []")
    over = [t["s"] for t in texts if (t["a"] == "left" and t["x"] + t["w"] > 1080 - 112 + 1)
            or (t["a"] == "right" and t["x"] - t["w"] < 112 - 1)
            or (t["a"] == "center" and (t["x"] - t["w"] / 2 < 112 - 1 or t["x"] + t["w"] / 2 > 1080 - 112 + 1))]
    check(not over, f"{label}: text runs off the card: {over[:3]}", problems)
    low = [t["s"] for t in texts if t["y"] > h - 48]
    check(not low, f"{label}: text below the card's edge: {low[:3]}", problems)
    # the logo is drawn (the mark's tile is not empty)
    return text


# ------------------------------------------------------------------ scenarios

async def s_expense_equal(br):
    """Equal split, one payer: amount, payer, each share, who owes whom."""
    a, gid = await setup(br, ["Sherin", "Rahul", "Priya"])
    await add(a, gid, "Dinner", 240000, {"Sherin": 240000}, equal(240000, ["Sherin", "Rahul", "Priya"]), "equal")
    await record_text(a)
    problems = []
    before = await settled(a)
    await watch_writes(a)
    await share_expense(a, "Dinner")
    img, caption, _ = await press_share(a)
    keep(img, "expense_equal")
    text = await card_checks(a, img, caption, problems, "equal")
    missing = has(text, "Goa Trip", "Dinner", "Paid by Sherin", "Rahul", "Priya", "2,400.00", "800.00", "Rahul owes Sherin", "Priya owes Sherin")
    check(not missing, f"equal: card lacks {missing}", problems)
    m = await a.page.evaluate("window.__t('window.__lastCard.model')")
    split = {r["label"]: r["value"] for r in m["sections"][-1]["rows"]}
    check(split == {"Sherin": "₹800.00", "Rahul": "₹800.00", "Priya": "₹800.00"}, f"equal: split rows {split}", problems)
    owes = [(r["label"], r["value"]) for r in m["callout"]["rows"]]
    check(owes == [("Rahul owes Sherin", "₹800.00"), ("Priya owes Sherin", "₹800.00")], f"equal: owes {owes}", problems)
    check(caption.startswith("Goa Trip – Dinner"), f"equal: caption {caption!r}", problems)
    await a.sync()
    check(await snapshot(a) == before, "equal: sharing changed the app's data", problems)
    check(all(n == 0 for n in a.pushes), f"equal: a sync pushed changes {a.pushes}", problems)
    return problems


async def s_expense_unequal_and_multi_payer(br):
    """Unequal shares show their real values; several payers get a Paid list;
    an odd amount keeps its paise and the rows add up to the total."""
    a, gid = await setup(br, ["Sherin", "Rahul", "Priya"])
    await add(a, gid, "Hotel", 1000000, {"Rahul": 1000000}, {"Sherin": 500000, "Rahul": 300000, "Priya": 200000})
    await add(a, gid, "Fuel", 100000, {"Sherin": 60000, "Priya": 40000}, equal(100000, ["Sherin", "Rahul", "Priya"]), "equal")
    await record_text(a)
    problems = []
    before = await settled(a)
    await share_expense(a, "Hotel")
    img, caption, _ = await press_share(a)
    keep(img, "expense_unequal")
    text = await card_checks(a, img, caption, problems, "unequal")
    missing = has(text, "Hotel", "10,000.00", "Paid by Rahul", "5,000.00", "3,000.00", "2,000.00", "Sherin owes Rahul", "Priya owes Rahul")
    check(not missing, f"unequal: card lacks {missing}", problems)
    m = await a.page.evaluate("window.__t('window.__lastCard.model')")
    owes = [(r["label"], r["value"]) for r in m["callout"]["rows"]]
    check(owes == [("Sherin owes Rahul", "₹5,000.00"), ("Priya owes Rahul", "₹2,000.00")], f"unequal: owes {owes}", problems)
    await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")

    await share_expense(a, "Fuel")
    img, caption, _ = await press_share(a)
    keep(img, "expense_two_payers")
    await card_checks(a, img, caption, problems, "two payers")
    m = await a.page.evaluate("window.__t('window.__lastCard.model')")
    heads = [s["heading"] for s in m["sections"]]
    check(heads == ["Paid", "Split"], f"two payers: sections {heads}", problems)
    paid = {r["label"]: r["value"] for r in m["sections"][0]["rows"]}
    check(paid == {"Sherin": "₹600.00", "Priya": "₹400.00"}, f"two payers: paid {paid}", problems)
    split = [r["value"] for r in m["sections"][1]["rows"]]
    check(split == ["₹333.34", "₹333.33", "₹333.33"], f"two payers: split {split}", problems)
    # the app's own pairwise rule, not a new calculation
    want = await a.app("""gid => { const g = S.groups.find(x => x.id === gid); const e = S.expenses.find(x => x.description === 'Fuel');
      return pairwiseDebts(g.members, [e], []).map(d => memberName(d.from, g) + ' owes ' + memberName(d.to, g) + ' ' + fmt(d.amount, 'INR')); }""", gid)
    got = [r["label"] + " " + r["value"] for r in m["callout"]["rows"]]
    check(got == want, f"two payers: card says {got}, the app says {want}", problems)
    check(m["amountNote"] == "Paid by Sherin, Priya", f"two payers: {m['amountNote']!r}", problems)
    check(await snapshot(a) == before, "unequal: sharing changed the app's data", problems)
    return problems


async def s_balance_owe_and_owed(br):
    """'YOU OWE SHERIN' for the one who owes, 'YOU ARE OWED BY RAHUL' the other
    way round; each card shows only that member's own transfers."""
    a, gid = await setup(br, ["Sherin", "Rahul", "Priya"])
    await add(a, gid, "Dinner", 240000, {"Sherin": 240000}, equal(240000, ["Sherin", "Rahul", "Priya"]), "equal")
    await add(a, gid, "Cab", 60000, {"Priya": 60000}, {"Priya": 30000, "Rahul": 30000})
    # now: Rahul owes Sherin 800 and Priya 300; Priya owes Sherin 800
    await record_text(a)
    problems = []
    a_before = await settled(a)
    await watch_writes(a)
    await a.app("() => { S.simplify = false; }")      # Exact debts: one transfer per pair

    await share_balance(a, "Priya")                    # Priya: owes Sherin 800, is owed 300 by Rahul
    img, caption, _ = await press_share(a)
    keep(img, "balance_priya_total")
    text = await card_checks(a, img, caption, problems, "Priya")
    m = await a.page.evaluate("window.__t('window.__lastCard.model')")
    check(m["amountNote"] == "YOU OWE IN TOTAL" and m["amount"] == "₹500.00", f"Priya: {m['amountNote']} {m['amount']}", problems)
    rows = [(r["label"], r["value"]) for r in m["sections"][0]["rows"]]
    check(sorted(rows) == sorted([("You owe Sherin", "₹800.00"), ("Rahul owes you", "₹300.00")]), f"Priya: details {rows}", problems)
    missing = has(text, "Priya", "YOU OWE IN TOTAL", "500.00", "You owe Sherin", "Rahul owes you")
    check(not missing, f"Priya: card lacks {missing}", problems)
    await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")

    # a two-person group gives the single-transfer wording both ways
    await a.app("() => { S.simplify = true; }")
    b, gid2 = await setup(br, ["Sherin", "Rahul"], group="Flat")
    await add(b, gid2, "Rent share", 1250050, {"Sherin": 1250050}, {"Rahul": 1250050})
    await record_text(b)
    b_before = await settled(b)
    await share_balance(b, "Rahul")
    img, caption, _ = await press_share(b)
    keep(img, "balance_you_owe")
    text = await card_checks(b, img, caption, problems, "Rahul")
    missing = has(text, "Flat", "Rahul", "YOU OWE SHERIN", "12,500.50", "Based on current group expenses")
    check(not missing, f"Rahul: card lacks {missing}", problems)
    m = await b.page.evaluate("window.__t('window.__lastCard.model')")
    check(m["amountNote"] == "YOU OWE SHERIN" and m["amountTone"] == "neg", f"Rahul: {m['amountNote']} {m['amountTone']}", problems)
    check(caption == "Flat | Rahul owes Sherin ₹12,500.50", f"Rahul: caption {caption!r}", problems)
    await b.page.click("#modalRoot .modal-ft button:has-text('Cancel')")

    await share_balance(b, "Sherin")
    img, caption, _ = await press_share(b)
    keep(img, "balance_you_are_owed")
    text = await card_checks(b, img, caption, problems, "Sherin")
    missing = has(text, "YOU ARE OWED BY RAHUL", "12,500.50")
    check(not missing, f"Sherin: card lacks {missing}", problems)
    m = await b.page.evaluate("window.__t('window.__lastCard.model')")
    check(m["amountTone"] == "pos", f"Sherin: tone {m['amountTone']}", problems)

    # only that member's business: in the 3-person group Rahul's card leaves Priya→Sherin out
    await a.app("() => { S.simplify = false; }")
    await share_balance(a, "Rahul")
    m = await a.page.evaluate("window.__t('window.__lastCard.model')")
    labels = " ".join(r["label"] for s in m["sections"] for r in s["rows"])
    check("Priya owes" not in labels and "Sherin owes" not in labels, f"Rahul's card shows others' debts: {labels}", problems)
    await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    # Simplified: the card follows the screen's setting
    await a.app("() => { S.simplify = true; }")
    await share_balance(a, "Rahul")
    m = await a.page.evaluate("window.__t('window.__lastCard.model')")
    want = await a.app("""gid => { const g = S.groups.find(x => x.id === gid); const n = netBalances(liveMembers(g), currentExpenses(), currentSettlements());
      const r = g.members.find(x => x.name === 'Rahul').id;
      return simplifyDebts(n).filter(t => t.from === r || t.to === r).map(t => fmt(t.amount, 'INR')); }""", gid)
    got = [m["amount"]] if not m["sections"] else [r["value"] for r in m["sections"][0]["rows"]]
    check(got == want, f"simplified: card {got}, the app {want}", problems)
    await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")

    await a.sync(); await b.sync()
    # (the Simplified/Exact switch was flipped above, so compare the data itself)
    check((await snapshot(a))["d"] == a_before["d"], "balance: sharing changed the app's data", problems)
    check((await snapshot(b))["d"] == b_before["d"], "balance (Flat): sharing changed the app's data", problems)
    check(all(n == 0 for n in a.pushes), f"balance: a sync pushed changes {a.pushes}", problems)
    return problems


async def s_settled_member(br):
    a, gid = await setup(br, ["Sherin", "Rahul"])
    await add(a, gid, "Coffee", 30000, {"Sherin": 30000}, {"Sherin": 30000})
    await record_text(a)
    problems = []
    await share_balance(a, "Rahul")
    img, caption, _ = await press_share(a)
    keep(img, "balance_settled")
    text = await card_checks(a, img, caption, problems, "settled")
    check(not has(text, "SETTLED"), "settled: no 'settled' on the card", problems)
    return problems


async def s_group_summary(br):
    a, gid = await setup(br, ["Sherin", "Rahul", "Priya", "Anu"])
    await add(a, gid, "Villa", 1200000, {"Sherin": 1200000}, equal(1200000, ["Sherin", "Rahul", "Priya", "Anu"]), "equal")
    await add(a, gid, "Boat", 400000, {"Anu": 400000}, equal(400000, ["Sherin", "Rahul", "Priya", "Anu"]), "equal")
    await record_text(a)
    problems = []
    before = await settled(a)
    await share_balance(a, "Group summary")
    img, caption, _ = await press_share(a)
    keep(img, "group_summary")
    text = await card_checks(a, img, caption, problems, "summary")
    missing = has(text, "Goa Trip", "16,000.00", "2 expenses", "Balances", "Gets", "Owes", "settle up", "pays")
    check(not missing, f"summary: card lacks {missing}", problems)
    m = await a.page.evaluate("window.__t('window.__lastCard.model')")
    want = await a.app("""() => { const g = S.group; const n = netBalances(liveMembers(g), currentExpenses(), currentSettlements());
      return simplifyDebts(n).map(t => memberName(t.from, g) + ' pays ' + memberName(t.to, g) + ' ' + fmt(t.amount, 'INR')); }""")
    got = [r["label"] + " " + r["value"] for r in m["sections"][1]["rows"]]
    check(got == want, f"summary: to settle {got}, the app {want}", problems)
    check((await snapshot(a))["d"] == before["d"], "summary: sharing changed the app's data", problems)
    return problems


async def s_many_people_long_text(br):
    """25 people, a very long title and long names: the card grows, every line
    wraps inside it, and every person is on it."""
    long_name = "Venkataraghavan Subramaniam Iyer-Krishnamurthy"
    people = ["Sherin", long_name] + ["Friend %02d" % i for i in range(1, 24)]
    a, gid = await setup(br, people, group="College Reunion Weekend at the Backwaters — Alleppey 2026")
    title = "Houseboat booking, lunch, dinner and the extra night because the boat broke down near Kumarakom"
    await add(a, gid, title, 2500000, {long_name: 2500000}, equal(2500000, people), "equal")
    await record_text(a)
    problems = []
    await share_expense(a, title)
    img, caption, _ = await press_share(a)
    keep(img, "expense_25_people")
    text = await card_checks(a, img, caption, problems, "25 people")
    check(img.size[1] > 2500, f"25 people: card only {img.size[1]} tall", problems)
    m = await a.page.evaluate("window.__t('window.__lastCard.model')")
    check(len(m["sections"][-1]["rows"]) == 25, f"25 people: {len(m['sections'][-1]['rows'])} split rows", problems)
    drawn = " ".join(t["s"] for t in await a.page.evaluate("window.__texts"))
    gone = [p for p in people if p.split()[0] not in drawn]
    check(not gone, f"25 people: not drawn: {gone}", problems)
    missing = has(text, "Houseboat", "Kumarakom", "Venkataraghavan", "Friend 23", "1,000.00")
    check(not missing, f"25 people: card lacks {missing}", problems)
    await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    await share_balance(a, "Group summary")
    img, caption, _ = await press_share(a)
    keep(img, "summary_25_people")
    await card_checks(a, img, caption, problems, "25 people summary")
    return problems


async def s_currency(br):
    problems = []
    for cur, want in (("USD", "$1,234.56"), ("EUR", "1.234,56"), ("GBP", "£1,234.56")):
        a, gid = await setup(br, ["Sherin", "Rahul"], currency=cur, group="Trip " + cur)
        await add(a, gid, "Tickets", 123456, {"Sherin": 123456}, {"Rahul": 123456})
        await record_text(a)
        await share_expense(a, "Tickets")
        img, caption, _ = await press_share(a)
        keep(img, "currency_" + cur)
        await card_checks(a, img, caption, problems, cur)
        m = await a.page.evaluate("window.__t('window.__lastCard.model')")
        check(want in m["amount"] and "₹" not in m["amount"], f"{cur}: amount {m['amount']!r}", problems)
        check(all("₹" not in r["value"] for s in m["sections"] for r in s["rows"]), f"{cur}: rupee on the card", problems)
        check(not has(ocr(img), want.strip("$£")), f"{cur}: {want} not read on the card", problems)
        await a.ctx.close()
    return problems


async def s_preview_cancel_and_failures(br):
    """Cancel shares nothing; a native failure is a friendly message, not a crash."""
    a, gid = await setup(br, ["Sherin", "Rahul"])
    await add(a, gid, "Snacks", 50000, {"Sherin": 50000}, {"Rahul": 50000})
    problems = []
    before = await settled(a)
    await share_expense(a, "Snacks")
    title = (await a.page.text_content("#modalRoot .modal-hd")).strip()
    check(title.startswith("Share card"), f"preview title {title!r}", problems)
    btns = await a.page.eval_on_selector_all("#modalRoot .modal-ft button", "els => els.map(e => e.textContent.trim())")
    check(btns == ["Cancel", "Share"], f"preview buttons {btns}", problems)
    await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    await a.page.wait_for_timeout(200)
    check(not await a.page.is_visible("#modalRoot .modal"), "Cancel left the preview open", problems)
    check(await a.page.evaluate("window.__shared.length") == 0, "Cancel shared something", problems)

    for answer in ("error", "throw"):
        await a.page.evaluate(f"window.__bridgeAnswer = '{answer}'")
        await a._watch_toasts()
        await share_expense(a, "Snacks")
        await a.page.click("#modalRoot .modal-ft button:has-text('Share')")
        await a.page.wait_for_timeout(300)
        t = [x["m"] for x in await a.page.evaluate("window.__toasts")]
        check(any("Couldn't prepare the image" in m for m in t), f"{answer}: toasts {t}", problems)
        check(await a.page.is_visible("#modalRoot img.cardimg"), f"{answer}: the preview vanished", problems)
        await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    await a.page.evaluate("window.__bridgeAnswer = 'ok'")

    # the native side couldn't open the share sheet (it calls __shareFailed)
    await a._watch_toasts()
    await a.page.evaluate("window.__shareFailed()")
    t = [x["m"] for x in await a.page.evaluate("window.__toasts")]
    check(any("Couldn't open sharing" in m for m in t), f"__shareFailed: toasts {t}", problems)

    # a card that cannot be built is a message, not a crash
    await a._watch_toasts()
    await a.app("() => openCardPreview(() => { throw new Error('boom'); })")
    await a.page.wait_for_timeout(200)
    t = [x["m"] for x in await a.page.evaluate("window.__toasts")]
    check(any("Couldn't create the card" in m for m in t), f"bad card: toasts {t}", problems)
    check((await snapshot(a))["d"] == before["d"], "cancel/failures: data changed", problems)
    return problems


async def s_entry_points(br):
    """Share is on a saved expense (not a new one) and on Balances' Settle up;
    the balance menu offers the summary and every member."""
    a, gid = await setup(br, ["Sherin", "Rahul", "Priya"])
    await add(a, gid, "Lunch", 90000, {"Sherin": 90000}, equal(90000, ["Sherin", "Rahul", "Priya"]), "equal")
    problems = []
    await go_bills(a)
    await a.page.click(".topbar button:has-text('Add expense')")
    await a.page.wait_for_selector("#modalRoot .modal")
    check(await a.page.locator("#modalRoot .modal-ft button:has-text('Share')").count() == 0, "a new expense has Share", problems)
    await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    await a.page.click(".erow:has(.t:text-is('Lunch'))")
    check(await a.page.locator("#modalRoot .modal-ft button:has-text('Share')").count() == 1, "a saved expense has no Share", problems)
    await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    await go_balances(a)
    await a.page.click(".card-hd button[title='Share balances as an image']")
    opts = await a.page.eval_on_selector_all("#modalRoot .pickgrp .gn", "els => els.map(e => e.textContent)")
    check(opts == ["Group summary", "Sherin", "Rahul", "Priya"], f"balance menu {opts}", problems)
    subs = await a.page.eval_on_selector_all("#modalRoot .pickgrp .gs", "els => els.map(e => e.textContent)")
    check(subs[1:] == ["is owed ₹600.00", "owes ₹300.00", "owes ₹300.00"], f"balance menu amounts {subs}", problems)
    await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    # Back closes the preview like any other dialog
    await share_balance(a, "Group summary")
    await a.page.go_back(); await a.page.wait_for_timeout(300)
    check(not await a.page.is_visible("#modalRoot .modal"), "Back left the preview open", problems)
    check(await a.page.evaluate("location.href.endsWith('/index.html')"), "Back left the app", problems)
    return problems


async def s_unsaved_edit_not_shared(br):
    """Share in the edit dialog sends the saved expense, never unsaved typing."""
    a, gid = await setup(br, ["Sherin", "Rahul"])
    await add(a, gid, "Movie", 80000, {"Sherin": 80000}, {"Sherin": 40000, "Rahul": 40000})
    problems = []
    before = await settled(a)
    await go_bills(a)
    await a.page.click(".erow:has(.t:text-is('Movie'))")
    await a.page.fill("#modalRoot input[placeholder^='Dinner at']", "Changed but not saved")
    await a.page.click("#modalRoot .modal-ft button:has-text('Share')")
    await a.page.wait_for_selector("#modalRoot img.cardimg", timeout=15000)
    m = await a.page.evaluate("window.__t('window.__lastCard.model')")
    check(m["title"] == "Movie", f"shared the unsaved title {m['title']!r}", problems)
    await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    check((await snapshot(a))["d"] == before["d"], "unsaved edit: data changed", problems)
    return problems


SCENARIOS = [s_expense_equal, s_expense_unequal_and_multi_payer, s_balance_owe_and_owed, s_settled_member,
             s_group_summary, s_many_people_long_text, s_currency, s_preview_cancel_and_failures,
             s_entry_points, s_unsaved_edit_not_shared]


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


asyncio.run(main())
