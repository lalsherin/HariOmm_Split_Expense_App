# Build notes

How the APK is produced, why it is put together the way it is, and what has
actually been verified.

## The two builds share one file

`web/split-ledger.html` is the application. `android/build_asset.js` turns it
into `android/assets/index.html`, the page bundled inside the APK, by applying a
fixed list of source replacements. Each replacement asserts that it matched
**exactly once** — if the web file drifts so that an anchor no longer matches,
the build fails loudly rather than silently shipping a half-transformed page.

The four differences in the phone build:

1. **Storage.** The web build can use the Claude Artifact document store so that
   several people see the same groups live. The phone build has no network, so
   that branch is removed and everything goes to `localStorage`. After the
   transform the output is scanned for `window.claude`, `claude.use(` and the
   font hosts; any hit aborts the build.
2. **Fonts.** The Google Fonts links are dropped and system font stacks
   substituted, since nothing can be fetched at runtime.
3. **Hardware back button.** Opening a dialog or the groups drawer pushes a
   history entry, so `WebView.canGoBack()` in `MainActivity.onBackPressed()`
   unwinds them one at a time before the app exits. Entries are tracked in a
   small LIFO stack of `{key, close}` pairs with a `pendingPops` counter, so a
   close triggered from the UI removes only its own entry and swallows the
   `popstate` it causes — without that counter, closing a dialog cascaded into
   closing the drawer underneath it.
4. **Backup & restore**, and a first-run sample group — there is no cloud copy
   of the data, so the app has to be able to hand it back to you as text.

## No Gradle, no dex compiler

The build environment had no access to `dl.google.com`, `maven.google.com` or
Maven Central, which rules out the Android Gradle Plugin and every normal route
to `d8`. The Ubuntu archive supplies most of what is needed:

```sh
sudo apt install android-sdk-build-tools aapt apksigner zipalign android-sdk-platform-23
```

— `aapt`/`aapt2`, `apksigner`, `zipalign`, and an API-23 `android.jar` to
compile against. What it does not supply is a Java-to-Dalvik compiler. Ubuntu
packages none, and the `dx` package in apt is OpenDX, an unrelated scientific
visualisation suite.

The way around it: skip Java entirely. The Activity is written directly in
**smali** — one class, two methods, about 60 lines — and assembled with the
smali assembler that ships inside `apktool.jar`, reached through a six-line
driver (`Dexer.java`) that calls `brut.androlib.src.SmaliBuilder.build`.

That leaves the resulting dex referencing only `android/*`, `java/*` and
`com.sherinlal.splitledger.MainActivity`. Nothing third-party is compiled into
the APK.

### Order of operations

```
smali/            --Dexer-->     build/classes.dex
AndroidManifest + res + assets   --aapt package-->  build/app.apk
build/classes.dex                --aapt add-->      build/app.apk
                                 --zipalign -p 4--> build/app.aligned.apk
                                 --apksigner-->     dist/split_expense.apk
```

`zipalign` must run before `apksigner`; the signer preserves alignment, but not
the other way round.

## Launcher icons

`make_icons.py` draws them with nothing but `zlib` and `struct` — a rounded navy
tile with three ledger rules, 4× supersampled, emitted as RGBA PNGs at five
densities, plus transparent foregrounds and an `adaptive-icon` XML for API 26+.
No image library required.

## Signing

Released with a self-signed 2048-bit RSA key (SHA256withRSA, 30-year validity),
using the v1, v2 and v3 schemes together — v1 alone is rejected by Android 11+
for apps targeting API 30 and above.

**The keystore is not in this repository, by design.** Whoever holds it can
publish something Android will accept as an update to this app. An APK signed
with a different key cannot install over an existing install; Android treats it
as an unrelated app.

## Verification

What has been checked:

- `apksigner verify` — v1, v2 and v3 all pass. `zipalign -c 4` clean.
- `aapt dump badging` and `aapt dump xmltree` — package, versions, label,
  launcher intent-filter, `android:exported`, `minSdk` 21 / `targetSdk` 33.
- The dex string table — only `android/*`, `java/*` and the app's own class.
- **Money logic**, in Node: fixed cases for every split type plus 400 randomized
  trials (3–7 members, 8 expenses, mixed split types). Each trial asserts splits
  sum exactly to the expense total, net balances sum to zero, pairwise debts
  reconcile to the same net positions, and applying the simplified transfers
  leaves everyone at exactly zero.
