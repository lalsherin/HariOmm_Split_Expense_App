/* Transform the artifact page into the offline asset shipped inside the APK.
   Every replacement is asserted so a silent mismatch can't ship. */
const fs = require("fs");
const path = require("path");
/* Paths are relative to this file so the repository builds anywhere, and
   overridable for the scratch layout used while developing. */
const SRC = process.env.SL_SRC || path.join(__dirname, "..", "web", "split-ledger.html");
const OUT = process.env.SL_OUT || path.join(__dirname, "assets", "index.html");

let s = fs.readFileSync(SRC, "utf8");
const reps = [];
function rep(name, from, to) { reps.push({ name, from, to }); }

/* 1 — drop the web-font links (no network on the phone build) */
rep("fontlinks",
  `<title>Hariomm_Split_expense</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=Instrument+Sans:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
`, "");

/* 2 — system font stacks in place of the Google faces */
rep("fonts",
  `  --font-display: "Bricolage Grotesque", "Instrument Sans", system-ui, sans-serif;
  --font-body: "Instrument Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;`,
  `  --font-display: system-ui, "Roboto", "Segoe UI", sans-serif;
  --font-body: system-ui, "Roboto", "Segoe UI", sans-serif;
  --font-mono: ui-monospace, "Roboto Mono", "Droid Sans Mono", monospace;`);

/* 3 — phone chrome: safe areas, no tap highlight, no rubber-banding */
rep("appcss", `@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}`, `@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}

/* --- phone app chrome --- */
body {
  -webkit-tap-highlight-color: transparent;
  overscroll-behavior-y: none;
  -webkit-text-size-adjust: 100%;
}
.topbar { padding-top: calc(16px + env(safe-area-inset-top)); }
.rail { padding-top: env(safe-area-inset-top); }
.rail-foot { padding-bottom: calc(10px + env(safe-area-inset-bottom)); }
.content { padding-bottom: calc(60px + env(safe-area-inset-bottom)); }
.modal { max-height: min(88vh, 900px); }
textarea { resize: vertical; font-family: var(--font-mono); }
@media (max-width: 780px) {
  .topbar { padding-top: calc(12px + env(safe-area-inset-top)); }
  .hero-figure { font-size: 34px; }
  .btn { padding: 9px 14px; }
  .tab { padding: 10px 13px 12px; }
}`);

/* 4 — the "shared storage" banner has no meaning in an offline app */
rep("banner",
  `  if (S.offline) v.appendChild(el("div", { class: "banner warn", html: "<strong>Working offline.</strong>&nbsp;Shared storage isn’t available in this view, so changes stay in this browser only." }));
`, "");

/* 5 — a Backup button in the rail footer */
rep("backupbtn",
  `      <button class="btn btn-sm btn-ghost" id="themeBtn" title="Toggle theme" aria-label="Toggle theme">`,
  `      <button class="btn btn-sm btn-ghost" id="backupBtn" title="Backup & restore" aria-label="Backup and restore">
        <svg class="icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2v7M5.2 6.2L8 9l2.8-2.8M2.8 11v1.6c0 .6.5 1.1 1.1 1.1h8.2c.6 0 1.1-.5 1.1-1.1V11"/></svg>
      </button>
      <button class="btn btn-sm btn-ghost" id="themeBtn" title="Toggle theme" aria-label="Toggle theme">`);

/* 6 — hardware back button.
   Whatever is open becomes a history entry; Android's back unwinds them
   newest-first. Closing something from the UI removes its own entry and
   swallows the resulting popstate, so it never cascades into whatever is
   still open underneath (this is what closed the New-group dialog on the
   first tap when the drawer was open behind it). */
rep("closeModal",
  `function closeModal() { $("#modalRoot").innerHTML = ""; document.removeEventListener("keydown", escClose); }`,
  `var backStack = [], pendingPops = 0;
function pushBack(key, closeFn) {
  backStack.push({ key: key, close: closeFn });
  try { history.pushState({ sl: key }, ""); } catch (e) { }
}
function releaseBack(key) {
  for (var i = backStack.length - 1; i >= 0; i--) {
    if (backStack[i].key !== key) continue;
    var wasTop = (i === backStack.length - 1);
    backStack.splice(i, 1);
    if (wasTop) { pendingPops++; try { history.back(); } catch (e) { pendingPops--; } }
    return;
  }
}
window.addEventListener("popstate", function () {
  if (pendingPops > 0) { pendingPops--; return; }   // our own history.back(), already handled
  var top = backStack.pop();
  if (top) top.close();                             // closers are idempotent, never touch history
});
function closeModalRaw() { $("#modalRoot").innerHTML = ""; document.removeEventListener("keydown", escClose); }
function closeModal() { closeModalRaw(); releaseBack("modal"); }`);

