#!/bin/sh
# Optional build guard: check the assembled classes.dex the way a phone would,
# before it is ever installed.
#
#   1. dex2jar turns it back into JVM classes, which are loaded with the JVM's
#      own type-inferring verifier against android.jar. A register holding the
#      wrong kind of value -- what shipped as 2.7 and 2.8 and killed the app at
#      launch with VerifyError -- fails here instead.
#   2. Every Android method and field the smali calls must exist in API 23
#      (minSdk). A misspelt or too-new API would otherwise only show up as
#      NoSuchMethodError on someone's phone.
#
# Needs dex2jar (https://github.com/pxb1988/dex2jar, v2.4): set DEX2JAR to its
# folder. build.sh runs this when DEX2JAR is set and skips it otherwise.
#
#   DEX2JAR=/path/dex-tools-v2.4 ./verify_dex.sh build/classes.dex
set -e
cd "$(dirname "$0")"
DEX=${1:-build/classes.dex}
ANDROID_JAR=${ANDROID_JAR:-/usr/lib/android-sdk/platforms/android-23/android.jar}
: "${DEX2JAR:?set DEX2JAR to the dex2jar folder}"
T=$(mktemp -d)
javac -d "$T" verify/VerifyLoad.java verify/RefCheck.java
sh "$DEX2JAR/d2j-dex2jar.sh" -f -o "$T/app.jar" "$DEX" >/dev/null 2>&1
# class version 49: no stack maps, so the JVM infers every type itself
sh "$DEX2JAR/d2j-class-version-switch.sh" 5 "$T/app.jar" "$T/app49.jar" >/dev/null 2>&1
java -Xverify:all -cp "$T" VerifyLoad "$T/app49.jar" "$ANDROID_JAR"
javap -c -p -cp "$T/app.jar" $(unzip -Z1 "$T/app.jar" | grep '\.class$' | sed 's/\.class$//; s#/#.#g') \
  | grep -oE '// (Method|InterfaceMethod|Field) [^ ]+' \
  | sed -E 's#// (InterfaceMethod|Method) #Method #; s#// Field #Field #' \
  | sed -E 's#^(Method|Field) ([^.]+)\.("?[^:"]+"?):(.*)$#\1 \2 \3 \4#; s#"##g' | sort -u \
  | java -cp "$T" RefCheck "$ANDROID_JAR"
rm -rf "$T"
