#!/usr/bin/env bash
# =============================================================================
# DEDAN Health — shared shell helpers
#
# Sourced by the scripts in this directory. Provides consistent logging and
# DEDAN-specific process discovery.
# =============================================================================

# Resolve the repository root. This file lives at <repo>/scripts/lib/common.sh,
# so the root is two levels up. Deriving it from the script's own location
# (rather than from the caller) keeps the value correct no matter which script
# sources this file, and independent of the caller's working directory.
DEDAN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export DEDAN_ROOT

# Runtime directory for PID files and logs. Kept out of version control.
DEDAN_RUN_DIR="${DEDAN_ROOT}/.run"
export DEDAN_RUN_DIR

BACKEND_DIR="${DEDAN_ROOT}/backend-v2"

# Ports (override via environment).
BACKEND_PORT="${BACKEND_PORT:-8001}"
export BACKEND_PORT

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  C_RED=$'\033[0;31m'; C_GREEN=$'\033[0;32m'
  C_YELLOW=$'\033[0;33m'; C_BLUE=$'\033[0;34m'; C_RESET=$'\033[0m'
else
  C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_RESET=""
fi

log_info()    { printf '%s[INFO]%s %s\n'  "${C_BLUE}"   "${C_RESET}" "$*"; }
log_ok()      { printf '%s[ OK ]%s %s\n'  "${C_GREEN}"  "${C_RESET}" "$*"; }
log_warn()    { printf '%s[WARN]%s %s\n'  "${C_YELLOW}" "${C_RESET}" "$*"; }
log_error()   { printf '%s[FAIL]%s %s\n'  "${C_RED}"    "${C_RESET}" "$*" >&2; }

# Is a TCP port accepting connections on localhost?
port_open() {
  local port="$1"
  (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null && exec 3<&- 3>&- && return 0
  return 1
}

# Wait until a TCP port starts accepting connections.
# Usage: wait_for_port <port> <timeout_seconds> [label]
wait_for_port() {
  local port="$1" timeout="${2:-30}" label="${3:-port ${1}}"
  local elapsed=0
  while (( elapsed < timeout )); do
    if port_open "${port}"; then
      return 0
    fi
    sleep 1
    ((elapsed++))
  done
  log_error "Timed out after ${timeout}s waiting for ${label} (port ${port})."
  return 1
}

# ---------------------------------------------------------------------------
# DEDAN-specific process discovery
#
# These helpers deliberately match on the DEDAN repository path so they can
# never terminate an unrelated project's application server (e.g. another
# app on the same machine also running `uvicorn` on a different port).
# ---------------------------------------------------------------------------

# Print PIDs whose command line references this DEDAN checkout.
dedan_pids_for() {
  local pattern="$1"     # e.g. "uvicorn" or "vite"
  pgrep -f "${DEDAN_ROOT}/.*${pattern}" 2>/dev/null || true
}

# Resolve a recorded PID file to a live PID, or print nothing.
pid_from_file() {
  local file="$1"
  [[ -f "${file}" ]] || return 1
  local pid
  pid="$(cat "${file}" 2>/dev/null || true)"
  [[ -n "${pid}" ]] || return 1
  kill -0 "${pid}" 2>/dev/null || return 1
  printf '%s' "${pid}"
  return 0
}
