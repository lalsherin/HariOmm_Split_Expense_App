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
  → Split Ledger → Storage → **Clear data** is what actually resets it.

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
