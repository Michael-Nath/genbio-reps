#!/usr/bin/env bash
# Start the live collaborative notebook server.
# Usage: ./run.sh [notebook.ipynb] [port]
set -euo pipefail
cd "$(dirname "$0")"

NB="${1:-../00_foundations/01_proteins_as_tensors.ipynb}"
PORT="${2:-8000}"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q fastapi "uvicorn[standard]" jupyter_client ipykernel nbformat numpy matplotlib pyflakes
fi

export NB_PATH="$NB"
echo "serving $NB on http://0.0.0.0:$PORT  (open http://localhost:$PORT)"
exec .venv/bin/uvicorn server:app --host 0.0.0.0 --port "$PORT"
