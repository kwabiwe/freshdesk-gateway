#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def api_base(raw_url: str) -> str:
    base = raw_url.rstrip("/")
    if not base.endswith("/api"):
        base = f"{base}/api"
    return base


def call_gateway(method: str, path: str, *, base_url: str, token: str = "", body: Any = None) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{api_base(base_url)}{path}",
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Gateway returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach gateway: {exc.reason}") from exc
    return json.loads(payload.decode("utf-8")) if payload else None


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenClaw helper for the Freshdesk gateway AI Agent API.")
    parser.add_argument("--url", default=os.environ.get("FRESHDESK_GATEWAY_URL", "http://127.0.0.1:8787"), help="Gateway base URL, with or without /api.")
    parser.add_argument("--token", default=os.environ.get("AGENT_API_TOKEN", ""), help="Agent API token. Defaults to AGENT_API_TOKEN.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("metadata", help="Fetch current Freshdesk metadata visible to agent callers.")

    list_parser = sub.add_parser("list", help="List recent submitted AI Agent drafts.")
    list_parser.add_argument("--limit", type=int, default=20)

    get_parser = sub.add_parser("get", help="Fetch one submitted draft by ID.")
    get_parser.add_argument("draft_id")

    submit_parser = sub.add_parser("submit", help="Submit a draft envelope JSON file for review.")
    submit_parser.add_argument("draft_json", type=Path)

    args = parser.parse_args()
    if args.command == "metadata":
        print_json(call_gateway("GET", "/v1/metadata", base_url=args.url, token=args.token))
    elif args.command == "list":
        print_json(call_gateway("GET", f"/v1/drafts?limit={args.limit}", base_url=args.url, token=args.token))
    elif args.command == "get":
        print_json(call_gateway("GET", f"/v1/drafts/{args.draft_id}", base_url=args.url, token=args.token))
    elif args.command == "submit":
        payload = json.loads(args.draft_json.read_text())
        result = call_gateway("POST", "/v1/drafts", base_url=args.url, token=args.token, body=payload)
        print_json(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