rep("openModalHead",
  `function openModal(title, bodyNodes, footNodes) {
  const root = $("#modalRoot"); root.innerHTML = "";`,
  `function openModal(title, bodyNodes, footNodes) {
  const root = $("#modalRoot");
  const hadModal = !!root.innerHTML;
  root.innerHTML = "";`);

rep("openModalPush",
  `  scrim.appendChild(m);
  root.appendChild(scrim);
  document.addEventListener("keydown", escClose);`,
  `  scrim.appendChild(m);
  root.appendChild(scrim);
  if (!hadModal) pushBack("modal", closeModalRaw);
  document.addEventListener("keydown", escClose);`);

rep("setRail",
  `function setRail(open) { $("#rail").classList.toggle("open", !!open); }`,
  `function railCloseRaw() { $("#rail").classList.remove("open"); }
function setRail(open) {
  const isOpen = $("#rail").classList.contains("open");
  if (open && !isOpen) { $("#rail").classList.add("open"); pushBack("rail", railCloseRaw); }
  else if (!open && isOpen) { railCloseRaw(); releaseBack("rail"); }
}`);

/* 6a — the phone build ships pointed at the project's own server, so a new
   install syncs with nothing to configure. Overridable and switch-off-able in
   Account -> Sync server, which stores an empty string and wins over this. */
const SERVER = process.env.SL_SERVER || "https://split-ledger-71my.onrender.com";
rep("serverDefault",
  `function serverUrl() { return String(LS.get("sl.server", "") || "").replace(/\\/+$/, ""); }`,
  `/* Built in so the app works out of the box. Account -> Sync server overrides
   it; emptying that box stores "" and turns syncing off. */
const DEFAULT_SERVER = ${JSON.stringify(SERVER)};
function serverUrl() { return String(LS.get("sl.server", DEFAULT_SERVER) || "").replace(/\\/+$/, ""); }`);

/* 6b — lock and server sync are phone-build features */
rep("lockOn", `const LOCK_ENABLED = false;`, `const LOCK_ENABLED = true;`);
rep("syncOn", `const SYNC_ENABLED = false;          // the phone build turns this on`,
             `const SYNC_ENABLED = true;           // on in the phone build`);

/* 7 — boot: local storage only, plus backup/restore. No demo data. */