- **UI**, by driving the `assets/index.html` extracted from the *signed* APK in
  a 412×915 browser: sample seeding, adding a shares-split expense and finding
  it after a reload, drawer and dialog interaction, back-button layering,
  backup generation, both themes, and no horizontal overflow.

What has **not** been checked: the APK has never run on a real device or an
emulator. No emulator was reachable from the build environment — the system
images come from the same blocked hosts. Everything above is static analysis of
the package plus dynamic testing of the page it carries.

## Changelog

### 3.6 (versionCode 20)

**The removed group that came back.** Reported with screenshots, and they
showed something more precise than the description: the group list had the same
number of rows before and after, with one group gone and a previously removed
one back in its place. A *swap*. That is the signature of one list replacing
another rather than being added to.

Root cause, `applyPull()` in `web/split-ledger.html`. The merge of the server's
hidden list was written as "adopt the server's, keeping anything still pending":

```js
const next = data.hidden.filter(id => pending.indexOf(id) < 0)
  .concat(pending.filter(id => mine.indexOf(id) >= 0));
```

Anything in the local list that the server had not been told about, and that
was not in the outbox at that moment, was silently dropped. That is **every
removal made on 3.2, 3.3 or 3.4** — where the list lived only on the phone and
the server had no idea — and every removal whose push had not landed. The next
sync wiped it, and the most visible trigger for a sync is removing the next
group. Hence "remove the second one and the first comes back".

Reproduced first, with a test that seeds exactly that state: the list came back
as `["<goa-id>"]` with the other id erased, and the group reappeared.

**The fix is that removal is now one-way.** The merge is a union: a sync can
only ever add to the removed list, never take from it. And anything this phone
knows about that the server does not is queued to be *sent* — the two converge
by telling the server rather than by forgetting. Self-healing, so a removal
made on an older build, or one whose push failed while the host was asleep,
repairs itself on the next successful sync instead of being undone by it.

**Restore is gone.** Being able to put a group back was what made removal feel
provisional, and provisional state is what let a sync quietly reverse it. Also
removed, with no leftovers: `unhideGroup()`, `hiddenGroupsField()`, the Account
section, the Undo on the toast, and the toast-action mechanism and CSS that
existed only to carry it.

**Both dialogs now say what they mean**, and they are no longer near-identical:

| | title | button |
|---|---|---|
| member | Remove this group? | Remove from my account |
| creator | Delete this group for everyone? | Delete for everyone |

The member's message says the others keep it, that they are still in the group
and their share still counts, and that it cannot be undone.

**Being added back clears a removal** (`app/sync/service.py`). Without it,
permanent removal makes re-adding someone a dead end: a member of a group they
can never see, with no way out. A *new* member row linking that account to that
group now deletes their `group_hidden` row.

Tests: `resurrect.mjs` reproduces the exact reported sequence and also removes
a group while a stand-in host is asleep, then checks it is still gone a minute
after the host wakes. `removal.mjs` (replacing `admindelete.mjs`) covers five
groups with three removed and repeated syncs, a new group and an owner deletion
in between, an app restart, both other members left untouched, and that no
Restore exists anywhere. Two new backend tests: removal is one-way across
repeated syncs, and re-adding clears it. **80 backend tests pass.**

### 3.5 (versionCode 19)

**A central record of who has signed up.** Most of it already existed — this
extends it rather than adding a second identity system, which is what the
request asked for and also the only safe option: `users` is what every session,
group member and expense already points at.

Already there, unchanged: `users.id` (uuid4), `mobile_number` (E.164, unique,
indexed — the identity), `name`, `created_at`, `last_login_at`,
`account_status` (the is-active flag), `mobile_verified`, and a full
`login_history` table recording every sign-in attempt with its outcome.
`register_or_login()` was already find-then-create-or-update keyed on the
normalised number, so repeated sign-ins were already idempotent.

Added:

- **`users.last_seen_at`** — written by the auth dependency, which is the one
  place every authenticated request passes through, so there is no separate
  heartbeat endpoint to build or call. Throttled to **once per 15 minutes**:
  a phone with the app on screen makes about 280 sync requests an hour, and
  writing on each would be 280 pointless UPDATEs per user per hour on a
  free-tier database to record something nobody needs to the second.
- **`users.app_version`** — from a new `X-App-Version` header the app sends on
  every request, taken from `APP_VERSION` so it cannot go stale. Captured at
  sign-in too, since a session lasts 30 days and a phone may not sign in again
  for weeks. "Which build is this person on?" is most of the work in any sync
  complaint, and until now it was unanswerable.

