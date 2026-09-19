#!/usr/bin/env python3
"""Fail the build if the app's own version string has drifted.

The page shows APP_VERSION in the connection check, right beside the version
the server reports, so that someone on a phone can tell whether the deploy
they just did actually took. That comparison is worthless if APP_VERSION is
stale, and nothing else would ever notice — the number is only ever read by a
human, weeks later, while trying to work out why sync is broken.

Checks, against android/AndroidManifest.xml:
  web/split-ledger.html   const APP_VERSION = "x.y"
  backend/app/main.py     SERVER_BUILD = "x.y"
"""
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent


def find(path, pattern, label):
    text = (ROOT / path).read_text(encoding="utf-8")
    m = re.search(pattern, text)
    if not m:
        sys.exit("version check: could not find %s in %s" % (label, path))
    return m.group(1)


want = find("android/AndroidManifest.xml", r'android:versionName="([^"]+)"', "versionName")
found = {
    "web/split-ledger.html (APP_VERSION)":
        find("web/split-ledger.html", r'const APP_VERSION = "([^"]+)"', "APP_VERSION"),
    "backend/app/main.py (SERVER_BUILD)":
        find("backend/app/main.py", r'SERVER_BUILD = "([^"]+)"', "SERVER_BUILD"),
}

bad = {k: v for k, v in found.items() if v != want}
if bad:
    print("version check FAILED - the manifest says %s, but:" % want, file=sys.stderr)
    for k, v in bad.items():
        print("    %-40s says %s" % (k, v), file=sys.stderr)
    sys.exit(1)

print("version check ok (%s everywhere)" % want)
