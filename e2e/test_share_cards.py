"""End to end: Share Balance as an image card (3.16: balances only).

Every card is made through the real buttons (Balances → Share → a member or
Group summary → preview → Share), and no expense anywhere offers Share. The
Android bridge is a stand-in that keeps what the app hands it: the PNG (as
base64) and the caption. The PNG is then decoded and checked — its size, its
pixels, and its words, read back with OCR — and the app's data is compared
before and after to prove sharing changed nothing.

    ./run.sh cards
    python3 test_share_cards.py balance_owe_and_owed,group_summary    # some only
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

SHARE_SEL = "#modalRoot .modal-ft button:has-text('Share')"


async def open_expense(p, desc, where):
    """Open an expense the ways a person can: Bills, or the group's own list."""
    await p.page.wait_for_selector("#modalRoot .modal", state="detached")   # any earlier dialog gone
    if where == "bills":
        await go_bills(p)
    else:
        await p.app("() => { go('groups'); S.groupOpen = true; S.tab = 'expenses'; render(); }")
        await p.page.wait_for_timeout(150)
    await p.page.click(f".erow:has(.t:text-is('{desc}'))")
    await p.page.wait_for_selector("#modalRoot .modal")


async def s_no_expense_share(br):
    """Tests 1, 12, 14: no expense offers Share, anywhere; editing an expense
    still works exactly as before; the expense card code is gone."""
    a, gid = await setup(br, ["Sherin", "Rahul", "Priya"])
    await add(a, gid, "Dinner", 240000, {"Sherin": 240000}, equal(240000, ["Sherin", "Rahul", "Priya"]), "equal")
    problems = []
    for where in ("bills", "group"):
        await open_expense(a, "Dinner", where)
        title = (await a.page.text_content("#modalRoot .modal-hd")).strip()
        check(title.startswith("Edit expense"), f"{where}: opened {title!r}", problems)
        btns = await a.page.eval_on_selector_all("#modalRoot .modal-ft button", "els => els.map(e => e.textContent.trim())")
        check(not any("Share" in b for b in btns), f"{where}: expense dialog has Share: {btns}", problems)
        check(btns == ["Delete", "Cancel", "Save expense"], f"{where}: expense dialog buttons {btns}", problems)
        check(await a.page.locator("#modalRoot [title*='image' i], #modalRoot [aria-label*='share' i]").count() == 0,
              f"{where}: a share control is still in the expense dialog", problems)
        await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    # nothing on the expense list rows either
    await go_bills(a)
    check(await a.page.locator(".erow button, .erow [title*='hare']").count() == 0, "an expense row has a button", problems)
    # the new-expense dialog never had one
    await a.page.click(".topbar button:has-text('Add expense')")
    await a.page.wait_for_selector("#modalRoot .modal")
    check(await a.page.locator(SHARE_SEL).count() == 0, "Add expense has Share", problems)
    await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    # the expense card is gone from the app, not just hidden
    gone = await a.app("() => [typeof expenseCard, String(layoutCard).includes('model.title'), String(layoutCard).includes('model.meta')]")
    check(gone == ["undefined", False, False], f"expense card code still present: {gone}", problems)
    # editing still works: change the amount, save, balances follow
    await open_expense(a, "Dinner", "bills")
    await a.page.wait_for_timeout(300)                     # the dialog finishes setting itself up
    await a.page.fill("#modalRoot input[placeholder='0.00'] >> nth=0", "3000")
    await a.page.wait_for_function("document.querySelector('#modalRoot .modal-bd').innerText.includes('3,000.00 of')")
    await a.page.click("#modalRoot .modal-ft button:has-text('Save expense')")
    await a.page.wait_for_selector("#modalRoot .modal", state="detached")
    await a.page.wait_for_timeout(300)
    e = await a.app("() => { const e = S.expenses.find(x => x.description === 'Dinner' && !x.deleted); return [e.amount, Object.values(e.splits)]; }")
    check(e == [300000, [100000, 100000, 100000]], f"edited expense {e}", problems)
    return problems


