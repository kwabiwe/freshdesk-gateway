#!/usr/bin/env bash
set -euo pipefail

find_tailscale() {
  if command -v tailscale >/dev/null 2>&1; then
    command -v tailscale
    return
  fi
  if [[ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]]; then
    printf '%s\n' /Applications/Tailscale.app/Contents/MacOS/Tailscale
    return
  fi
  printf 'Tailscale CLI not found.\n' >&2
  exit 1
}

TAILSCALE_BIN="$(find_tailscale)"
"$TAILSCALE_BIN" serve reset
printf 'Freshdesk Gateway Tailnet publishing is disabled.\n'
