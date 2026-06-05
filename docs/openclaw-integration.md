# OpenClaw Integration

This guide connects an OpenClaw orchestrator on another Tailnet device to a MacBook-hosted Freshdesk Gateway.

Use this topology:

- MacBook: gateway host, Freshdesk credential holder, schema cache owner, local LLM host, review UI.
- Mac Mini/OpenClaw: orchestrator that gathers context, asks the gateway for metadata, submits draft envelopes, and reads approval feedback.
- GitHub: code only.
- Local runtime state: never pushed to GitHub.

## Runtime State

The gateway stores runtime state in SQLite:

```text
data/freshdesk_gateway.db
```

Important tables:

- `schema_cache`: synced Freshdesk metadata such as ticket fields, groups, agents, companies, and ticket forms.
- `agent_drafts`: OpenClaw-submitted draft envelopes and approval feedback.
- `drafts`: manual UI drafts.
- `audit_log`: local audit trail.
- `settings`: runtime UI overrides.
- `rate_events`: local rate-limit counters.

The following paths are intentionally ignored by Git:

- `.env`
- `data/`
- `STOP`
- `.venv/`
- `frontend/node_modules/`
- `frontend/dist/`

Freshdesk schema sync is local to the machine running the gateway. If you sync on the MacBook, the schema is in the MacBook SQLite DB. The Mac Mini does not need a DB copy because it calls the MacBook gateway API.

## MacBook Setup

Update the repo:

```bash
cd /path/to/freshdesk-gateway
git pull origin main
./scripts/setup.sh
```

`setup.sh` creates `.env` only if it does not already exist. It should not replace existing Freshdesk credentials or `data/freshdesk_gateway.db`.

Set the agent API token:

```bash
openssl rand -hex 32
```

Edit `.env`:

```bash
AGENT_API_TOKEN=paste_generated_token_here
```

Do not quote the token. Restart the gateway after changing `.env`; environment variables are read when the server starts.

Start the gateway:

```bash
./scripts/start.sh
```

Verify local health on the MacBook:

```bash
curl http://127.0.0.1:8787/api/health
```

Expected:

```json
{"ok":true,"service":"freshdesk-gateway","local_only":true}
```

Run Freshdesk schema sync from the UI after Freshdesk credentials are configured:

```text
Settings & help -> Test Freshdesk connection
Freshdesk schema -> Sync schema
```

## Private Tailscale Serve

Keep the gateway bound to loopback. Do not bind FastAPI to `0.0.0.0` for this workflow.

In a second MacBook terminal:

```bash
cd /path/to/freshdesk-gateway
./scripts/tailnet-serve.sh
```

Copy the private HTTPS URL printed by `tailscale serve status`.

To remove the private Tailnet route:

```bash
./scripts/tailnet-stop.sh
```

Do not use Tailscale Funnel. Funnel publishes beyond the private Tailnet.

## Mac Mini / OpenClaw Setup

Store the MacBook gateway URL and token outside the repo:

```bash
mkdir -p ~/.openclaw/workspace/.secrets
nano ~/.openclaw/workspace/.secrets/freshdesk-gateway.env
```

Add:

```bash
export FRESHDESK_GATEWAY_URL="https://tailnet-url-from-tailscale-serve"
export AGENT_API_TOKEN="same-token-as-macbook-env"
```

Lock down the file:

```bash
chmod 600 ~/.openclaw/workspace/.secrets/freshdesk-gateway.env
```

Load it in a shell:

```bash
source ~/.openclaw/workspace/.secrets/freshdesk-gateway.env
```

Basic reachability:

```bash
curl "$FRESHDESK_GATEWAY_URL/api/health"
```

Authenticated metadata:

```bash
curl -H "Authorization: Bearer $AGENT_API_TOKEN" \
  "$FRESHDESK_GATEWAY_URL/api/v1/metadata"
```

The unauthenticated metadata request should return `401` when `AGENT_API_TOKEN` is configured and the gateway has been restarted.

## OpenClaw Helper CLI