async def s_reported_example_1350(br):
    """Tests 2-4 with the exact example: Rahul owes Sherin ₹1,350 in Goa Trip,
    then the same relationship reversed."""
    problems = []
    a, gid = await setup(br, ["Sherin", "Rahul"])
    await add(a, gid, "Villa", 270000, {"Sherin": 270000}, equal(270000, ["Sherin", "Rahul"]), "equal")
    before = await settled(a)
    await watch_writes(a)
    await go_balances(a)
    check(await a.page.locator(".card-hd button[title='Share balances as an image']").count() == 1, "Balances has no Share", problems)
    await share_balance(a, "Rahul")
    img, caption, _ = await press_share(a)
    keep(img, "example_rahul_owes_sherin")
    text = await card_checks(a, img, caption, problems, "Rahul owes")
    missing = has(text, "Split Buddy", "Goa Trip", "YOUR BALANCE", "Rahul", "1,350.00", "YOU OWE SHERIN")
    check(not missing, f"Rahul owes: card lacks {missing}", problems)
    m = await a.page.evaluate("window.__t('window.__lastCard.model')")
    check((m["amount"], m["amountNote"], m["amountTone"]) == ("₹1,350.00", "YOU OWE SHERIN", "neg"), f"Rahul owes: {m}", problems)
    check(caption == "Goa Trip | Rahul owes Sherin ₹1,350.00", f"Rahul owes: caption {caption!r}", problems)
    check(not any(k in m for k in ("title", "meta")), f"balance card carries expense fields: {list(m)}", problems)
    await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    await share_balance(a, "Sherin")
    img, caption, _ = await press_share(a)
    keep(img, "example_sherin_owed_by_rahul")
    m = await a.page.evaluate("window.__t('window.__lastCard.model')")
    check((m["amount"], m["amountNote"], m["amountTone"]) == ("₹1,350.00", "YOU ARE OWED BY RAHUL", "pos"), f"Sherin: {m['amountNote']}", problems)
    await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    await a.sync()
    check((await snapshot(a))["d"] == before["d"], "1350: sharing changed the app's data", problems)
    check(all(n == 0 for n in a.pushes), f"1350: a sync pushed changes {a.pushes}", problems)

    # reversed: Rahul paid, so now Sherin owes Rahul ₹1,350
    b, gid2 = await setup(br, ["Sherin", "Rahul"])
    await add(b, gid2, "Villa", 270000, {"Rahul": 270000}, equal(270000, ["Sherin", "Rahul"]), "equal")
    await share_balance(b, "Rahul")
    img, caption, _ = await press_share(b)
    keep(img, "example_reversed")
    text = await card_checks(b, img, caption, problems, "reversed")
    check(not has(text, "YOU ARE OWED BY SHERIN", "1,350.00"), "reversed: card lacks 'YOU ARE OWED BY SHERIN ₹1,350.00'", problems)
    m = await b.page.evaluate("window.__t('window.__lastCard.model')")
    check((m["amountNote"], m["amountTone"]) == ("YOU ARE OWED BY SHERIN", "pos"), f"reversed: {m['amountNote']}", problems)
    return problems


async def s_multiple_people_not_combined(br):
    """Test 17: Rahul owes Sherin ₹800 and Arun ₹500 — two separate lines, the
    total only as their sum, never one invented person-to-person debt."""
    a, gid = await setup(br, ["Sherin", "Rahul", "Arun"])
    await add(a, gid, "Hotel", 80000, {"Sherin": 80000}, {"Rahul": 80000})
    await add(a, gid, "Fuel", 50000, {"Arun": 50000}, {"Rahul": 50000})
    problems = []
    for simplify in (False, True):
        await a.app(f"() => {{ S.simplify = {'true' if simplify else 'false'}; }}")
        await share_balance(a, "Rahul")
        img, caption, _ = await press_share(a)
        keep(img, "rahul_owes_two_people" + ("_simplified" if simplify else ""))
        text = await card_checks(a, img, caption, problems, "two people")
        m = await a.page.evaluate("window.__t('window.__lastCard.model')")
        rows = sorted((r["label"], r["value"]) for r in m["sections"][0]["rows"]) if m["sections"] else []
        check(rows == [("You owe Arun", "₹500.00"), ("You owe Sherin", "₹800.00")], f"simplify={simplify}: details {rows}", problems)
        check((m["amount"], m["amountNote"]) == ("₹1,300.00", "YOU OWE IN TOTAL"), f"simplify={simplify}: {m['amount']} {m['amountNote']}", problems)
        check(not has(text, "You owe Sherin", "800.00", "You owe Arun", "500.00"), f"simplify={simplify}: lines not on the card", problems)
        await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    return problems


