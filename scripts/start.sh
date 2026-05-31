#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"
if [[ ! -x .venv/bin/python ]]; then
  printf 'Missing .venv. Run ./scripts/setup.sh first.\n' >&2
  exit 1
fi

npm --prefix frontend run build
exec .venv/bin/python -m uvicorn app.main:app \
  --app-dir backend \
  --host "${APP_HOST:-127.0.0.1}" \
  --port "${APP_PORT:-8787}"
