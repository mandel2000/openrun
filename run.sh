#!/usr/bin/env bash
# OpenRun: build the UI (first time) and start the app on http://localhost:8000
#   OPENRUN_HOST=0.0.0.0 OPENRUN_PIN=<pin> ./run.sh   -> also reachable from your phone on the same wifi
set -euo pipefail
cd "$(dirname "$0")"
if [ -f .env ]; then set -a; . ./.env; set +a; fi  # settings from .env (see .env.example)
PY=${PYTHON:-python3}
HOST=${OPENRUN_HOST:-127.0.0.1}
if [ "$HOST" != "127.0.0.1" ] && [ "$HOST" != "localhost" ] && [ -z "${OPENRUN_PIN:-}" ]; then
  echo "Para abrir OpenRun en la red local define un PIN: OPENRUN_HOST=$HOST OPENRUN_PIN=<pin> ./run.sh" >&2
  exit 1
fi
if [ ! -d backend/.venv ]; then
  "$PY" -m venv backend/.venv
fi
backend/.venv/bin/pip install -q -r backend/requirements.txt
if [ ! -d frontend/dist ] || [ -n "$(find frontend/src frontend/index.html frontend/public -newer frontend/dist -print -quit 2>/dev/null)" ]; then
  (cd frontend && npm install --silent && npm run build)
fi
cd backend
export OPENRUN_HOST="$HOST"
exec .venv/bin/uvicorn app.main:app --host "$HOST" --port "${PORT:-8000}"
