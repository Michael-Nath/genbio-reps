#!/usr/bin/env bash
# Start the live server AND a public tunnel, so a friend can join from anywhere.
# Usage: ./share.sh [notebook.ipynb] [port]
#
# Prints a https://<random>.trycloudflare.com URL — send it to your friend.
# Both of you open the same URL, type a name, and you share one live notebook.
set -euo pipefail
cd "$(dirname "$0")"

NB="${1:-../00_foundations/01_proteins_as_tensors.ipynb}"
PORT="${2:-8000}"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q fastapi "uvicorn[standard]" jupyter_client ipykernel nbformat numpy matplotlib pyflakes
fi

CF="./.bin/cloudflared"
if [ ! -x "$CF" ]; then
  if command -v cloudflared >/dev/null 2>&1; then
    CF="cloudflared"
  else
    echo "cloudflared not found. Get it with:" >&2
    echo "  mkdir -p .bin && curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz | tar xz -C .bin" >&2
    exit 1
  fi
fi

export NB_PATH="$NB"
.venv/bin/uvicorn server:app --host 127.0.0.1 --port "$PORT" > /tmp/reps_server.log 2>&1 &
SPID=$!
trap 'kill $SPID 2>/dev/null || true' EXIT
sleep 3

echo "local:  http://localhost:$PORT"
echo "notebook: $NB"
echo "----------------------------------------------------------------"
echo "Public URL below — send it to your friend. Ctrl-C to stop."
echo "----------------------------------------------------------------"
exec "$CF" tunnel --url "http://localhost:$PORT"
