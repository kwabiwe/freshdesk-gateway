#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r backend/requirements-dev.txt
npm --prefix frontend install

if [[ ! -f .env ]]; then
  cp .env.example .env
  printf '\nCreated .env from .env.example. Add your Freshdesk domain and personal API key before testing the connection.\n'
fi

printf '\nSetup complete. Run ./scripts/start.sh and open http://127.0.0.1:8787.\n'
