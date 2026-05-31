#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${APP_PORT:-8787}"

find_tailscale() {
  if command -v tailscale >/dev/null 2>&1; then
    command -v tailscale
    return
  fi
  if [[ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]]; then
    printf '%s\n' /Applications/Tailscale.app/Contents/MacOS/Tailscale
    return
  fi
  printf 'Tailscale CLI not found. Install and sign in to Tailscale first.\n' >&2
  exit 1
}

cd "$ROOT"
if ! curl --fail --silent "http://127.0.0.1:${PORT}/api/health" >/dev/null; then
  printf 'Freshdesk Gateway is not running on http://127.0.0.1:%s. Start ./scripts/start.sh first.\n' "$PORT" >&2
  exit 1
fi

TAILSCALE_BIN="$(find_tailscale)"
"$TAILSCALE_BIN" serve --bg --yes "http://127.0.0.1:${PORT}"
"$TAILSCALE_BIN" serve status
