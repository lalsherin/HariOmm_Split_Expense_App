#!/bin/sh
# Two-phone end-to-end checks against a real (local, SQLite) server.
#
#   pip install -r ../backend/requirements-dev.txt playwright && playwright install chromium
#   ./run.sh                     # everything                         (~15 minutes)
#   ./run.sh late                # late-install checks only            (~4 minutes)
#   ./run.sh contacts            # multi-select contact picker          (~2 minutes)
#   ./run.sh nav                 # bottom navigation bar                (~2 minutes)
#   ./run.sh invites             # share group / invite links           (~2 minutes)
#   ./run.sh addexp              # Home's Add expense asks for the group (~1 minute)
#   ./run.sh cards               # share expense / balance as an image  (~2 minutes)
#   ./run.sh refused 35 removed_then_hides,stuck_37_phone_upgrades
#
# Builds the phone page from web/split-ledger.html first, so it tests what the
# APK would carry.
set -e
cd "$(dirname "$0")"
node ../android/build_asset.js
python3 make_page.py

export E2E_DB=$(mktemp -u /tmp/split-e2e-XXXXXX.db)
./api.sh start
( cd www && exec python3 -m http.server 8080 >/dev/null 2>&1 ) &
WEB=$!
trap './api.sh stop; kill $WEB 2>/dev/null; rm -f "$E2E_DB"' EXIT
sleep 1

WHICH=${1:-all}; [ $# -gt 0 ] && shift
STATUS=0
if [ "$WHICH" = all ] || [ "$WHICH" = late ]; then
  python3 test_late_install.py "$@" || STATUS=1
fi
if [ "$WHICH" = all ] || [ "$WHICH" = addexp ]; then
  python3 test_add_expense_group.py "$@" || STATUS=1
fi
if [ "$WHICH" = all ] || [ "$WHICH" = invites ]; then
  python3 test_invites.py "$@" || STATUS=1
fi
if [ "$WHICH" = all ] || [ "$WHICH" = nav ]; then
  python3 test_navigation.py "$@" || STATUS=1
fi
if [ "$WHICH" = all ] || [ "$WHICH" = contacts ]; then
  python3 test_contact_picker.py "$@" || STATUS=1
fi
if [ "$WHICH" = all ] || [ "$WHICH" = cards ]; then
  python3 test_share_cards.py "$@" || STATUS=1
fi
if [ "$WHICH" = all ] || [ "$WHICH" = refused ]; then
  python3 test_refused_changes.py "$@" || STATUS=1
fi
exit $STATUS