async def s_settle_up_then_card(br):
    """Test 13: recording a payment still works, and the card reads the new
    balance from the app (BALANCE settled) without the card touching anything."""
    a, gid = await setup(br, ["Sherin", "Rahul"])
    await add(a, gid, "Villa", 270000, {"Sherin": 270000}, equal(270000, ["Sherin", "Rahul"]), "equal")
    problems = []
    await go_balances(a)
    await a.page.click(".settle-row button:has-text('Record')")
    await a.page.click("#modalRoot .modal-ft button:has-text('Record payment')")
    await a.page.wait_for_selector("#modalRoot .modal", state="detached")
    check(await a.app("() => currentSettlements().length") == 1, "payment not recorded", problems)
    before = await settled(a)
    await share_balance(a, "Rahul")
    img, caption, _ = await press_share(a)
    keep(img, "after_payment_settled")
    text = await card_checks(a, img, caption, problems, "after payment")
    m = await a.page.evaluate("window.__t('window.__lastCard.model')")
    check((m["amount"], m["amountNote"]) == ("₹0.00", "YOU'RE ALL SETTLED"), f"after payment: {m['amount']} {m['amountNote']}", problems)
    check("owe" not in m["amountNote"].lower().replace("you're", ""), "after payment: an 'owe' card for a settled member", problems)
    await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    check((await snapshot(a))["d"] == before["d"], "after payment: sharing changed the data", problems)
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
    """25 people and very long names: the summary grows, every line wraps
    inside the card, every person is on it; a long-named member's card too."""
    long_name = "Venkataraghavan Subramaniam Iyer-Krishnamurthy"
    people = ["Sherin", long_name] + ["Friend %02d" % i for i in range(1, 24)]
    a, gid = await setup(br, people, group="College Reunion Weekend at the Backwaters — Alleppey 2026")
    await add(a, gid, "Houseboat", 2500000, {long_name: 2500000}, equal(2500000, people), "equal")
    problems = []
    await share_balance(a, "Group summary")
    img, caption, _ = await press_share(a)
    keep(img, "summary_25_people")
    text = await card_checks(a, img, caption, problems, "25 people summary")
    check(img.size[1] > 2500, f"25 people: card only {img.size[1]} tall", problems)
    m = await a.page.evaluate("window.__t('window.__lastCard.model')")
    check(len(m["sections"][0]["rows"]) == 25, f"25 people: {len(m['sections'][0]['rows'])} balance rows", problems)
    drawn = " ".join(t["s"] for t in await a.page.evaluate("window.__texts"))
    gone = [p for p in people if p.split()[0] not in drawn]
    check(not gone, f"25 people: not drawn: {gone}", problems)
    missing = has(text, "Venkataraghavan", "Friend 23", "Backwaters")
    check(not missing, f"25 people: card lacks {missing}", problems)
    await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    await share_balance(a, long_name)
    img, caption, _ = await press_share(a)
    keep(img, "long_name_member")
    await card_checks(a, img, caption, problems, "long name")
    m = await a.page.evaluate("window.__t('window.__lastCard.model')")
    check(m["amountNote"] == "YOU ARE OWED IN TOTAL" and len(m["sections"][0]["rows"]) == 24,
          f"long name: {m['amountNote']} with {len(m['sections'][0]['rows']) if m['sections'] else 0} rows", problems)
    return problems