**Adding a column to a live table.** This is the part that could have broken
Neon. `create_all` creates missing *tables*; it does not add missing *columns*.
The moment `last_seen_at` existed in the models and not in the database, every
query naming it would fail with UndefinedColumn — the whole server down, on
deploy. `_ensure_columns()` in `database.py` closes that: idempotent, additive,
dialect-aware, and deliberately able to do only one thing — add a nullable
column with no default, which in Postgres is a catalogue update that does not
rewrite the table. Anything else still needs a considered migration.

Rehearsed rather than assumed: a local PostgreSQL was set up with the schema as
it is in production today (old columns only) and real rows in `users`,
`groups`, `group_members` and `expenses`. The upgrade path was then run exactly
as a Render boot runs it. Columns added, `timestamp with time zone` not text,
every existing row intact, new columns NULL on old rows, second run a no-op —
then sign-in matched the *existing* account rather than creating a duplicate,
`/users/me` returned the new fields, and sync returned the group and expense
that were already there.

**The suite now runs against real PostgreSQL**, not only SQLite:
`TEST_DATABASE_URL=postgresql://… python3 -m pytest`. That needed `DB_POOL=null`
(NullPool), because pytest gives each test its own event loop while a pooled
asyncpg connection belongs to the loop that opened it — without it the suite
cannot be run against the real engine at all, and "it passes on SQLite" is a
weaker claim than it looks. **78 passed on both.**

**No endpoint lists users.** `/users/me` returns one account's own row; nothing
anywhere returns somebody else's. A listing endpoint would hand out mobile
numbers, on a server where `REQUIRE_OTP=false` means anyone can sign in as any
number. Neon's own console is already an authenticated admin view; `docs/PROJECT.md`
has the query.

### 3.4 (versionCode 18)

Two defects, both found by reproducing them rather than by reading.

**A group created while the host was waking up took two minutes to go out —
and a hung token refresh could stop the app syncing for good.**

`syncNow`'s catch block scheduled nothing. A failed sync left no timer alive,
so the only thing that ever tried again was the two-minute tick. A free host
sleeps when idle and takes 30–60 seconds to wake, while every request is
abandoned at 20 — so the first group made after a quiet spell sat unsent while
the app did nothing at all. Measured against a stand-in that wakes in 45s:
**114 seconds** to reach the other phone, with four requests made in that time.
Now: bounded exponential backoff, 2s → 4s → 8s → 16s → 32s → 60s, reset on
success and paused while the app is in the background. Same test: **51
seconds**, i.e. about six seconds after the server was actually available.

Worse, and the likely cause of "it worked for a while and then stopped":
`doRefresh()` built its `fetch` with **no AbortController**, while every other
request in the app is abandoned at 20 seconds. `api()` also clears its own
timeout *before* it inspects the status code. So a `/auth/refresh-token`
request that was accepted and never answered — precisely what a container or
a database that is still waking does — hung for ever. The sync waiting on it
never returned, `SYNC.running` stayed true for the life of the page, and every
later sync bounced straight off it without touching the network. Reproduced:
**0 sync attempts in 40 seconds, and still stuck 150 seconds after the server
was healthy again.** Only force-closing the app cleared it.

Three changes, because one was not enough:

- **`timedFetch`** — one helper, one deadline, used by every request including
  the refresh.
- **A watchdog.** A request still "in flight" after 45 seconds is not in
  flight; `unwedge()` clears the flag. A single stuck flag should never be able
  to disable an app permanently, whatever causes it.
- **The first sync after each launch asks for everything** (`since = 0`) and
  reconciles by row id. It is the one moment the phone can check its whole
  picture against the server's, which also covers a counter that is somehow
  ahead of the server's — after a restore, or if the database is ever rebuilt.
  Rows are matched by id, so asking twice changes nothing.

**Rate limits sized before long polling existed.** An idle phone with the app
on screen makes about 280 sync requests an hour; the limit was 600. Two busy
phones on one account, or a stretch of heavy use, would have started getting
429s that look exactly like "sync has stopped working". Now 3000. And
`RL_AUTH_PER_NUMBER` was at its default of **10 an hour** — the app signs
itself in again when a refresh token turns out to be unusable, so ten is close
enough to normal behaviour to lock a real person out for an hour. Now 60.

