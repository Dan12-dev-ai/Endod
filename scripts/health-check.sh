#!/usr/bin/env bash
# =============================================================================
# DEDAN Health — system health check.
#
#   ./scripts/health-check.sh
#
# Verifies the backend and the API health endpoint.
# Reports READY only when every required check passes.
# =============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

echo "DEDAN Health System Check"
echo "=========================================================="
echo

failures=0

# --- Backend: TCP reachability ----------------------------------------------
if port_open "${BACKEND_PORT}"; then
  log_ok "Backend reachable (port ${BACKEND_PORT})"
else
  log_error "Backend not reachable (port ${BACKEND_PORT})"
  failures=$((failures + 1))
fi

# --- Backend: /api/health ----------------------------------------------------
health_body=""
if health_body="$(curl -fsS --max-time 10 "http://localhost:${BACKEND_PORT}/api/health" 2>/dev/null)"; then
  log_ok "Health endpoint (/api/health)"
  printf '       %s\n' "${health_body}"
else
  log_error "Health endpoint (/api/health) did not respond successfully"
  failures=$((failures + 1))
fi

# --- Backend: legacy /health alias ------------------------------------------
if curl -fsS --max-time 10 "http://localhost:${BACKEND_PORT}/health" >/dev/null 2>&1; then
  log_ok "Health alias (/health)"
else
  log_warn "Health alias (/health) unavailable"
fi

# --- Backend: providers listing ---------------------------------------------
if curl -fsS --max-time 10 "http://localhost:${BACKEND_PORT}/api/providers" >/dev/null 2>&1; then
  log_ok "Provider registry (/api/providers)"
else
  log_warn "Provider registry (/api/providers) unavailable"
fi

echo
echo "=========================================================="
if (( failures == 0 )); then
  echo "System status: READY"
  echo "  API:        http://localhost:${BACKEND_PORT}"
  echo "  API docs:   http://localhost:${BACKEND_PORT}/docs"
  exit 0
else
  echo "System status: NOT READY (${failures} check(s) failed)"
  echo "  Start the backend with: ./scripts/setup-and-run.sh"
  exit 1
fi