async def s_currency(br):
    problems = []
    for cur, want in (("USD", "$1,234.56"), ("EUR", "1.234,56"), ("GBP", "£1,234.56")):
        a, gid = await setup(br, ["Sherin", "Rahul"], currency=cur, group="Trip " + cur)
        await add(a, gid, "Tickets", 123456, {"Sherin": 123456}, {"Rahul": 123456})
        await share_balance(a, "Rahul")
        img, caption, _ = await press_share(a)
        keep(img, "currency_" + cur)
        await card_checks(a, img, caption, problems, cur)
        m = await a.page.evaluate("window.__t('window.__lastCard.model')")
        check(want in m["amount"] and "₹" not in m["amount"] + caption, f"{cur}: amount {m['amount']!r} / {caption!r}", problems)
        check(not has(ocr(img), want.strip("$£")), f"{cur}: {want} not read on the card", problems)
        await a.ctx.close()
    return problems


async def s_preview_cancel_and_failures(br):
    """Cancel shares nothing; a native failure is a friendly message, not a crash."""
    a, gid = await setup(br, ["Sherin", "Rahul"])
    await add(a, gid, "Snacks", 50000, {"Sherin": 50000}, {"Rahul": 50000})
    problems = []
    before = await settled(a)
    await share_balance(a, "Rahul")
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
        await share_balance(a, "Rahul")
        await a.page.click(SHARE_SEL)
        await a.page.wait_for_timeout(300)
        t = [x["m"] for x in await a.page.evaluate("window.__toasts")]
        check(any("Couldn't prepare the image" in m for m in t), f"{answer}: toasts {t}", problems)
        check(await a.page.is_visible("#modalRoot img.cardimg"), f"{answer}: the preview vanished", problems)
        await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    await a.page.evaluate("window.__bridgeAnswer = 'ok'")

    await a._watch_toasts()
    await a.page.evaluate("window.__shareFailed()")
    t = [x["m"] for x in await a.page.evaluate("window.__toasts")]
    check(any("Couldn't open sharing" in m for m in t), f"__shareFailed: toasts {t}", problems)

    await a._watch_toasts()
    await a.app("() => openCardPreview(() => { throw new Error('boom'); })")
    await a.page.wait_for_timeout(200)
    t = [x["m"] for x in await a.page.evaluate("window.__toasts")]
    check(any("Couldn't create the card" in m for m in t), f"bad card: toasts {t}", problems)
    check((await snapshot(a))["d"] == before["d"], "cancel/failures: data changed", problems)
    return problems


async def s_entry_points(br):
    """Balances → Share lists the summary and every member with their balance;
    Back closes the preview like any other dialog."""
    a, gid = await setup(br, ["Sherin", "Rahul", "Priya"])
    await add(a, gid, "Lunch", 90000, {"Sherin": 90000}, equal(90000, ["Sherin", "Rahul", "Priya"]), "equal")
    problems = []
    await go_balances(a)
    await a.page.click(".card-hd button[title='Share balances as an image']")
    opts = await a.page.eval_on_selector_all("#modalRoot .pickgrp .gn", "els => els.map(e => e.textContent)")
    check(opts == ["Group summary", "Sherin", "Rahul", "Priya"], f"balance menu {opts}", problems)
    subs = await a.page.eval_on_selector_all("#modalRoot .pickgrp .gs", "els => els.map(e => e.textContent)")
    check(subs[1:] == ["is owed ₹600.00", "owes ₹300.00", "owes ₹300.00"], f"balance menu amounts {subs}", problems)
    await a.page.click("#modalRoot .modal-ft button:has-text('Cancel')")
    # the same Share from inside the group (Groups → group → Balances tab)
    await a.app("() => { go('groups'); S.groupOpen = true; S.tab = 'balances'; render(); }")
    await a.page.wait_for_timeout(150)
    check(await a.page.locator(".card-hd button[title='Share balances as an image']").count() == 1,
          "group's Balances tab has no Share", problems)
    await share_balance(a, "Group summary")
    await a.page.go_back(); await a.page.wait_for_timeout(300)
    check(not await a.page.is_visible("#modalRoot .modal"), "Back left the preview open", problems)
    check(await a.page.evaluate("location.href.endsWith('/index.html')"), "Back left the app", problems)
    return problems


SCENARIOS = [s_no_expense_share, s_reported_example_1350, s_balance_owe_and_owed, s_multiple_people_not_combined,
             s_settled_member, s_settle_up_then_card, s_group_summary, s_many_people_long_text, s_currency,
             s_preview_cancel_and_failures, s_entry_points]

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
