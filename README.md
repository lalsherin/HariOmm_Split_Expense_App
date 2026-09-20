# HariOmm Split Expense

A shared-expense ledger for groups — trips, flatmates, dinner clubs. Track who
paid for what, split it five different ways, and settle up in the fewest
possible payments.

**Start with [`docs/PROJECT.md`](docs/PROJECT.md)** — the project handbook: what
everything is called and why those names must not change, how the pieces are
joined, how two phones find each other, the release routine, and which
decisions are already settled.

Three parts:

- **Web** — `web/split-ledger.html`, a single self-contained page.
- **Android** — `dist/split_expense.apk`, a 62 KB app with a passcode lock,
  contact picking, and cross-phone sync. Works fully offline; syncs when it
  can reach your server.
- **Server** — `backend/`, mobile-number identity and cross-device sync, so a
  group created on one phone appears on everyone else's. Deployed on Render
  with a Neon database — see [`docs/DEPLOY.md`](docs/DEPLOY.md), and
  [`docs/QUERIES.sql`](docs/QUERIES.sql) for looking inside it.

---

## Features

**Groups** — a trip, a flat, a recurring dinner. Named members, and a currency
per group (INR by default; USD, EUR, GBP, AED, SGD, AUD and JPY too).

**Expenses** — description, amount, date, category, and a payer. One person can
front the bill, or several can split the paying.

**Five ways to split**

| Split | What it does |
|---|---|
| Equally | Everyone selected owes the same share |
| Exact amounts | Type what each person owes; must total the bill |
| Percentages | Each share as a percentage; must total 100% |
| Shares | Weights — 2 shares owe twice what 1 share owes |
| Adjustments | Charge someone for their own item, split the rest equally |

The editor reconciles live: *"₹240.00 of ₹1,200.00 — ₹960.00 left"*. An
unbalanced split cannot be saved.

**Balances and settle-up** — your net position per group, and a toggle between
*exact debts* (who literally owes whom) and the *simplified* set, which pays
everyone off in the fewest transfers. Record a payment in cash, UPI, bank
transfer, card or wallet and the balances update.

**Insights** — where the money goes by category, who fronts the bills, spending
by month, and a diverging chart of who is up and who is down. Every chart has a
"view as table" fallback.

**Activity** — a running feed of every expense and payment.

**Passcode lock** (phone build) — a four-digit code asked for on open and after
two minutes in the background, with an attempt cooldown. Stored as a salted,
25,000-round SHA-256, computed in plain JS because a `file://` WebView page is
not a secure context and has no `crypto.subtle`. It keeps someone who picks up
your phone out of the app; it is not encryption, and the phone's own screen
lock is what protects the data at rest.

**Contact picking** (phone build) — members can be added straight from the
phone's address book. The app never reads contacts and holds **no contacts
permission**: it fires `ACTION_PICK`, Android's own picker runs outside the
app, and only the one person tapped comes back through the temporary URI grant
in the result intent.

---

## The money engine

All arithmetic runs in **minor units** (paise/cents) as integers, so nothing is
ever lost or invented by floating point.

- `distribute(total, weights)` — largest-remainder allocation. ₹100 across three
  people is 33.34 / 33.33 / 33.33, and the parts always re-sum to the total.
- `computeSplits()` — one function covering all five split types.
- `netBalances()` — `paid − owed`, adjusted by recorded settlements. Always sums
  to exactly zero across the group.
- `pairwiseDebts()` — exact who-owes-whom. With several payers on one expense, a
  debtor's share is allocated to each payer in proportion to what they actually
  put in.
- `simplifyDebts()` — greedy debtor/creditor matching, settling everyone in at
  most *n − 1* transfers.

These are covered by a Node suite of fixed cases plus 400 randomized trials
(3–7 members, mixed split types). Every trial asserts that splits sum exactly to
the expense, that net balances sum to zero, that pairwise debts reconcile to the
same net positions, and that applying the simplified transfers leaves every
member at exactly zero.

---

## Installing the Android app

Download `dist/split_expense.apk` onto the phone and open it.

Android will block it as an unknown source — tap **Settings** in that message,
allow the app you are installing from, then **Install**. Play Protect may also
warn; choose **Install anyway**. It flags anything it has not seen before.

Full walkthrough in [`docs/INSTALL.txt`](docs/INSTALL.txt).

**Your data lives on the phone.** The app has no account and no network access,
so nothing syncs — not with the web build, not between phones. Uninstalling
deletes it. The **Backup** screen (☰ drawer → download icon) exports everything
as text you can paste back on another device.

---

## Running the web build

Open `web/split-ledger.html` in a browser. It is one file with no build step and
no dependencies; data is kept in `localStorage`.

The version hosted as a Claude Artifact additionally uses that platform's
document store, so several people see the same groups live. That is the only
difference — `build_asset.js` strips the branch when generating the Android
asset, and fails the build if any reference to it survives.

---

## Building the APK yourself

```sh
cd android
./build.sh
```

Prerequisites, the keystore situation and the environment variables are all
documented at the top of [`android/build.sh`](android/build.sh).

### Why the build looks unusual

There is no Gradle and no Android Gradle Plugin here. The app was built in an
environment with no access to Google's servers, so the toolchain came from the
Ubuntu archive instead:

```sh
sudo apt install android-sdk-build-tools aapt apksigner zipalign android-sdk-platform-23
```

That provides `aapt`, `apksigner`, `zipalign` and an API-23 `android.jar` — but
**no dex compiler**. Ubuntu ships none (the `dx` package in apt is OpenDX, an
unrelated visualisation tool). So the Activity is written directly in **smali**
([`android/smali/…/MainActivity.smali`](android/smali/com/sherinlal/splitledger/MainActivity.smali),
about 60 lines, one class) and assembled to `classes.dex` using the smali
assembler bundled inside `apktool.jar`, driven by the six-line `Dexer.java`.

The upshot is a very small, very auditable APK: the dex references only
`android/*`, `java/*` and the app's own class. No third-party code ships inside
it.

Build order: `smali → classes.dex`, `aapt package` (manifest + res + assets),
`aapt add classes.dex`, `zipalign -p 4`, `apksigner sign`.

More detail in [`docs/BUILD.md`](docs/BUILD.md).

---

## App details

```
package        com.sherinlal.splitledger
label          Split Buddy
version        3.0 (versionCode 14)
minSdk         23  (Android 6.0 Marshmallow)
targetSdk      34
permissions    INTERNET, ACCESS_NETWORK_STATE
signatures     v1 + v2 + v3
```

---

## Repository layout

```
backend/                     FastAPI + Postgres: identity and sync (see its README)
playstore/                   the Google Play bundle (.aab) build — see its README
web/split-ledger.html        the application — source of truth for both builds
android/
  AndroidManifest.xml
  smali/…/MainActivity.smali one Activity: a WebView over the bundled page
  assets/index.html          generated from web/ by build_asset.js
  res/                       launcher icons (generated by make_icons.py)
  build_asset.js             web page -> offline phone asset
  make_icons.py              draws the launcher icons, stdlib only
  Dexer.java                 smali -> classes.dex driver
  build.sh                   the whole build
dist/split_expense.apk       the signed release
docs/INSTALL.txt             install and backup instructions
docs/BUILD.md                toolchain notes and verification record
```

## Not in this repository

The **signing keystore** is deliberately absent, and `.gitignore` keeps
`*.jks` / `*.keystore` out. Anyone holding it could publish an app that Android
accepts as an update to this one.

If you build with your own key, your APK will not install over an existing
install of the released one — Android requires the same signature. Uninstall
first, exporting from the Backup screen if there is data worth keeping.