**Removing a group from your own view now survives a reinstall.** In 3.2 that
was `sl.hidden` in localStorage and nowhere else, so a wipe brought every
removed group back. New `group_hidden` table (`user_id`, `group_id`,
`hidden_at`) — the smallest thing that lets the data model say *gone for this
one account* as distinct from `groups.deleted`, which means *gone for
everyone*. The pull returns each account only its own list, in full rather than
as a delta; there are only ever a handful, and a complete list is something the
phone can adopt rather than reconcile. **It is never sent to anyone else** —
the others are still not told, which was the point of the rule. Created
automatically on startup like every other table; no migration needed, and an
older server simply omits the field and the behaviour falls back to being local
to one phone.

### 3.3 (versionCode 17)

Shipped after a report that groups had stopped reaching the other phone since
3.1. Every existing test passed, including two written specifically to
reproduce it — phones with accounts and data from previous days, an app closed
and reopened, and a 3.2 phone talking to a 3.0 server. Groups arrived every
time, in 0.6s against a current server and inside two minutes against an old
one. So the delivery path was not broken.

What *was* broken was the app's answer when you ask it.

**Account → Save reported failure when nothing had failed.** Since 3.1 the app
spends nearly all its time holding a sync request open, and `syncNow(manual)`
began with:

```js
if (SYNC.running) { cancelHold(); scheduleSync(...); return false; }
```

`false` means "that failed" to every caller. So Save — the documented way to
force a sync, and the first thing anyone tries when they think sync is
broken — answered *"Couldn't reach that server"* almost every time, on a
perfectly healthy server. Data was never affected: the hold was cancelled and
the sync went through 60ms later. The message was simply a lie, and it is the
kind of lie that turns a working system into a support problem.

Fixed: a manual sync now waits for the cancelled request to let go
(`settleInFlight`, milliseconds in practice) and then performs the real sync
and reports what actually happened. If it genuinely cannot get a turn inside
five seconds it says *"Still syncing — give it a moment"* rather than blaming
the network.

**Account → Connection check** (new). "My friend hasn't got the group" has
about six causes and the app showed none of them — the status dot reads
*Synced* in most, because from that phone's point of view everything did work.
One screen now answers it:

- is the server answering, and how fast;
- **which build the server is running** — `/health` now returns `build`, so a
  phone can finally tell whether a redeploy actually took. "It's on GitHub" and
  "it's running on Render" are different things and the difference has already
  cost an evening. A server too old to report its version says so.
- who this phone is signed in as;
- the result of a sync run there and then;
- anything still queued to send;
- and the one that is usually the answer: **for every member of the current
  group, whether anyone has actually signed in with that number.** A member
  whose number belongs to no account is a placeholder — the group looks
  perfectly healthy on the phone that made it and does not exist on theirs.
  Until now nothing anywhere said so.

Nothing on that screen is secret — no tokens, no passwords — so it is safe to
screenshot and send on. There is a Copy button for the same reason.

**`check_version.py`**, wired into both builds: the app's `APP_VERSION`, the
server's `SERVER_BUILD` and the manifest's `versionName` must agree or the
build fails. A version marker that silently goes stale is worse than none,
because the whole point is to be believed weeks later by someone debugging.

### 3.2 (versionCode 16)

**Deleting a group now means two different things depending on who you are.**

- **Whoever created the group** deletes it for everybody, as before. The
  tombstone syncs and it goes from every phone in the group.
- **Everyone else** only clears it off their own phone. They stay in the group,
  their share of every expense still counts in everyone else's balances, and
  nobody is told. It is reversible — an Undo on the toast, and a *Removed from
  this phone* list in Account.

The two are told apart at the moment of the tap: different dialog title,
different message, different button (*Delete for everyone* vs *Remove from my
phone*), and a different tooltip on the bin in the group list.

How the creator is known: the server already recorded `created_by` on a group
the first time it was pushed, and already sent it back on every pull — it was
simply never stored on the phone. It is now (`g.ownerId`), and `iAmAdmin()`
compares it against the signed-in account. A group with no recorded creator is
one that has never been near a server, so it belongs to the phone it is on and
that phone may do as it likes with it.

**The rule is enforced on the server, not just in the app** (`app/sync/service.py`).
A hidden button is not a rule: an older build — 3.1 included — sends a real
tombstone when a member presses Delete, and without the server check it would
wipe out everyone else's records. A group tombstone from anyone but the creator
is now refused with `not_the_creator`.

One subtlety that took a second pass. Deleting a group also tombstones every
member, expense and settlement inside it, and those rows travel in the *same*
request. Refusing only the group would have left it standing and empty — worse
than either outcome. So a refused group delete now also blocks the tombstones
riding along with it in that request. There is a test for exactly this.