rep("boot", `applyStoredTheme();
S.gid = LS.get("sl.lastGroup", null);
render();

(async function boot() {
  let db = null;
  try { db = window.claude && window.claude.use ? await window.claude.use("db") : null; } catch (e) { db = null; }
  if (db) {
    S.db = db;
    subscribeGroups();
  } else {
    S.offline = true; S.ready = true;
    localLoad();
    if (!S.gid || !S.groups.some(g => g.id === S.gid)) S.gid = S.groups[0] ? S.groups[0].id : null;
    S.group = S.groups.find(g => g.id === S.gid) || null;
    render();
  }
})();`, `/* ---------- backup & restore ---------- */
function openBackupModal() {
  const payload = JSON.stringify({ app: "split-ledger", version: 1, exportedAt: nowISO(), groups: S.groups, expenses: S.expenses, settlements: S.settlements });
  const out = el("textarea", { rows: "6", readonly: "readonly" });
  out.value = payload;
  const inp = el("textarea", { rows: "4", placeholder: "Paste a backup here" });
  const note = el("div", { class: "hint", style: "color:var(--neg)" });
  const body = [
    el("div", { class: "field" }, [
      el("label", { text: "Your data" }), out,
      el("div", { class: "hint", text: S.groups.length + " groups · " + S.expenses.length + " expenses · " + S.settlements.length + " payments. Copy this somewhere safe — it's the only copy." })
    ]),
    el("div", { class: "field" }, [
      el("label", { text: "Restore from a backup" }), inp,
      el("div", { class: "hint", text: "Restoring replaces everything currently in the app." })
    ]),
    note
  ];
  const copy = el("button", {
    class: "btn", text: "Copy", onclick: () => {
      out.focus(); out.select();
      try { out.setSelectionRange(0, 999999); } catch (e) { }
      try { document.execCommand("copy"); toast("Backup copied"); } catch (e) { toast("Select the text and copy it by hand."); }
    }
  });
  const restore = el("button", {
    class: "btn btn-danger", text: "Restore", onclick: () => {
      note.textContent = "";
      let d = null;
      try { d = JSON.parse(inp.value); } catch (e) { }
      if (!d || !Array.isArray(d.groups)) { note.textContent = "That doesn't look like a Split Buddy backup."; return; }
      closeModal();
      confirmModal({
        title: "Replace everything?",
        danger: true, confirmLabel: "Restore backup",
        message: "The backup holds <strong>" + d.groups.length + "</strong> "
          + (d.groups.length === 1 ? "group" : "groups") + " and <strong>"
          + ((d.expenses || []).length) + "</strong> expenses.\\n\\nEverything currently in the app is discarded and replaced.",
        onConfirm: () => {
          S.groups = d.groups; S.expenses = d.expenses || []; S.settlements = d.settlements || [];
          localSave();
          S.gid = S.groups[0] ? S.groups[0].id : null;
          S.group = S.groups.find(x => x.id === S.gid) || null;
          LS.set("sl.lastGroup", S.gid);
          render(); toast("Backup restored");
        }
      });
    }
  });
  openModal("Backup & restore", body, [restore, copy, el("button", { class: "btn btn-primary", text: "Done", onclick: closeModal })]);
}
$("#backupBtn").addEventListener("click", openBackupModal);

/* ---------- first run ----------
   Nothing is seeded. A new install opens empty, so every group anyone ever
   sees is either one they made or one they were added to by number.

   Builds before 2.4 shipped a demo group, "Goa Trip 2026". It is cleared here
   on upgrade — but only while it is still exactly as it shipped. If the ids in
   it do not match the ones that were seeded, somebody has been using it as a
   real group, and it is left alone rather than deleted under them. */
const DEMO_GID = "goa-sample";
const DEMO_EXPENSES = ["e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8"];
const DEMO_SETTLEMENTS = ["s1"];

function sameIds(got, want) {
  if (got.length !== want.length) return false;
  const w = {};
  want.forEach(id => { w[id] = true; });
  return got.every(id => w[id]);
}

function dropDemoGroup() {
  if (!S.groups.some(g => g.id === DEMO_GID)) return;
  const exp = S.expenses.filter(e => e.gid === DEMO_GID).map(e => e.id);
  const set = S.settlements.filter(s => s.gid === DEMO_GID).map(s => s.id);
  if (!sameIds(exp, DEMO_EXPENSES) || !sameIds(set, DEMO_SETTLEMENTS)) return;
  S.groups = S.groups.filter(g => g.id !== DEMO_GID);
  S.expenses = S.expenses.filter(e => e.gid !== DEMO_GID);
  S.settlements = S.settlements.filter(s => s.gid !== DEMO_GID);
  try { localStorage.removeItem(meKey(DEMO_GID)); } catch (e) { }
  if (LS.get("sl.lastGroup", null) === DEMO_GID) LS.set("sl.lastGroup", null);
  localSave();
}

applyStoredTheme();
localLoad();
dropDemoGroup();
S.ready = true;
S.gid = LS.get("sl.lastGroup", null);
// A group hidden on this phone must not be the one we open on.
if (!S.gid || !liveGroups().some(g => g.id === S.gid)) S.gid = liveGroups()[0] ? liveGroups()[0].id : null;
S.group = S.groups.find(g => g.id === S.gid) || null;
render();

/* ---------- who you are, then the lock, then the ledger ---------- */
$("#lockBtn").hidden = false;
watchIdle();
drawSyncBar();

window.addEventListener("online", () => scheduleSync(500));
document.addEventListener("visibilitychange", () => { if (!document.hidden) scheduleSync(900); });
setInterval(() => { if (!document.hidden) scheduleSync(0); }, 120000);

if (!myIdentity()) {
  showAuth();
} else if (lockIsSet()) {
  showLock("locked");
} else {
  if (!LS.get("sl.lockSkipped", false)) showLock("setup");
  scheduleSync(600);
}`);

/* apply */
for (const r of reps) {
  const n = s.split(r.from).length - 1;
  if (n !== 1) { console.error("FAILED replacement '" + r.name + "' matched " + n + " times"); process.exit(1); }
  s = s.replace(r.from, () => r.to);
}

/* guard: nothing cloud-specific may survive into the phone build */
["window.claude", "fonts.googleapis", "fonts.gstatic", "claude.use("].forEach(bad => {
  if (s.indexOf(bad) >= 0) { console.error("FORBIDDEN token left in asset: " + bad); process.exit(1); }
});

const doc = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<title>Split Buddy</title>
</head>
<body>
${s}
</body>
</html>
`;
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, doc);
console.log("wrote " + OUT + " (" + (doc.length / 1024).toFixed(1) + " KB), " + reps.length + " replacements applied");
