#!/usr/bin/env bash
# =============================================================================
# DEDAN Health — stop the DEDAN services.
#
# Scope is deliberately narrow: this script only terminates processes that
# belong to THIS checkout (by recorded PID file, and by a command line that
# references the DEDAN repository path). It never runs a blanket
# `pkill -f uvicorn`, which would also kill unrelated projects running their
# own ASGI servers on the same machine.
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

log_info "Stopping DEDAN Health services"

stopped_any=0

# --- 1. Stop via recorded PID files -----------------------------------------
for service in backend; do
  pidfile="${DEDAN_RUN_DIR}/${service}.pid"
  if pid="$(pid_from_file "${pidfile}")"; then
    log_info "Stopping ${service} (pid ${pid})"
    # TERM first so the server can shut down cleanly; escalate only if needed.
    kill -TERM "${pid}" 2>/dev/null || true
    for _ in $(seq 1 10); do
      kill -0 "${pid}" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "${pid}" 2>/dev/null; then
      log_warn "${service} did not exit; sending SIGKILL"
      kill -KILL "${pid}" 2>/dev/null || true
    fi
    stopped_any=1
  fi
  rm -f "${pidfile}"
done

# --- 2. Sweep any stragglers from THIS checkout -----------------------------
# The pattern includes the DEDAN root path, so only our own processes match.
for pattern in uvicorn; do
  for pid in $(dedan_pids_for "${pattern}"); do
    # Never signal ourselves or our own process group.
    [[ "${pid}" == "$$" || "${pid}" == "${PPID}" ]] && continue
    log_info "Stopping leftover ${pattern} process (pid ${pid})"
    kill -TERM "${pid}" 2>/dev/null || true
    stopped_any=1
  done
done

# --- 3. Report --------------------------------------------------------------
if (( stopped_any )); then
  sleep 1
  log_ok "DEDAN Health services stopped."
else
  log_info "No running DEDAN Health services were found."
fi

# Informational only — a closed port may belong to a different process.
for port in "${FRONTEND_PORT}" "${BACKEND_PORT}"; do
  if port_open "${port}"; then
    log_warn "Port ${port} is still accepting connections (may be an unrelated process)."
  fi
done
