#!/bin/sh
# Start, stop or restart the local API used by the end-to-end checks.
#   E2E_DB   sqlite file to use (kept across restarts — that is the point)
#   ./api.sh start | stop | restart
cd "$(dirname "$0")"
PIDFILE=${E2E_PIDFILE:-/tmp/split-e2e-api.pid}
stop() {
  [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null
  rm -f "$PIDFILE"; sleep 0.7
}
start() {
  ( cd ../backend && DATABASE_URL="sqlite+aiosqlite:///${E2E_DB:?set E2E_DB}" REQUIRE_OTP=false \
      RL_SYNC_PER_USER=100000 RL_AUTH_PER_NUMBER=1000 RL_AUTH_PER_IP=1000 \
      exec python3 -m uvicorn app.main:app --port 8000 --log-level warning ) >/dev/null 2>&1 &
  echo $! > "$PIDFILE"
  for i in $(seq 1 60); do
    curl -s -m 1 -o /dev/null http://127.0.0.1:8000/health && return 0
    sleep 0.25
  done
  echo "api did not start" >&2; return 1
}
case "$1" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  *) echo "usage: $0 start|stop|restart" >&2; exit 2 ;;
esac
