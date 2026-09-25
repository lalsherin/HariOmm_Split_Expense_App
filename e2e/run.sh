#!/bin/sh
# Two-phone end-to-end check against a real (local, SQLite) server.
#
#   pip install -r ../backend/requirements-dev.txt playwright && playwright install chromium
#   ./run.sh            # all scenarios, each watched 35s   (~9 minutes)
#   ./run.sh 35 removed_then_hides,stuck_37_phone_upgrades
#
# Builds the phone page from web/split-ledger.html first, so it tests what the
# APK would carry.
set -e
cd "$(dirname "$0")"
HERE=$(pwd)
node ../android/build_asset.js
python3 make_page.py

DB=$(mktemp -u /tmp/split-e2e-XXXXXX.db)
( cd ../backend && DATABASE_URL="sqlite+aiosqlite:///$DB" REQUIRE_OTP=false \
    RL_SYNC_PER_USER=100000 RL_AUTH_PER_NUMBER=1000 RL_AUTH_PER_IP=1000 \
    exec python3 -m uvicorn app.main:app --port 8000 --log-level warning ) &
API=$!
( cd www && exec python3 -m http.server 8080 >/dev/null 2>&1 ) &
WEB=$!
trap 'kill $API $WEB 2>/dev/null; rm -f "$DB"' EXIT
sleep 3
python3 test_refused_changes.py "$@"
