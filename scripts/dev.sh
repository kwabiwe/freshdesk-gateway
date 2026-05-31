#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"
if [[ ! -x .venv/bin/python ]]; then
  printf 'Missing .venv. Run ./scripts/setup.sh first.\n' >&2
  exit 1
fi

trap 'kill 0' EXIT
.venv/bin/python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8787 &
npm --prefix frontend run dev