Local-only, never pushed: `sl.hidden`, the list of group ids hidden on this
phone. The server has no idea it exists, which is the point — hiding changes
nothing for anybody else. Hidden groups still sync in the background, so
restoring one brings it back up to date rather than frozen at the moment it
was hidden. An id whose group has since been deleted for everyone is dropped
from the list on sight.

Five new server tests and a two-phone browser test (`admindelete.mjs`, 27
checks) covering both paths, the Undo, the Account restore, and the case where
the creator deletes a group the other phone had already hidden.

### 3.1 (versionCode 15)

**A group made on one phone now appears on the other in about a second**,
instead of somewhere inside the next two minutes. Measured: 0.0–0.2s for a new
group, 0.8–1.0s for an expense, in `instant.mjs` with one phone left completely
untouched.

There is no push notification involved, and this is the honest limit of it: it
works while the other person has the app **open on screen**. A phone with the
app closed or in the background still finds out when it is next opened. Real
push needs Firebase, a Google project, and a Gradle build — none of which this
repository has.

What actually changed:

- **The server may hold a request open** (`app/sync/router.py`). A phone with
  nothing to send now asks for up to 15 seconds of patience via a new `wait`
  field. Rather than re-running the four per-table pull queries in a loop, the
  hold watches the single global `Counter` row — one cheap read every 0.75s,
  with a `commit()` between checks so the database connection goes back to the
  pool instead of being tied up for the whole wait. A real pull only runs when
  that counter has actually moved. 15s is deliberately well inside the 20s the
  app abandons a request at, so a wait never surfaces as "No connection".
- **The wait is cut short the moment there is something to send**
  (`cancelHold()`). Without this, adding an expense would queue behind a
  request that might sit for another fourteen seconds — which is exactly what
  the first measurement showed: 8.6s to deliver a group, almost all of it the
  creating phone waiting for its own idle request to end.
- **The app goes straight back to waiting after every sync**, not just after a
  held one. Previously a phone that had just pushed something dropped back to
  the two-minute timer, so the person who created a group was the last to hear
  about anything that happened in it.
- **A held request no longer reads "Syncing…".** It is waiting, not working;
  the status stays *Synced*, which is the truth.
- **It degrades on an old server.** If three held requests come back instantly
  and empty, the server predates `wait`, long polling switches itself off, and
  the app falls back to the two-minute poll rather than hammering it every
  250ms. So a phone on 3.1 is safe against a Render deployment still running
  3.0 — it is simply no faster until the server is updated.
- Backgrounding stops it dead: `document.hidden` disables the hold, and the
  test asserts a hidden page makes at most one request in six seconds.

Four new server tests cover the wake-up, the timeout, the cap, and the rule
that a request carrying changes is never held.

### 3.0 (versionCode 14)

- **Renamed to Split Buddy** — the launcher label (`res/values/strings.xml`),
  the title bar, the welcome screen, the lock screen, and every sentence in the
  UI that named the app.

Two things deliberately keep the old name, and both would cause real damage if
they were changed to match:

- **The package id stays `com.sherinlal.splitledger`.** Android identifies an
  app by its package, not its label. Changing it produces a *different* app:
  it installs alongside the old one instead of updating it, and everything on
  the old install — including anything that never synced — is stranded there.
- **A backup file still carries `"app": "split-ledger"`.** That marker is what
  Restore checks before it will read a file. Renaming it would make every
  backup taken with an earlier build fail to restore.

### 2.9 (versionCode 13)

**2.7 and 2.8 do not start. Both crash on launch. Use this build instead.**

```
java.lang.VerifyError: Verifier rejected class …MainActivity:
  void …MainActivity.run() failed to verify: [0x10]
  tried to get class from non-reference register v3 (type=PositiveByteConstant)
```

The permission request added in 2.7 was written into `run()`, which declares
`.registers 4`. Parameters live in the LAST registers of a dex frame, so with
one parameter `this` sits in **v3** — and the new code did `const/4 v3, 0x0`
for an array index. `this` became the integer 8; the next `invoke-virtual`
tried to call a method on a number; the verifier rejected the class at load
time and the Activity never instantiated.

`run()` now declares `.registers 5`, leaving v0-v3 as locals with `this` above
them.

**Why nothing caught it.** Every check in the build passed: the smali
assembled, the dex round-tripped through baksmali, `apksigner verify` was
clean, `aapt dump badging` reported exactly the right package, version and
permissions. Register allocation is not something any of those look at, and
the verifier that does look only runs on a device — which this build
environment does not have.

