# Freshdesk Gateway User Guide

## What This App Does

Freshdesk Gateway is a local productivity tool for creating Freshdesk tickets safely and quickly. It supports standard tickets, structured change-request-style tickets, and batches of similar tickets.

A change-style ticket is still a normal Freshdesk ticket. This project does not assume Freshservice or ITIL change-management objects exist.

The browser UI talks only to the local FastAPI backend. The backend holds your personal API key, validates each draft, enforces rate limits, writes the local audit trail, and makes Freshdesk requests as your named Freshdesk account.

## What It Does Not Do

The MVP does not delete, close, merge, bulk-update, or reassign existing tickets. It does not send public replies. It does not add automation notes, AI markers, tags, or other visible Freshdesk metadata. It does not need OpenClaw or cloud AI.

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

Open **Change-style ticket** and paste your technical notes, relevant email text, and any prior plan. Select **Structure with local model**. The gateway uses its versioned local change-drafting skill to extract evidence, resolve relative dates against your local timezone, infer conservative operational detail, and flag assumptions for review.

Edit the generated sections directly. The rich Freshdesk Description preview updates from the structured record through the backend renderer. The template covers:

- Planned change date, customer, and environment
- Configuration items
- Background of change
- Change description
- Implementation steps
- Rollback branches
- Pre-change, in-change, and post-change verification
- Risk and impact
- Expected outcome
- Success criteria
- Dependencies

Unsupported specifics remain `TBD` instead of being invented. Inferred Freshdesk dropdown values remain editable. Save the draft only after reviewing the assumptions and final preview. The server re-renders the Description when saving, then validates the exact payload before approval.

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

## Optional OpenClaw Integration Later

OpenClaw is not required. A later local-only adapter can call the existing REST API at `http://127.0.0.1:8787/api`, or the private Tailscale Serve URL when the adapter runs on another Tailnet device.

Safe endpoint families already exist for health, stop/resume, schema sync, directory lookups, drafting, validation, approval, selected batch creation, related-ticket listing, local-model summarisation, and audit viewing.

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
