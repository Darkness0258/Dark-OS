#!/bin/bash
# Launches every darkos-*.py bare (no args) against a headless compositor,
# three seconds each, SIGTERM then SIGKILL, and checks stderr for an
# unhandled Python traceback. Several of these scripts are daemons or CLI
# tools that correctly print a usage error with no window to show when run
# with no arguments -- expected, not a failure. An uncaught-exception
# traceback is. Run through run-all.sh, or inside a session started with
# lib.sh.
#   bash ci/headless/app_launch_check.sh [output-log-path]
set -u
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

OUT="${1:-/tmp/darkos-app-launch-audit.log}"
: > "$OUT"

for script in "$DARKOS_BIN"/darkos-*.py; do
  name=$(basename "$script")
  echo "===== $name =====" >> "$OUT"
  timeout 6 python3 "$script" >>"$OUT" 2>&1 &
  pid=$!
  sleep 3
  kill -TERM "$pid" 2>/dev/null
  sleep 0.3
  kill -KILL "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null
  echo >> "$OUT"
done

count=$(grep -c "Traceback (most recent call last):" "$OUT")
echo "wrote $OUT ($(grep -c '^=====' "$OUT") scripts launched, $count traceback(s))"
if [ "$count" -ne 0 ]; then
  echo "FAILED: see $OUT for the script(s) that crashed" >&2
  exit 1
fi
echo "ALL SCRIPTS STARTED WITHOUT AN UNHANDLED TRACEBACK"
