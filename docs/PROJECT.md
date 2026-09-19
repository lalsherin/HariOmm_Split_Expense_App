# Split Buddy — project handbook

**Read this before changing anything.** It is the one place that records what
this project is, what the pieces are called, how they are joined together, and
which decisions are already settled and why. Everything else in `docs/` goes
deeper on one topic; this is the map.

Last updated for **3.5 (versionCode 19)**, 19 September 2026.

---

## 1. What it is

An Android app for splitting shared expenses — trips, flatmates, a group
dinner — for Sherin and his friends. Every phone keeps its own copy of
everything and works with no signal; a small server in the middle lets the
phones find each other and catch up.

There is no Gradle, no Android Studio and no dex compiler anywhere in this
project. The whole app is **one HTML file** shown in a WebView by a
hand-written Activity in smali. That sounds mad and is deliberate: it builds
anywhere with a JDK, Node and the Android build-tools, in about ten seconds.

---

## 2. Names — and why they must not change

| Thing | Name | Changing it costs |
|---|---|---|
| App, as people see it | **Split Buddy** | nothing — it is just `res/values/strings.xml` |
| Package id | **`com.sherinlal.splitledger`** | **Everything.** Android identifies an app by its package. A new id installs *alongside* the old app instead of updating it, and every group that never synced is stranded in the old one. It still says "splitledger" because it was named Split Ledger until 3.0. Leave it. |
| Source zip | **`HariOmm_Split_Expense_App.zip`** | extracts to `HariOmm_Split_Expense_App\`, which is the folder with the `.git` in it. A different name means a fresh `git init`, a second copy on disk, and `push_to_github.cmd`'s own instructions no longer match. (This was renamed by accident once. Don't.) |
| Sideload build | **`split_expense.apk`** | nothing, but it is what the install instructions name |
| Play build | **`split_expense.aab`** | nothing |
| GitHub repo | **https://github.com/lalsherin/HariOmm_Split_Expense_App** | the push scripts point at it |
| Live server | **https://split-ledger-71my.onrender.com** | it is **built into the app** (`DEFAULT_SERVER`). Change the Render service name and every installed phone loses sync until it is rebuilt. |
| Backup file marker | `"app": "split-ledger"` | every backup ever taken stops restoring |
| Signing key | `split-ledger.jks`, alias `splitledger` | an APK signed with a different key **cannot install over** an existing one. Android treats it as a different app. |
| Working folder on the PC | `C:\Sherin_Lal_GM\Split_Expense` | nothing — it is where finished files are delivered |

---

## 3. How the pieces are joined

```
   C:\Sherin_Lal_GM\Split_Expense\          <- finished files land here
        HariOmm_Split_Expense_App.zip       <- the whole project, zipped
        split_expense.apk                   <- install this / send to friends
        split_expense.aab                   <- upload this to Google Play
              |
              |  extract, then push_to_github.cmd
              v
   github.com/lalsherin/HariOmm_Split_Expense_App
              |
              |  Render watches the repo and rebuilds
              v
   split-ledger.onrender.com  (Render web service, Singapore, Docker)
              |
              |  DATABASE_URL
              v
   Neon Postgres  (project still-voice-88708648, Singapore, free plan)

   Phone A  ─┐
             ├─►  the Render address, which is baked into the APK
   Phone B  ─┘
