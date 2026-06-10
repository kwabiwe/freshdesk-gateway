# Freshdesk Gateway User Guide

## What This App Does

Freshdesk Gateway is a local productivity tool for creating Freshdesk tickets safely and quickly. It supports standard tickets, structured change-request-style tickets, and batches of similar tickets.

A change-style ticket is still a normal Freshdesk ticket. This project does not assume Freshservice or ITIL change-management objects exist.

The browser UI talks only to the local FastAPI backend. The backend holds your personal API key, validates each draft, enforces rate limits, writes the local audit trail, and makes Freshdesk requests as your named Freshdesk account.

## What It Does Not Do

The MVP does not delete, close, merge, bulk-update, or reassign existing tickets. It does not send public replies. It does not add automation notes, AI markers, tags, or other visible Freshdesk metadata. It does not need a specific AI agent or cloud AI.

## Install

You need Python 3.11 or newer and Node.js 20 or newer.

```bash
./scripts/setup.sh
```

This creates `.venv`, installs backend and frontend dependencies, and copies `.env.example` to `.env` if needed.

## Configure `.env`

Edit `.env` locally:

```dotenv
FRESHDESK_DOMAIN=example
FRESHDESK_API_KEY=xxxxx
LOCAL_LLM_PROVIDER=auto
LOCAL_LLM_URL=http://127.0.0.1:11434
LOCAL_LLM_MODEL=llama3.1
LOCAL_LLM_GENERATION_TIMEOUT_SECONDS=300
MAX_WRITES_PER_HOUR=5
MAX_READS_PER_HOUR=60
MAX_TICKET_CREATIONS_PER_HOUR=5
MY_NAME=My Name
MY_EMAIL=my.email@example.com
APP_HOST=127.0.0.1
APP_PORT=8787
DRAFT_EXPIRY_MINUTES=30
CHANGE_DRAFTING_SKILL=change_management_drafting
AGENT_API_TOKEN=
```

Use the Freshdesk subdomain only for `FRESHDESK_DOMAIN`, unless you deliberately provide the full Freshdesk base URL. The `.env` file is excluded from Git.

Your Freshdesk API key is used as the Basic Auth username with `X` as the password. It never goes to the frontend, local model server, audit records, browser storage, or Freshdesk ticket content.

## Start Everything

For normal use:

```bash
./scripts/start.sh
```

