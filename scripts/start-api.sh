#!/usr/bin/env bash
# Start the DEDAN Health API in the background for local review.
#
# Uses setsid so the server is not in the caller's process group and survives
# the launching shell exiting. Logs to /tmp/opencode/api.log.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${DEDAN_API_LOG:-/tmp/opencode/api.log}"
PORT="${DEDAN_PORT:-8001}"

mkdir -p "$(dirname "$LOG")"

if pgrep -f "uvicorn main_clinical" >/dev/null 2>&1; then
  pkill -f "uvicorn main_clinical" || true
  sleep 3
fi

cd "$ROOT/backend-v2"
AI_PROVIDER_MODE="${AI_PROVIDER_MODE:-offline}" \
  setsid "$ROOT/.venv/bin/python" -m uvicorn main_clinical:app \
  --host 0.0.0.0 --port "$PORT" >"$LOG" 2>&1 </dev/null &

disown || true
echo "DEDAN API starting on port $PORT (log: $LOG)"
