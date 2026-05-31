# Freshdesk Gateway

A standalone local web app for drafting, validating, reviewing, and creating Freshdesk tickets through your own named Freshdesk account.

The gateway keeps the Freshdesk API key in the backend process only. It creates normal Freshdesk tickets. Its change-style workflow uses a versioned local drafting skill and a structured ticket template, not a Freshservice or ITIL change object.

## Quick Start

Requirements:

- macOS with Python 3.11+ and Node.js 20+
- A personal Freshdesk API key
- A local model server such as Ollama or LM Studio if you want drafting assistance

```bash
./scripts/setup.sh
```

Edit `.env`, then start the app:

```bash
./scripts/start.sh
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787).

To publish the loopback-only gateway privately to devices on your Tailnet:

```bash
./scripts/tailnet-serve.sh
```

The script prints the private Tailscale HTTPS URL. It does not expose the app to the public internet or your local network.

For frontend development with hot reload:

```bash
./scripts/dev.sh
```

The Vite frontend runs at [http://127.0.0.1:5173](http://127.0.0.1:5173) and proxies `/api` to FastAPI.

## Safety Defaults

- Every ticket is drafted and validated before creation.
- Ticket creation needs an explicit typed approval.
- Batch creation preflights the selected count against local limits.
- Obvious secrets block ticket creation and are rejected before local-model calls.
- Freshdesk writes default to 5 per hour.
- A `STOP` file blocks all Freshdesk operations immediately.
- Audit records stay in local SQLite.
- No Freshdesk note, tag, text, or marker indicates automation or AI use.
- Tailnet access uses private Tailscale Serve publishing while FastAPI remains bound to loopback.

See [GUIDE.md](GUIDE.md) for configuration, workflows, troubleshooting, and the optional later OpenClaw interface.