This builds the React UI and serves it from FastAPI at [http://127.0.0.1:8787](http://127.0.0.1:8787).

For UI development:

```bash
./scripts/dev.sh
```

## Private Tailnet Access

The normal launcher keeps FastAPI bound to `127.0.0.1`. To reach the gateway from your other Tailnet devices without exposing it to the public internet or your local network, keep the gateway running and publish it privately through Tailscale Serve:

```bash
./scripts/tailnet-serve.sh
```

The script detects either a `tailscale` command on your path or the bundled macOS Tailscale app binary. It prints the private HTTPS URL to open from devices signed into your Tailnet.

To remove the Tailnet route:

```bash
./scripts/tailnet-stop.sh
```

Do not use Tailscale Funnel for this gateway. Funnel would publish the service beyond your Tailnet.

## Connect A Local Model

Ollama works directly:

```bash
ollama pull llama3.1
ollama serve
```

LM Studio and other OpenAI-compatible local servers also work. For LM Studio, start its local server and set `LOCAL_LLM_URL=http://127.0.0.1:1234`. Leave `LOCAL_LLM_PROVIDER=auto`, or choose the provider explicitly in **Settings & Help**.

Use **Refresh model list** to discover the server's available models, choose one from the dropdown, save settings, and use **Test local model** to verify connectivity.

The local model server is optional. Manual ticket drafting still works when it is unavailable. The gateway runs deterministic secret detection before sending notes to the server.

Larger local models can take several minutes to load or generate on a laptop. The gateway defaults to a 300-second generation timeout. When Ollama is selected, it keeps the model warm for 15 minutes after use. Increase `LOCAL_LLM_GENERATION_TIMEOUT_SECONDS` or select a smaller model if generations remain slow. Older `OLLAMA_*` environment variable names remain accepted for compatibility.

For change drafting, prefer an instruction model that reliably returns JSON. Some reasoning-first models may spend their output budget on internal reasoning instead of the structured record. In that case the gateway opens an editable fallback document with a warning; select another discovered model in **Settings & Help** for fuller automatic drafting.

## Test Freshdesk And Sync Schema

Open **Settings & Help** and select **Test Freshdesk**. Then open **Freshdesk schema** and select **Sync Freshdesk schema**.

Schema sync caches locally:

- Ticket fields and required-field flags
- Custom fields and dropdown values where Freshdesk exposes them
- Groups
- Agents
- Companies and ticket-form metadata where your permissions allow

The schema page shows inaccessible resources. For groups and agents, the gateway uses values embedded in the successful ticket-fields response when your personal agent role cannot call the admin-only list endpoints. The gateway does not guess inaccessible required fields.

## Create A Standard Ticket

1. Open **New ticket**.
2. Add rough notes. Your configured requester identity is entered automatically and remains editable.
3. Optionally select **Draft with local model**.
4. Complete the exact subject, description, and any required discovered fields.
5. Select **Save draft for review**.
6. Review the outgoing payload and validation panel.
7. Select **Approve and create**, then type `CREATE`.

The backend re-validates the saved draft immediately before sending it to Freshdesk.

Unsaved text remains available when you move between pages while the local web app stays open. It is kept in browser memory only and is cleared by a full page reload or browser close.

## Create A Change-Style Ticket

Open **Change-style ticket** and paste your technical notes, relevant email text, and any prior plan. Select **Structure with local model**. The gateway uses its versioned local change-drafting skill and your synced Freshdesk schema to extract evidence, resolve relative dates against your local timezone, infer conservative operational detail, and propose values for real Freshdesk fields.

Before you save, the page separates auto-filled Freshdesk fields, missing required fields, assumptions, open questions, `TBD` values, low-confidence values, field-mapping notes, and the validation preview. Dropdown suggestions are accepted only when they match values discovered from Freshdesk. Review and correct these suggestions directly in the form.

Edit the generated sections directly. The rich Freshdesk Description preview updates from the structured record through the backend renderer. The template covers:

- Change type and workflow state
- Planned change date or start/end window
- Customer and environment
- Configuration items
- Background of change
- Change description
- Implementation steps
- Rollback branches
- Pre-change, in-change, and post-change verification
- Risk and impact
- Risks and mitigations
- Communication plan
- Expected outcome
- Success criteria
- Dependencies

Unsupported specifics remain `TBD` instead of being invented. Inferred Freshdesk dropdown values remain editable. Open questions stay in the local review panel and are not blindly added to the Freshdesk Description. Save the draft only after reviewing the assumptions, open questions, required-field preview, mapped fields, and final Description preview. The server re-renders the Description and re-runs deterministic mapping when saving, then validates the exact payload before approval.

This creates a normal Freshdesk ticket after review and typed approval. The structured change record stays in local SQLite only. Configuration items, rollback, and verification are rendered into the Description because Freshdesk does not expose dedicated fields for them.

Open **Settings & Help** to view the active read-only change skill version and section list.

## Local Drafting Skills

Local drafting instructions live under `skills/`. Each skill has its own folder and `skill.json` manifest:

```text
skills/
  change_management_drafting/
    skill.json
    SKILL.md
    TEMPLATE.md
    examples/
```

The gateway discovers every manifest-backed folder through its local skill registry. `CHANGE_DRAFTING_SKILL` chooses the skill used by the change-style workflow. The active skill and discovered catalogue appear in **Settings & Help**. Additional workflows can select different registered skills later without replacing the change-management instructions.

## Create Batch Tickets

Open **Batch tickets** and paste CSV, tab-separated table text, pipe-separated text, or a JSON array. Include a header row. Common new-user headers are:

```text
name,email,department,manager,start_date,site,required_access,device_requirement
```

Select **Parse into drafts**. Review every generated draft, select valid drafts, choose **Create selected**, and type `CREATE BATCH`.

Each created Freshdesk ticket counts as one write and one ticket creation. The backend blocks the full batch before sending anything if the selected count exceeds the available local limit.

## Validation And Approval

Drafts are local SQLite records with an expiry time. Validation checks:

- Freshdesk-required fields discovered during schema sync
- Requester email, subject, and description required by the create workflow
- Obvious passwords, API keys, bearer tokens, private keys, session-like tokens, recovery codes, and password-bearing connection strings

The local model can suggest editable values but cannot approve them. A ticket is created only after you review the exact draft and type the approval phrase.

AI Agent drafts use the same hard approval pattern. Create mode requires `CREATE`, update mode requires `UPDATE`, and bulk-create mode requires `CREATE BULK`.

The AI Agent review page shows a numbered Change Request field ledger plus a separate **Freshdesk Description** editor. The description sections are combined into one Freshdesk `description` payload field; they are not separate custom fields unless the synced Freshdesk schema exposes matching `cf_*` fields.

Before approval, the review panel also shows the exact outgoing Freshdesk payload. The gateway blocks unsupported top-level keys locally. Review-only names such as Product, Contact, Form, Group, Agent, Customer, Business Impact, and Change State must map to an allowed API field, a synced `custom_fields` entry, or be omitted.

Product is treated as an ID-backed Freshdesk entity. The gateway never submits a top-level `product` key. If Product is supported and resolved from metadata, the payload uses `product_id`; if a required Product cannot be resolved to an ID, approval is blocked before Freshdesk is called.

## Rate Limits

Defaults:

- 5 Freshdesk writes per rolling hour
- 60 Freshdesk reads per rolling hour
- 5 ticket creations per rolling hour

Schema requests and Freshdesk searches count as reads. Every ticket created in a batch counts separately. The dashboard shows remaining writes.

## Emergency Stop

The large red **Emergency stop** button is always visible. Select it and type `STOP`.

You can activate it from Terminal even if the UI is closed:

```bash
touch STOP
```

While `STOP` exists, the gateway blocks Freshdesk reads, writes, searches, schema sync, and ticket workflows. Health, stop status, local settings/help, local audit viewing, and resume remain available.

To resume in the UI, select **Resume gateway** and type `RESUME`. From Terminal:

```bash
rm STOP
```

## Audit Logs

Open **Audit log** in the UI. Records stay in local SQLite at `data/freshdesk_gateway.db` by default. Audit summaries are redacted and intentionally avoid full payloads.

Nothing is written back into Freshdesk as an audit marker.

## Related Tickets

Open **Related tickets** and run the constrained search. The gateway uses `MY_NAME` and `MY_EMAIL` to look for requester, assigned-agent, and mention matches where your Freshdesk permissions allow. Selected result text can be summarised by your local model.

## Common Freshdesk Errors

- `401` or `403`: check your domain and personal API key, then confirm your Freshdesk account has permission for that resource.
- `404` during ticket forms sync: your Freshdesk plan or permissions may not expose ticket-form metadata. Other schema resources still cache normally.
- `429`: the local rolling-hour limit blocked the action. Wait for prior actions to age out or deliberately update the local limit in Settings.
- `423`: emergency stop is active. Resume only after checking why it was activated.
- Validation failure: sync the schema, complete the listed required fields, and remove suspected secrets.

## Optional AI Agent Integration

For the full MacBook gateway to OpenClaw/Mac Mini setup, see [docs/openclaw-integration.md](docs/openclaw-integration.md).

The gateway is provider-neutral. Any local AI agent can call the existing REST API at `http://127.0.0.1:8787/api`, or the private Tailscale Serve URL when the adapter runs on another Tailnet device.

Set `AGENT_API_TOKEN` to require a bearer token or `X-Agent-Token` header on `/api/v1` routes. This is intended for the Mac Mini to MacBook gateway path. The browser review page has an **Agent API token** field on the AI Agent API tab for local testing when this is enabled.

Safe endpoint families already exist for health, stop/resume, schema sync, directory lookups, drafting, validation, typed approval, selected batch creation, related-ticket listing, local-model summarisation, and audit viewing.

The review page is a real inbox, not a demo surface. It loads Freshdesk metadata, tries the last reviewed draft ID from browser storage, then falls back to `GET /api/v1/drafts?limit=1`. If no agent has submitted a draft, it shows an empty waiting state instead of creating example data.

Minimum OpenClaw-to-gateway flow:

1. Start the gateway on the MacBook and run Freshdesk schema sync from the UI.
2. Expose it privately with `scripts/tailnet-serve.sh` if OpenClaw is running on another Tailnet device.
3. Set `AGENT_API_TOKEN` in `.env` and give the same token to the OpenClaw caller.
4. OpenClaw fetches `GET /api/v1/metadata` to see current Freshdesk fields, groups, agents, forms, defaults, and schema-sync state.
5. OpenClaw submits a versioned draft to `POST /api/v1/drafts`.
6. You review and edit the draft in the AI Agent review page.
7. OpenClaw or the review UI can fetch `GET /api/v1/drafts/{id}/payload-preview` to inspect the exact Freshdesk payload that approval would send.
8. The gateway converts the approved ledger into the Freshdesk create/update/bulk payload and sends it only after the exact typed approval phrase.
9. OpenClaw can fetch `GET /api/v1/drafts/{id}` after approval to read the `feedback_payload`, including final fields, generated Freshdesk payload, changed fields, and created ticket ID.

For command-line testing from OpenClaw or another Tailnet machine:

```bash
export FRESHDESK_GATEWAY_URL="https://your-macbook-tailnet-url"
export AGENT_API_TOKEN="same-token-as-the-gateway"
scripts/openclaw-gateway.py metadata
scripts/openclaw-gateway.py list --limit 5
scripts/openclaw-gateway.py submit path/to/draft-envelope.json
scripts/openclaw-gateway.py get agd_123
```

The AI Agent handoff supports three modes:

- `create` creates one reviewed Freshdesk ticket after `CREATE`.
- `update` updates the existing `target_ticket_id` after `UPDATE`; default requester/contact values are not sent unless the agent or reviewer explicitly sets that field.
- `bulk_create` accepts one template plus row-level `bulk_items`, validates every row first, then creates the set only after `CREATE BULK`.

Do not add an arbitrary Freshdesk passthrough endpoint. Do not expose the API key. Keep the same validation, approval, rate-limit, audit, and emergency-stop path for every future interface.

## Security Considerations

- Keep `.env`, `STOP`, `data/`, and `.venv/` local.
- Keep the app bound to `127.0.0.1`. Use the private Tailscale Serve wrapper for Tailnet access instead of binding FastAPI to a public or LAN-facing interface.
- Treat your personal Freshdesk API key like a password.
- Review drafts for confidential information before approval.
- Keep the model server local unless you deliberately redesign the threat model.
- Back up or delete local SQLite records according to your organisation's data-handling policy.

## Limitations

- Freshdesk features vary by plan and account permissions.
- Required-field discovery depends on fields exposed by Freshdesk.
- Sensitive-data detection is intentionally conservative and may flag text for manual redaction.
- The quality of inferred operational steps depends on the selected local model. Review every assumption and leave unsupported specifics as `TBD`.
- Runtime settings updates are stored locally in SQLite. Domain, API key, identity, host, port, database path, and STOP-file path remain `.env` settings.
