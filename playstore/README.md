# Google Play build

`dist/split_expense.aab` — the Android App Bundle Play requires. Built by
`build_aab.sh` from the same application source as the sideloadable APK.

**This folder does not affect the running app.** `../android/` still builds
`dist/split_expense.apk`, still targets SDK 34, still gets shared as a direct
download. The two builds share `web/split-ledger.html` and the smali Activity
and differ only in the manifest and the packaging.

## What is different in the Play build

| | sideload APK | Play AAB |
|---|---|---|
| format | `.apk` | `.aab` |
| targetSdk | 34 | **36** — required by Play since 31 Aug 2026 |
| `usesCleartextTraffic` | true | **removed** — https only |
| signed by | your key, final | your *upload* key; Play re-signs |

## Play does not host your backend

Worth stating plainly because it is a common and expensive misunderstanding:
Google Play distributes the app file. It runs no servers for you. An install
from Play syncs through the same Render + Neon backend as every other install
(`docs/DEPLOY.md`). If that server is down, the Play build stops syncing too.

## Signing, and the one-way door

Enrol in **Play App Signing**. You upload a bundle signed with an *upload key*;
Google re-signs it with the app signing key it holds. Consequences:

- Losing the upload key is recoverable — Google can reset it.
- **The Play build and the sideload build have different signatures.** Android
  treats them as unrelated apps: nobody can update from one to the other, and
  installing one over the other fails. Anyone moving from the direct download
  to the Play version must uninstall first, which wipes the local copy of
  anything that never synced.

## Before this can actually be uploaded

The bundle is valid and signed. These are not build problems, they are account
and policy work:

1. **Play Console account** — $25, one-time.
2. **Twelve testers, fourteen days.** A new *personal* developer account must
   run a closed test with 12 testers continuously opted in for 14 days before
   it may apply for production access. Organisation accounts are exempt.
3. **Privacy policy URL**, publicly reachable.
4. **Data safety form** — declare the phone number: collected, shared with
   other members of a group, and how it is deleted. Since 2.7 also declare
   **Contacts**: accessed to list the numbers on the one contact the user
   picks, not collected and not shared — the chosen number is stored as group
   membership, the contact name never leaves the device.
5. **In-app account deletion**, plus a web URL that does the same. Play
   requires both for any app with accounts. **Not built yet.**
6. **No phone verification.** The server runs `REQUIRE_OTP=false`, so anyone
   who types a mobile number becomes that person. This is defensible among
   people who know each other and indefensible on a public store listing. Turn
   OTP on before the listing goes live — which for Indian numbers means an SMS
   provider plus DLT registration.
7. **No leave / block / report.** Anyone who knows your number can add it to a
   group and it appears in your app, with no way out. Reviewers read that as a
   harassment surface in a social-shaped app.

## Not verified

The bundle has never run on a device or an emulator — no emulator was reachable
from the build environment. What *has* been checked: `bundletool validate`
passes; the signature verifies; the universal APK generated from the bundle
reports the right package, version, `minSdk` 23 and `targetSdk` 36, and only
the two permissions; the page extracted from that APK is byte-identical to the
source build and passes the full regression and demo-cleanup suites in a
412×915 browser.

**The specific risk of targetSdk 36 is layout.** Android 15 began enforcing
edge-to-edge for apps targeting 35+, and 16 removes the opt-out, so the page
can end up drawn under the status bar. `setFitsSystemWindows(true)` is set on
the WebView, which should handle it — but "should" is doing real work in that
sentence. Sideload `build/uni/universal.apk` and look at it on a real phone
before uploading anything.

## Build

```sh
BUNDLETOOL=/path/bundletool.jar APKTOOL=/path/apktool.jar \
  KEYSTORE=/path/upload.jks ./build_aab.sh
```

Neither jar is in this repository. bundletool comes from
https://github.com/google/bundletool/releases; apktool, used only for its smali
assembler, from https://github.com/iBotPeaches/Apktool/releases. See
`../docs/BUILD.md` for why the build is put together this way.

Outputs:

- `dist/split_expense.aab` — upload this
- `build/uni/universal.apk` — install this on a phone to test what Play will serve