So the build now has one: **`android/lint_registers.py`**, run by both
`android/build.sh` and `playstore/build_aab.sh` before the dex is assembled.
It parses each method's descriptor, works out where the parameter registers
begin (counting `this`, and counting `J`/`D` as two), and fails the build if a
numeric `vN` is written at or above that line — including the second half of a
wide write. Deliberately touching a parameter is spelled `pN` and stays
allowed, so the only thing it flags is the accidental collision. Verified by
re-introducing the exact bug in a copy and watching it fail.

### 2.8 (versionCode 12)

- **The layout could run off the right edge of the screen.** Reported from one
  user's phone: the tab strip clipped mid-word to "ances", the Record button
  and the balance column simply not on screen, the page draggable sideways.
  Two phones showed it, several others did not — the difference is the phone's
  **display size** setting. A larger display size reports a *narrower* CSS
  viewport: 412dp becomes 360, 320, even 280, while every px in the stylesheet
  stays where it was.
  Reproduced by rendering the busiest screen — seven members, the settle-up
  list and the member ledger both open — at each of those widths. At 360px the
  page was 4px too wide, at 320px 44px, at 280px 84px.
  The cause is `min-width: auto`, the default on grid and flex children: one
  row that cannot break sizes the whole track, so a card stayed 348px wide
  inside a 320px screen. Every container holding a row of text is now allowed
  to shrink, the single-column grids use `minmax(0, 1fr)` rather than `1fr`,
  and a `max-width: 430px` tier drops the hard floors (`.flow` 200px,
  `.hero-main` 220px, `.search` 170px) that were fine at 412 and fatal below
  it. Long names wrap instead of pushing.
- Tabs were retuned so all four fit down to a 360px viewport instead of
  becoming a strip you have to drag.
- New suite, `fit.mjs`: eleven combinations of viewport width (412 down to
  280) and system text scale (100% to 175%), each measured on all four tabs,
  asserting the document never becomes wider than the screen. Enlarged system
  text is covered because it enlarges text without shrinking anything else —
  the other half of the same failure.

Note on the test harness, not the app: Chromium loading the page from
`file://` intermittently drops everything localStorage wrote during a page's
life when that page reloads, which shows up as a suite stopping early with the
sign-in screen back. The build from before this change flakes identically, so
it is the harness. `fit.mjs` seeds before the first load and never reloads,
which sidesteps it.

### 2.7 (versionCode 11)

- **A contact with two numbers is now asked about, not guessed at.** The
  picker on its own hands back a single number, and on some phones that is
  whichever one the contacts app treats as primary. Adding "Murali" could
  therefore use a number he does not carry — and because the number is the
  only thing that routes a group to a person, the group would simply never
  reach him, with nothing on either phone to say why.
  `MainActivity.numbersFor()` now reads every number saved against the one
  contact that was chosen and sends them all to the page, which shows a sheet
  to pick from when there is more than one.
- **`READ_CONTACTS` is declared**, requested the moment Contacts is tapped and
  never at launch. Refusing it is not fatal: `numbersFor()` falls back to the
  single number the picker returned, which is exactly the old behaviour. The
  permission is only ever used to read the numbers on the contact the user
  themselves selected; nothing is enumerated and nothing is uploaded.
- The chooser is **not** built on `openModal`, which clears `#modalRoot` and
  would throw away the New-group dialog underneath it. It is its own overlay
  at `z-index: 350`, between the modal and the toast, and it registers with
  the back stack so Android's back button closes it first.
- The same number saved in several spellings (`9876555555`,
  `+91 98765 55555`, `098765 55555`) is recognised as one number and does not
  provoke a pointless question.

Register note for anyone editing the smali: `onActivityResult` is at the
sixteen-register ceiling, and raising `.registers` to 17 puts `p3` in v16,
which `invoke-super` cannot address. The contact id therefore lives in a
field, not a local.

### 2.6 (versionCode 10)

**A phone could be signed out silently and never recover.** It synced happily
for an hour, then stopped, with the server up and nothing changed. The cause
is worth writing down because nothing about it looks like a bug from either
end:

1. The access token lasts an hour, after which the app refreshes it.
2. The app abandons any request after 20 seconds; a sleeping free-tier
   instance takes 30-60 to wake. So a refresh is often *processed* after the
   phone has already given up. The token is spent; the phone never learned
   the replacement and still holds the old one.
3. Next attempt presents that spent token. The server read any reuse as theft
   and revoked **every** session for the number.
