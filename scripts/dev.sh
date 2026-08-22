#!/usr/bin/env bash
# One-command local dev run: backend (FastAPI/uvicorn) + frontend (Vite),
# backgrounded together with a single Ctrl-C to stop both.
#
# What this script does NOT do: authenticate Google Earth Engine, install
# dependencies, or create venvs/node_modules. Those are one-time setup
# steps -- see root README.md "Setup from a clean clone". This script
# only starts the two long-running dev processes CLAUDE.md/
# .claude/agents/integration-docs.md call for ("a single script or
# documented command sequence that starts data-pipeline/detection (as
# needed), backend, and frontend together").
#
# Preconditions checked below, loudly, before anything starts:
#   1. backend/venv, detection/venv, data-pipeline/venv all exist.
#   2. frontend/node_modules exists.
#   3. detection/.env or data-pipeline/.env carries EE_PROJECT_ID (GEE
#      auth itself -- `earthengine authenticate` -- is NOT re-checked
#      live here; a missing/expired credential still fails loudly at
#      request time as a 503 with a fix-it message, per
#      data-pipeline/src/auth.py's GEEAuthError -- this script does not
#      duplicate that check, only the "did you even set EE_PROJECT_ID"
#      precondition).
#
# Usage:
#   ./scripts/dev.sh
#   (Ctrl-C stops both backend and frontend)
#
# Ports: backend on :8000, frontend on whatever Vite picks (default
# :5173, auto-increments if taken -- watch the frontend log line printed
# below for the actual URL).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"
DETECTION_DIR="$REPO_ROOT/detection"
DATA_PIPELINE_DIR="$REPO_ROOT/data-pipeline"

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

fail() {
  echo -e "${RED}dev.sh: $1${NC}" >&2
  exit 1
}

warn() {
  echo -e "${YELLOW}dev.sh: $1${NC}" >&2
}

# --- Preconditions ---------------------------------------------------------

[ -x "$BACKEND_DIR/venv/bin/uvicorn" ] || fail \
  "backend/venv is missing or incomplete. Run: cd backend && /opt/homebrew/bin/python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"

[ -d "$DETECTION_DIR/venv" ] || warn \
  "detection/venv not found -- fine if you only need the API/frontend to boot, but /detect, /risk-map, /validation will 503 (backend imports detection/src directly, in-process, not via detection/venv -- see backend/README.md 'Cross-project imports'; backend/venv itself is what matters for those routes, this is just a heads-up that detection/'s own tests/scripts won't run without it)."

[ -d "$DATA_PIPELINE_DIR/venv" ] || warn \
  "data-pipeline/venv not found -- same note as above: backend/venv carries its own earthengine-api install for the in-process import chain, so this alone won't block the API, but data-pipeline/'s own tests/scripts won't run without it."

[ -d "$FRONTEND_DIR/node_modules" ] || fail \
  "frontend/node_modules is missing. Run: cd frontend && npm install"

EE_PROJECT_SET=""
for env_file in "$DETECTION_DIR/.env" "$DATA_PIPELINE_DIR/.env"; do
  if [ -f "$env_file" ] && grep -q "^EE_PROJECT_ID=.\+" "$env_file"; then
    EE_PROJECT_SET="1"
    break
  fi
done
if [ -z "$EE_PROJECT_SET" ]; then
  warn "No EE_PROJECT_ID found in detection/.env or data-pipeline/.env, and 'earthengine authenticate' may not have been run."
  warn "The backend will still start, but every satellite-backed request (/detect, /risk-map after the scheduler's first pass, /validation, /timeseries) will fail loudly with a 503 GEEAuthError -- not silently fake data."
  warn "Fix: see root README.md 'Google Earth Engine setup', or data-pipeline/src/auth.py's FIX_IT_MESSAGE."
fi

echo -e "${GREEN}dev.sh: preconditions checked -- starting backend + frontend.${NC}"

# --- Start backend -----------------------------------------------------

cd "$BACKEND_DIR"
./venv/bin/python -m uvicorn src.main:app --reload --port 8000 &
BACKEND_PID=$!
cd "$REPO_ROOT"

# --- Start frontend ------------------------------------------------------

cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!
cd "$REPO_ROOT"

cleanup() {
  echo -e "\n${YELLOW}dev.sh: stopping backend (pid $BACKEND_PID) and frontend (pid $FRONTEND_PID)...${NC}"
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  echo -e "${GREEN}dev.sh: stopped.${NC}"
}
trap cleanup EXIT INT TERM

echo -e "${GREEN}dev.sh: backend -> http://localhost:8000 (docs at /docs), pid $BACKEND_PID${NC}"
echo -e "${GREEN}dev.sh: frontend -> see the 'Local:' line Vite prints above (default http://localhost:5173), pid $FRONTEND_PID${NC}"
echo -e "${GREEN}dev.sh: Ctrl-C to stop both.${NC}"

wait