From the OpenClaw/Mac Mini clone:

```bash
cd ~/.openclaw/workspace/projects/freshdesk-gateway
source ~/.openclaw/workspace/.secrets/freshdesk-gateway.env
scripts/openclaw-gateway.py metadata
scripts/openclaw-gateway.py list --limit 5
scripts/openclaw-gateway.py submit path/to/draft-envelope.json
scripts/openclaw-gateway.py get agd_123
```

Commands:

- `metadata`: fetch current Freshdesk metadata visible to agent callers.
- `list`: list recent OpenClaw-submitted drafts.
- `submit`: submit a draft envelope JSON file for review.
- `get`: fetch a draft by ID, including feedback after approval.

## End-to-End Flow

1. KB asks OpenClaw for a ticket draft, for example: "draft a Freshdesk change ticket from this email thread".
2. OpenClaw gathers relevant context from connected sources.
3. OpenClaw calls `GET /api/v1/metadata` to inspect the MacBook gateway's synced Freshdesk schema.
4. OpenClaw creates a versioned draft envelope with semantic fields, description sections, sources, assumptions, missing information, and validation hints.
5. OpenClaw submits the envelope to `POST /api/v1/drafts`.
6. KB opens the gateway UI on the MacBook and reviews the AI Agent draft.
7. KB edits any field or description section.
8. The gateway records revision events.
9. KB types the mode-specific approval phrase:
   - `CREATE` for create mode.
   - `UPDATE` for update mode.
   - `CREATE BULK` for bulk-create mode.
10. The gateway converts the reviewed ledger into the Freshdesk API payload.
11. The gateway writes to Freshdesk.
12. OpenClaw fetches `GET /api/v1/drafts/{draft_id}` and reads `feedback_payload`.

## Field Mapping Boundary

OpenClaw sends semantic intent:

- `product`
- `contact`
- `subject`
- `form`
- `ticket_type`
- `status`
- `business_impact`
- `group`
- `agent`
- `priority`
- schema-backed `cf_*` fields listed in `freshdesk_form_profiles`
- `description_sections`

The gateway maps reviewed fields to Freshdesk:

- `subject` -> `subject`
- rendered `description_sections` -> `description`
- `contact` -> `email`, `name`, or `requester_id`
- `group` -> `group_id`
- `agent` -> `responder_id`
- `status` -> Freshdesk status integer
- `priority` -> Freshdesk priority integer
- visible `form` -> A24 custom `cf_form2`
- visible `ticket_type` -> A24 custom `cf_type` when that field exists
- schema-backed `cf_*` ledger fields -> `custom_fields`
- Freshdesk's default API `type` is used only when the reviewed field binds to the default `ticket_type` field

The gateway owns Freshdesk IDs and validation. OpenClaw should not create, update, close, or otherwise write directly to Freshdesk.

## Real-Test Checklist

Run these from the Mac Mini/OpenClaw side after the MacBook gateway has been restarted from the latest code:

```bash
source ~/.openclaw/workspace/.secrets/freshdesk-gateway.env

curl "$FRESHDESK_GATEWAY_URL/api/health"

curl -o /tmp/fdgw-noauth.out -w "%{http_code}\n" \
  "$FRESHDESK_GATEWAY_URL/api/v1/metadata"

curl -H "Authorization: Bearer $AGENT_API_TOKEN" \
  "$FRESHDESK_GATEWAY_URL/api/settings"

scripts/openclaw-gateway.py metadata
scripts/openclaw-gateway.py list --limit 5
```

Expected:

- `/api/health` returns `200`.
- unauthenticated `/api/v1/metadata` returns `401` when token auth is enabled.
- `/api/settings` includes `"agent_api_auth_required": true`.
- `metadata` shows non-zero Freshdesk ticket fields after schema sync.
- `list` returns JSON, not the frontend HTML document.

If `list` returns HTML, the MacBook gateway is still running old code or was not restarted after pulling.

If unauthenticated metadata returns `200`, `AGENT_API_TOKEN` is not configured in the running MacBook process.