4. The phone then had no working token and no route to one. It showed no
   dialog — only "Sign in again" in the sync bar inside the drawer. Groups
   created from then on never left the device.

Fixed at three levels, so no single one has to hold:

- **Server, `rotate_session`.** A refresh token repeated within
  `REFRESH_GRACE_SECONDS` (default 120) is read as a reply the phone never
  heard, and reissued. Beyond that it is still treated as stolen and every
  session is dropped. Sessions ended deliberately — logout, or the theft
  response — now have their refresh hash burned (`_burn_refresh`) so they can
  never come back through that window. A test caught that hole: without the
  burn, signing out and replaying the token inside the window resurrected the
  session.
- **App, single-flight refresh.** Two requests noticing the same expiry no
  longer both spend the token. The second waits on the first.
- **App, `reauth()`.** If the refresh token is unusable for *any* reason —
  including against a server that has not been updated — the app signs in
  again from the number and name already on the phone, rate-limited to once a
  minute so a refusing server cannot become a login loop. With verification
  switched on the server will refuse, and the app then asks the person, which
  is the right outcome.
- Reaching a genuine dead end is now visible: a toast, and the sign-in screen
  on a manual sync, rather than a line in a drawer nobody opens.

No app update is needed for the server-side half — updating the deployment
fixes phones already in the field.

### 2.5 (versionCode 9)

- **The sync server's address is built into the app.** `DEFAULT_SERVER` is
  substituted into the phone build by `build_asset.js` (replacement
  `serverDefault`, overridable with `SL_SERVER`), so a fresh install signs in
  against the real server and starts syncing with nothing to configure. Before
  this, every person had to be told the address and type it into
  Account -> Sync server, which is exactly the sort of step that gets skipped
  and then looks like the app is broken.
  It is a *default*, not a write: nothing is stored under `sl.server` until
  someone saves something there, so pointing the app at a different server
  still works, and emptying the box stores `""` and turns syncing off without
  the built-in address creeping back on the next launch.
- Existing installs that never set an address pick the server up on upgrade.
  Ones where an address was typed in are left alone.
- Fixed in `playstore/build_aab.sh`: bundletool refuses to overwrite its
  output, so a second run failed until the previous `.aab` was removed.

### 2.4 (versionCode 8)

- **The "Goa Trip 2026" demo group is gone.** A new install now opens with an
  empty ledger, so every group anyone sees is one they made or one they were
  added to by number. The sample made sense when the app was offline-only and
  a first launch would otherwise show nothing at all; with sync live it was
  just fake data sitting in a list of real ones, and the first thing a new
  person had to do was work out which entries were theirs.
- **Upgrades clean it up too** — but only when the group is still exactly as
  it shipped. `dropDemoGroup()` compares the expense and settlement ids
  against the seeded set and leaves the group alone if anything was added,
  removed or renamed, on the grounds that somebody adopted it as a real group
  and deleting their records would be worse than leaving clutter. The stale
  `sl.lastGroup` pointer and the `sl.me.goa-sample` mapping go with it.
- Note for anyone reinstalling to "start clean": `android:allowBackup="true"`
  means Android restores the app's stored data from the user's Google backup,
  so an uninstall/reinstall often brings the old groups back. Settings → Apps
  → Split Buddy → Storage → **Clear data** is what actually resets it.

### 2.3 (versionCode 7)

- **The person creating a group is now in it from the start.** A new group
  opens with the signed-in user already listed first — name and number taken
  from the sign-in, so nothing has to be typed. Previously the creator had to
  add themselves by hand, and any group where they forgot left them out of
  every split.
  Their own row carries the **you** tag and no **Remove** button; taking
  yourself out of your own group is what deleting the group is for, and the
  balances would have nowhere to land. The "add at least two members" message
  now reads "add at least one other person" once the creator is seeded.
  `sl.me.<groupId>` is set at creation, so the group opens with the right
  person marked as you rather than resolving it on the next render.
  Groups created before this build are untouched.

### 2.2 (versionCode 6)

- **Fixed: changes could be silently dropped.** On a successful sync the client
  cleared the *entire* dirty queue. Anything marked dirty while that request
  was in flight went with it — never sent, never retried, while the UI said
  "Synced". Found by the §20 scenario test: user A's first expense reached
  neither the server nor user B.
  The queue now removes only the ids that round actually sent, plus ids that
  can never be sent (a record in the local-only sample group), so an
  un-pushable id cannot spin forever either. `syncNow` called while a sync is
  running now reschedules instead of returning silently.

