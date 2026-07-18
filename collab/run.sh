#!/usr/bin/env bash
# Start the live collaborative notebook server.
# Every .ipynb in the repo is auto-discovered as its own session — open
# http://localhost:$PORT to see the list, or jump straight to /n/<slug>.
# Usage: ./run.sh [port]
set -euo pipefail
cd "$(dirname "$0")"

PORT="${1:-8000}"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q fastapi "uvicorn[standard]" jupyter_client ipykernel nbformat numpy matplotlib pyflakes
fi

echo "serving sessions on http://0.0.0.0:$PORT  (open http://localhost:$PORT)"
exec .venv/bin/uvicorn server:app --host 0.0.0.0 --port "$PORT"
