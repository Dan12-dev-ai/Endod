#!/usr/bin/env bash
# =============================================================================
# DEDAN Health — one-command local setup and launch.
#
#   ./scripts/setup-and-run.sh
#
# Creates a Python virtualenv, installs backend dependencies, copies the
# example environment file, and starts the API in the default OFFLINE (mock)
# mode — $0 cost and no AI provider credentials required.
#
# Logs and PID files are written to .run/ (git-ignored).
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

log_info "DEDAN Health — setup and run"
log_info "Repository: ${DEDAN_ROOT}"

# --- 1. Prerequisites --------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  log_error "python3 is required but was not found on PATH."
  exit 1
fi

# --- 2. Python environment ---------------------------------------------------
VENV_DIR="${DEDAN_ROOT}/.venv"
if [[ ! -d "${VENV_DIR}" ]]; then
  log_info "Creating Python virtualenv at ${VENV_DIR}"
  python3 -m venv "${VENV_DIR}"
fi
VENV_PY="${VENV_DIR}/bin/python"
if [[ ! -x "${VENV_PY}" ]]; then
  VENV_PY="${VENV_DIR}/bin/python3"
fi
if [[ ! -x "${VENV_PY}" ]]; then
  log_error "Could not find a Python interpreter inside ${VENV_DIR}."
  exit 1
fi
log_ok "Virtualenv ready"

# --- 3. Backend dependencies -------------------------------------------------
log_info "Installing backend dependencies (this may take a few minutes)..."
if ! "${VENV_PY}" -m pip install --quiet --upgrade pip >/dev/null 2>&1; then
  log_warn "Could not upgrade pip; continuing with the existing version."
fi
if ! "${VENV_PY}" -m pip install --quiet -r "${BACKEND_DIR}/requirements.txt"; then
  log_error "Failed to install backend dependencies."
  exit 1
fi
log_ok "Backend dependencies installed"

# --- 4. Environment file -----------------------------------------------------
if [[ ! -f "${BACKEND_DIR}/.env" ]]; then
  cp "${BACKEND_DIR}/.env.example" "${BACKEND_DIR}/.env"
  log_ok "Created ${BACKEND_DIR}/.env from .env.example"
else
  log_info "Using existing ${BACKEND_DIR}/.env"
fi

# --- 5. Start the service ----------------------------------------------------
mkdir -p "${DEDAN_RUN_DIR}"

# Offline mode keeps the run deterministic and free. Override by exporting
# AI_PROVIDER_MODE=gemini|openai together with a real credential.
export AI_PROVIDER_MODE="${AI_PROVIDER_MODE:-offline}"

if port_open "${BACKEND_PORT}"; then
  log_warn "Port ${BACKEND_PORT} is already in use; assuming the backend is already running."
else
  log_info "Starting API on port ${BACKEND_PORT} (AI_PROVIDER_MODE=${AI_PROVIDER_MODE})..."
  (
    cd "${BACKEND_DIR}"
    nohup "${VENV_PY}" -m uvicorn main_clinical:app \
      --host 0.0.0.0 --port "${BACKEND_PORT}" \
      > "${DEDAN_RUN_DIR}/backend.log" 2>&1 &
    echo $! > "${DEDAN_RUN_DIR}/backend.pid"
  )
  if wait_for_port "${BACKEND_PORT}" 60 "the backend API"; then
    log_ok "Backend listening on http://localhost:${BACKEND_PORT}"
  else
    log_error "Backend failed to start. See ${DEDAN_RUN_DIR}/backend.log"
    tail -20 "${DEDAN_RUN_DIR}/backend.log" 2>/dev/null || true
    exit 1
  fi
fi

echo
log_info "DEDAN Health is running"
printf '  API        : %s\n' "http://localhost:${BACKEND_PORT}"
printf '  Health     : %s\n' "http://localhost:${BACKEND_PORT}/api/health"
printf '  API docs   : %s\n' "http://localhost:${BACKEND_PORT}/docs"
echo
log_info "Mode: offline (deterministic, no AI provider calls, no cost)"
log_info "Stop with: ./scripts/stop.sh   |   Check with: ./scripts/health-check.sh"
echo
log_warn "DEDAN Health provides health education, not medical diagnosis."
log_warn "It is not a substitute for a qualified healthcare professional."
echo