```

Two separate accounts on purpose: **Neon** for the database, **Render** for the
API. Render's own free Postgres is deleted 30 days after it is created, which
is a bad thing to discover with real data in it. Neon's free database has no
expiry.

Both in **Singapore** — the closest region to India on either platform, and the
app↔database hop happens on every request.

---

## 4. How two phones find each other

This is the part that confuses, so it is worth being exact.

**The mobile number is the only link.** There are no invite codes, no QR codes,
no usernames.

1. You create a group and add someone by their mobile number.
2. The number is normalised to E.164 — `98765 43210`, `+91 98765 43210` and
   `09876543210` all become `+919876543210`. A different number, **even by one
   digit, is a different person.**
3. That member row goes to the server. If somebody already has an account with
   that exact number, the row is linked to them immediately and the group
   appears on their phone. If nobody does, the row sits there as a
   **placeholder**, waiting.
4. When that person installs the app and signs in with that number, every
   placeholder row holding it is claimed at once, and every group they were
   added to arrives.

**So the number-one reason "my friend hasn't got the group" is that nobody has
ever signed in with the number you typed.** Your phone shows *Synced*, because
from its point of view everything worked perfectly — it sent the group, the
server took it. Nothing is wrong except that the number belongs to nobody.

**How to check, in ten seconds:** Account → **Connection check**. It lists
every member of the current group and says, for each, whether anyone has
actually signed in with that number. It also says whether the server is
answering and which build it is running. The screen is safe to screenshot —
no tokens or passwords appear on it.

Other things the app relies on:

- **`seq`, not clocks.** Every write anywhere gets a server-assigned number.
  Phones ask for "everything after my last number". Two phones with wrong
  clocks cannot miss each other's changes.
- **Tombstones.** Nothing is ever hard-deleted, because a phone that has been
  offline for a week has to learn that something went away.
- **Last writer wins** on a row's `updated_at`, per row, not per group.
- **Names are per-phone.** Everyone sees their own contact name for each
  person. The name the group's creator typed is only a fallback.

---

## 5. What is in the repo

```
android/          the phone build
  AndroidManifest.xml     <- versionCode + versionName live here; everything else follows
  build.sh                <- builds dist/split_expense.apk
  build_asset.js          <- turns web/split-ledger.html into the APK's page
  smali/…/MainActivity.smali   <- the hand-written Activity (WebView + contact picker)
  Dexer.java              <- calls apktool's smali assembler
  lint_registers.py       <- build guard (see below)
  check_version.py        <- build guard (see below)
  res/                    <- icons, app name, theme
playstore/        the Google Play build — same code, its own manifest
  build_aab.sh            <- builds playstore/dist/split_expense.aab
  AndroidManifest.xml     <- targetSdk 36, no cleartext traffic
backend/          the sync server (FastAPI + SQLAlchemy + Postgres)
  app/sync/service.py     <- push/pull, the rules about who may change what
  app/sync/router.py      <- the /sync endpoint, including long polling
  app/auth/service.py     <- sign-in, refresh-token rotation
  tests/                  <- 78 tests, runnable on SQLite or real Postgres
web/split-ledger.html     <- THE APP. ~3,700 lines. Everything the user sees.
docs/             BUILD.md (changelog + how it is built), DEPLOY.md, INSTALL.txt, this file
render.yaml       the Render service, described so there is no form to mistype
push_to_github.cmd / .sh  helper scripts, deliberately NOT committed
```

**`web/split-ledger.html` is the app.** One file: markup, styles and logic. To
change what the app does, change that file. `build_asset.js` then rewrites 13
specific passages for the phone build (turns sync and the passcode lock on,
bakes in the server address, removes the demo group, and so on). Each of those
13 replacements must match **exactly once** or the build stops — so if you edit
a line the asset builder is looking for, you find out immediately rather than
shipping a half-built app.

---

## 5b. Who has signed up — the user registry

One row per person in `users`, keyed by their mobile number in E.164. The same
number written three ways collapses to one account, which is what stops
somebody ending up with two accounts and none of their groups.

| column | what it is |
|---|---|
| `id` | uuid4 string, stable for the life of the account |
| `mobile_number` | E.164, **unique and indexed** — this is the identity |
| `name` | display name, as they typed it at sign-in |
| `created_at` | when they first signed in |
| `last_login_at` | server UTC, written on every successful sign-in |
| `last_seen_at` | last authenticated request, written at most once per 15 min |
| `app_version` | the build their phone last used, from `X-App-Version` |
| `account_status` | `active`. This is the is-active flag; nothing sets it to anything else automatically |
| `mobile_verified` | true only once OTP verification is switched on |

Every sign-in — successful or not — is also recorded in `login_history`
(time, platform, device string, IP, and the outcome). That table is what
answers "did they even reach the server?".

**To see who has registered**, open the Neon SQL editor and run:

```sql
select name, mobile_number, app_version,
       created_at, last_login_at, last_seen_at, account_status
