#!/bin/sh
# Build split_expense.aab — the Android App Bundle Google Play requires.
#
# This is a SEPARATE output from ../android/build.sh, which still produces the
# sideloadable APK. Neither touches the other: the Play build has its own
# manifest (targetSdk 36, no cleartext traffic) and writes only into
# playstore/build and playstore/dist. The application itself — web/split-ledger.html
# and the smali Activity — is shared, so there is one codebase, two packagings.
#
# Prerequisites (Ubuntu/Debian):
#   sudo apt install openjdk-21-jdk-headless nodejs \
#        android-sdk-build-tools aapt android-sdk-platform-23
#
# Plus two jars that are not in this repository:
#   apktool.jar   — https://github.com/iBotPeaches/Apktool/releases
#                   (only for its smali assembler; see ../docs/BUILD.md)
#   bundletool.jar — https://github.com/google/bundletool/releases
#                   (or `npm pack bundletoolheavy` and take the jar out of it)
#
# And a keystore. For Play this is your UPLOAD key, which is not the key your
# users' installs are signed with — Play re-signs with its own app signing key.
# Losing the upload key is recoverable (Google can reset it); the app signing
# key is Google's problem once you enrol in Play App Signing.
#
# Usage:  ./build_aab.sh
#         BUNDLETOOL=/path/bundletool.jar APKTOOL=/path/apktool.jar \
#           KEYSTORE=/path/upload.jks ./build_aab.sh

set -e
cd "$(dirname "$0")"
ROOT=$(cd .. && pwd)

ANDROID_JAR=${ANDROID_JAR:-/usr/lib/android-sdk/platforms/android-23/android.jar}
APKTOOL=${APKTOOL:-$ROOT/android/apktool.jar}
BUNDLETOOL=${BUNDLETOOL:-./bundletool.jar}
KEYSTORE=${KEYSTORE:-$ROOT/android/split-ledger.jks}
KEY_ALIAS=${KEY_ALIAS:-splitledger}
STORE_PASS=${STORE_PASS:-splitledger}

for f in "$ANDROID_JAR" "$APKTOOL" "$BUNDLETOOL" "$KEYSTORE"; do
  [ -f "$f" ] || { echo "missing: $f  (see the notes at the top of this script)" >&2; exit 1; }
done

rm -rf build
mkdir -p build dist

echo "==> regenerating the page from web/split-ledger.html"
( cd "$ROOT/android" && node build_asset.js )

echo "==> checking smali register use"
python3 "$ROOT/android/lint_registers.py" "$ROOT/android/smali"

echo "==> assembling smali -> classes.dex"
javac -cp "$APKTOOL" -d build "$ROOT/android/Dexer.java"
java -cp "$APKTOOL:build" Dexer "$ROOT/android/smali" build/classes.dex 23

# Play needs resources in protobuf form, which is what separates a bundle from
# an APK. aapt2 does that with --proto-format; aapt (v1) cannot do it at all.
echo "==> compiling resources"
aapt2 compile --dir "$ROOT/android/res" -o build/compiled.zip

echo "==> linking (protobuf format)"
aapt2 link --proto-format -o build/base-proto.apk \
  -I "$ANDROID_JAR" \
  --manifest AndroidManifest.xml \
  -R build/compiled.zip \
  -A "$ROOT/android/assets" \
  --min-sdk-version 23 --target-sdk-version 36 \
  --auto-add-overlay

# A bundle module is a zip in a fixed layout, which is not the layout aapt2
# emits: the manifest moves into manifest/, the dex into dex/, and res/,
# resources.pb and assets/ stay where they are.
echo "==> rearranging into the bundle module layout"
rm -rf build/module && mkdir -p build/module
( cd build/module && unzip -q ../base-proto.apk \
  && mkdir -p manifest dex \
  && mv AndroidManifest.xml manifest/ )
cp build/classes.dex build/module/dex/classes.dex
( cd build/module && zip -qr ../base.zip . )

echo "==> building the bundle"
rm -f dist/split_expense.aab        # bundletool refuses to overwrite
java -jar "$BUNDLETOOL" build-bundle --modules=build/base.zip --output=dist/split_expense.aab

echo "==> signing with the upload key"
jarsigner -keystore "$KEYSTORE" -storepass "$STORE_PASS" -keypass "$STORE_PASS" \
  -sigalg SHA256withRSA -digestalg SHA-256 dist/split_expense.aab "$KEY_ALIAS"

echo "==> verifying"
java -jar "$BUNDLETOOL" validate --bundle=dist/split_expense.aab | head -3
jarsigner -verify dist/split_expense.aab | head -1

# What Play will actually install, so it can be inspected and sideloaded for
# testing without going through the store.
echo "==> generating a universal APK for local testing"
rm -f build/universal.apks
java -jar "$BUNDLETOOL" build-apks --bundle=dist/split_expense.aab \
  --output=build/universal.apks --mode=universal \
  --ks="$KEYSTORE" --ks-key-alias="$KEY_ALIAS" \
  --ks-pass="pass:$STORE_PASS" --key-pass="pass:$STORE_PASS"
( cd build && unzip -qo universal.apks -d uni )
aapt dump badging build/uni/universal.apk | head -3

echo
echo "built: playstore/dist/split_expense.aab          <- upload this to Play"
echo "       playstore/build/uni/universal.apk         <- for testing on a device"