### 2.1 (versionCode 5)

- Mobile-number identity, shared groups, per-device contact names, offline
  queue. See the repo README.

### 2.0 (versionCode 4)

- **`minSdk` 21 -> 23, `targetSdk` 33 -> 34.** The installer was showing
  "This app was built for an older version of Android and doesn't include the
  latest privacy protections" — the wording points at pre-API-23 apps, which
  get install-time rather than runtime permissions. Declaring 23 as the floor
  and 34 as the target settles it from both directions. 34 rather than 35 is
  deliberate: Android 15 enforces edge-to-edge for apps targeting 35, which
  would push the page under the status bar. `setFitsSystemWindows(true)` is
  set on the WebView regardless, as insurance.
  Note `aapt` still stamps `platformBuildVersionCode=23` from the `-I`
  platform jar and there is no way to override it with the API-23 jar; it is
  informational and `PackageManager` does not read it.
- **Passcode lock** (phone build only, `LOCK_ENABLED`). Setup on first launch,
  lock on open and after `LOCK_IDLE_MS` in the background, 5 attempts then a
  30-second cooldown. The passcode is stored as a salted 25,000-round SHA-256.
  SHA-256 is implemented in plain JS: a page loaded from `file://` is not a
  secure context, so `crypto.subtle` is undefined in the WebView. The
  implementation is checked against node's `crypto` on 218 vectors covering
  every block boundary, multi-byte UTF-8 and surrogate pairs.
- **Contact picking.** `MainActivity` gained a single `@JavascriptInterface`
  method, `pickContact()`, which hops to the UI thread (the Activity
  implements `Runnable`, avoiding a second class) and fires `ACTION_PICK` on
  `ContactsContract.CommonDataKinds.Phone.CONTENT_URI`. The result URI is
  readable without `READ_CONTACTS` because the picker grants it temporarily,
  so **the APK still declares no permissions at all**. Name and number are
  percent-encoded with `Uri.encode` before being spliced into a
  `javascript:` call, so quotes and backslashes in a contact name cannot
  break out of the string literal.
- **Fixed: `[hidden]` was not hiding the lock overlay.** `.lock` sets
  `display: grid`, which outbids the UA stylesheet's `[hidden]` rule, and the
  phone build ships its own `<head>` with no reset — so the hidden overlay sat
  invisibly over the page swallowing every tap. An explicit
  `[hidden] { display: none !important; }` is now in the stylesheet.
- Fixed: a passcode mismatch during setup showed no message (`drawLock()`
  cleared the error it had just set), and the attempt cooldown re-enabled its
  own inputs a moment after starting.

### 1.2 (versionCode 3)

- Fixed: **Delete group**, **Delete expense** and **Undo** on a recorded payment
  all did nothing. Each asked for confirmation with `window.confirm()`. A plain
  Android WebView has no `WebChromeClient`, so it does not present JavaScript
  dialogs at all — `confirm()` returns `false` immediately and the action is
  cancelled, with nothing on screen to explain it. (A sandboxed frame without
  `allow-modals` behaves the same way, which is why the hosted web build was
  affected too.)

  Every confirmation is now an in-app dialog built from the app's own modal
  (`confirmModal()`), so no native dialog is involved anywhere. The regression
  suite stubs `window.confirm`/`alert`/`prompt` to record-and-refuse, mimicking
  a bare WebView, and asserts that no native dialog is ever reached.
- Group deletion now removes the group from the local view first, so the UI
  responds immediately, and reports a clear message if the store write fails.

### 1.1 (versionCode 2)

- Fixed: the New group dialog closed on the first tap in any field. It is opened
  from inside the ☰ drawer, so the drawer stays open behind it; the
  "tap outside the drawer to close it" listener ran in the bubble phase and
  counted a tap inside the dialog as outside the drawer. Closing the drawer then
  released its back-button history entry, which the `popstate` handler read as a
  real back press. The listener now runs in the **capture phase** and returns
  early while a dialog is open, and the back stack described above keeps a
  programmatic close from cascading.
- Added: delete a whole group — trash icon on each row of the drawer, and the
  existing button in Group settings. Removes the group, its members, every
  expense and all recorded payments.
- Added: an explicit **Add** button for group members. Android soft keyboards
  present a "next" key rather than Enter, which made the Enter-only handler
  unusable on a phone. A name still in the box is committed when Create group is
  tapped.
- Back button now unwinds one layer at a time: dialog, drawer, exit.

### 1.0 (versionCode 1)

First build.