from users
order by last_seen_at desc nulls last;
```

There is deliberately **no API endpoint that lists users.** `/users/me`
returns one account's own row and nothing else; there is nothing anywhere that
returns somebody else's. An endpoint that listed everyone would be an endpoint
that hands out a list of mobile numbers, and it would exist on a server with
`REQUIRE_OTP=false`, where anybody can sign in as any number. Neon's own
console is already an authenticated admin view; it does not need a second one.

To deactivate an account, set `account_status` to anything but `active` — the
auth dependency then refuses every request from it with 403. Nothing does this
automatically; being dormant is not a reason to be locked out.

## 6. Versions

Current: **3.3 / versionCode 17.**

`versionCode` must go **up** every release or Play refuses the upload and
Android refuses the update.

| | What it was about |
|---|---|
| 3.3 | Connection check; fixed Save falsely reporting "Couldn't reach that server" |
| 3.2 | Only the group's creator can delete it for everyone |
| 3.1 | Instant updates — a group reaches the other phone in about a second |
| 3.0 | Renamed to Split Buddy |
| 2.9 | **Fixed the crash in 2.7 and 2.8** — those two do not start at all |
| 2.8 | Layout fixed for narrow screens and large text |
| 2.7 | A contact with two numbers is asked about, not guessed |
| 2.6 | Fixed a silent sign-out that never recovered |
| 2.5 | The server address built into the app |
| 2.4 | Demo group removed |
| 2.3 | Whoever creates a group is in it from the start |
| 2.2 | Fixed changes being silently dropped on sync |
| 2.1 | Mobile-number identity, shared groups, offline working |
| 2.0 | minSdk 23, targetSdk 34 |
| 1.0–1.2 | First builds, local only |

---

## 7. Changing something — the routine

1. Edit **`web/split-ledger.html`** (or `backend/app/…` for server behaviour).
2. Bump `versionCode` **and** `versionName` in **both**
   `android/AndroidManifest.xml` and `playstore/AndroidManifest.xml`.
3. Update `APP_VERSION` in `web/split-ledger.html` and `SERVER_BUILD` in
   `backend/app/main.py` to the same `versionName`. *(The build fails if these
   three disagree — that is `check_version.py` doing its job.)*
4. Add an entry at the top of the changelog in `docs/BUILD.md`.
5. Build: `android/build.sh`, and `playstore/build_aab.sh` if Play needs it.
6. Extract the zip over `HariOmm_Split_Expense_App\`, run `push_to_github.cmd`.
7. **If the server changed, redeploy Render.** Code on GitHub is not code that
   is running. Account → Connection check tells you which build Render is
   actually serving.
8. Install the APK on the phones.

---

## 8. Building

Needs: `openjdk-21-jdk-headless`, `nodejs`, `android-sdk-build-tools`, `aapt`,
`apksigner`, `zipalign`, `android-sdk-platform-23`, plus two jars that are
**not** in the repo — `apktool.jar` (only for the smali assembler inside it)
and `bundletool.jar` (Play bundle only) — and the signing keystore.

```
cd android    && ./build.sh        ->  dist/split_expense.apk
cd playstore  && ./build_aab.sh    ->  playstore/dist/split_expense.aab
```

Two guards run first, both added after a bug got through:

- **`lint_registers.py`** — the smali Activity allocates registers by hand.
  Write to a register number that the frame has given to a parameter and the
  app dies at launch with `VerifyError`, with no other warning. That is exactly
  what shipped as 2.7 and 2.8. The linter now refuses to build it.
- **`check_version.py`** — the manifest, `APP_VERSION` and `SERVER_BUILD` must
  agree. A version marker that has quietly gone stale is worse than none,
  because the whole point is to be believed weeks later by someone debugging.

---

## 9. Deploying the server

Full walkthrough in **`docs/DEPLOY.md`**. The short version:

- **Render** reads `render.yaml` from the repo root. Leave the Blueprint Path
  field **empty** — a full GitHub URL in there is the "file not found" error.
- `dockerfilePath` is resolved **relative to** `rootDir`. With `rootDir: backend`
  it is `./Dockerfile`. Writing `./backend/Dockerfile` makes Render look for
  `backend/backend/Dockerfile` and the deploy dies at the clone step.
- **`DATABASE_URL`** is the one thing Render asks for. Use Neon's **direct**
  connection string, not the pooled one (`-pooler` in the host) — pgbouncer in
  transaction mode breaks asyncpg's prepared statements. Paste it exactly as
  Neon prints it; the server rewrites the scheme and TLS parameters itself.
- Tables are created on first startup. **There are no migrations** — a future
  schema change needs Alembic or a manual `DROP`.
- **Free Render sleeps after 15 minutes idle** and takes 30–60s to wake, while
  the app gives up at 20s. So the first sync after a quiet spell looks like
  "No connection" and the next one works. **Starter at $7/month never sleeps.**
  If anyone other than you uses this, pay the $7 — it is the difference between
  "our expense app" and "that app that never works".

---

## 10. Secrets

In `.gitignore` and never committed: `*.jks`, `*.keystore`, `*.p12`, `.env`,
`*.db`, `key.properties`.

**The signing keystore password is deliberately not written down in this file**,
because this file goes to GitHub. Keep it in a password manager. Losing it
means you can never update the sideloaded app again — every phone would have to
uninstall and reinstall, losing anything that had not synced. (For Play it is
recoverable: that is only the *upload* key, and Google can reset it.)

Also: don't paste the Neon connection string into a chat or an issue. It
contains the database password. If it ever leaks, Neon has a **Reset password**
button.

---

## 11. Decisions already made, and why

Re-opening these is fine — but know what was weighed.

**Deleting a group.** The creator deletes it for everyone. Anyone else only
clears it off their own phone: they stay in the group, their share of every
expense still counts in everyone else's balances, and nobody is told. The
alternative — removing their member row — silently rewrites what other people
owe, which is too much damage for one person tidying their own screen. Admin
is whoever created it, permanently; no promoting, no transferring. **Enforced
on the server, not just hidden in the app**, because an older build sends a
real delete and would otherwise wipe out everyone's records.

**Hidden groups** (`sl.hidden`) are local to one phone and never sent. They
keep syncing in the background, so restoring one brings it back current. A
hidden group stays hidden even if new expenses arrive in it — a thing you
deleted should not resurrect itself. Undo on the toast, or Account → *Removed
from this phone*.

**Instant updates are long polling, not push.** The phone asks the server to
hold a request open for up to 15 seconds; the server watches one counter and
answers the moment anything appears. A group arrives in about a second. **It
only works while the other person has the app open on screen.** Real push
needs Firebase, a Google Cloud project and a Gradle build — none of which this
project has, and adding them means giving up the no-Gradle build.

**No OTP.** `REQUIRE_OTP=false` means anyone who types a mobile number becomes
that person. For you and your friends that is a fair trade. The moment a
stranger can reach the URL it is not. Turning it on needs an SMS provider and,
for Indian numbers, DLT registration — a regulatory step, not a code change.

**The creator is in the group from the start**, listed first, and cannot remove
themselves — that is what deleting the group is for, and the balances would
have nowhere to land.

---

## 12. When something is wrong

In this order:

1. **Account → Connection check**, on the phone that has the problem. It
   answers most of this list by itself.
2. Is the server answering? On free Render, wait a minute and try again — it
   may be waking up.
3. Which build is the server running? If it is older than the app, **redeploy
   Render**. Code pushed to GitHub is not code that is running.
4. Has the other person signed in with **exactly** the number you added? This
   is the usual answer.
5. Is the other phone's app actually open? Instant updates only work on screen.
6. Does the status dot say *This phone only*? Then Account has no server
   address on that phone.

---

## 13. Known open items

Not bugs that bite at this size, but they are real:

- The rate limiter has a get-then-INSERT race: two simultaneous requests
  creating the same counter return **500** instead of 429.
- An idle sync costs 12 queries and a write; four small changes take it to
  about three and none.
- **No Alembic.** Missing tables are created at startup, and missing *columns*
  are added by a narrow additive step in `database.py` (`_ensure_columns`) that
  can only add a nullable column with no default. Anything else — renaming,
  dropping, changing a type, backfilling — still needs a considered migration,
  and Alembic is the right answer the first time one is needed.
- `allowBackup="true"` — Android may restore stale data onto a new install.
- No leave-group, block, report, or in-app account deletion. Google Play
  requires account deletion before a public listing.
- `REQUIRE_OTP=false` (see above).
- The Android contacts query has still never run on real hardware in a
  two-number case.

---

## 14. Tests

- **Backend:** `cd backend && python3 -m pytest` — 58 tests.
- **The app:** Playwright scripts drive two "phones" against a real server —
  group delivery, delete permissions, sign-out recovery, the connection check,
  layout down to a 280px screen at 175% text, and the latency of an update
  reaching the other phone.

Every one of them exists because something broke once. When you change
behaviour, add the test that would have caught it.
