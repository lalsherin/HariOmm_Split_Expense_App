#!/bin/sh
# Build split_expense.apk from source.
#
# Prerequisites (Ubuntu/Debian):
#   sudo apt install openjdk-21-jdk-headless nodejs \
#        android-sdk-build-tools aapt apksigner zipalign android-sdk-platform-23
#
# Plus an apktool jar, for the smali assembler bundled inside it:
#   https://github.com/iBotPeaches/Apktool/releases  ->  apktool.jar
#
# And a signing keystore. The one used for the released APK is deliberately
# NOT in this repository. Generate your own with:
#   keytool -genkeypair -keystore split-ledger.jks -alias splitledger \
#           -keyalg RSA -keysize 2048 -sigalg SHA256withRSA -validity 10950 \
#           -dname "CN=Your Name, C=IN"
# Note: an APK signed with a different key cannot install over one signed with
# the original — Android treats it as a different app.
#
# Usage:  ./build.sh            (expects ./apktool.jar and ./split-ledger.jks)
#         APKTOOL=/path/apktool.jar KEYSTORE=/path/my.jks ./build.sh

set -e
cd "$(dirname "$0")"

ANDROID_JAR=${ANDROID_JAR:-/usr/lib/android-sdk/platforms/android-23/android.jar}
APKTOOL=${APKTOOL:-./apktool.jar}
KEYSTORE=${KEYSTORE:-./split-ledger.jks}
KEY_ALIAS=${KEY_ALIAS:-splitledger}
STORE_PASS=${STORE_PASS:-splitledger}

for f in "$ANDROID_JAR" "$APKTOOL" "$KEYSTORE"; do
  [ -f "$f" ] || { echo "missing: $f  (see the notes at the top of this script)" >&2; exit 1; }
done

mkdir -p build

echo "==> regenerating assets/index.html from ../web/split-ledger.html"
node build_asset.js

echo "==> checking version strings agree"
python3 ./check_version.py

echo "==> checking smali register use"
python3 ./lint_registers.py ./smali

echo "==> assembling smali -> classes.dex"
javac -cp "$APKTOOL" -d build Dexer.java
java -cp "$APKTOOL:build" Dexer smali build/classes.dex 23

echo "==> packaging resources and assets"
aapt package -f -M AndroidManifest.xml -S res -A assets -I "$ANDROID_JAR" -F build/app.apk
( cd build && aapt add app.apk classes.dex >/dev/null )

echo "==> aligning and signing"
zipalign -f -p 4 build/app.apk build/app.aligned.apk
apksigner sign --ks "$KEYSTORE" --ks-key-alias "$KEY_ALIAS" \
  --ks-pass "pass:$STORE_PASS" --key-pass "pass:$STORE_PASS" \
  --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true \
  --min-sdk-version 21 --out ../dist/split_expense.apk build/app.aligned.apk

echo "==> verifying"
apksigner verify -v --min-sdk-version 21 ../dist/split_expense.apk
zipalign -c 4 ../dist/split_expense.apk && echo "alignment OK"
aapt dump badging ../dist/split_expense.apk | head -3
echo
echo "built: dist/split_expense.apk"
