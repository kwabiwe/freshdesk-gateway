# Freshdesk Gateway Architecture

## Runtime Flow

```text
Browser UI
  -> local FastAPI REST API
    -> emergency-stop guard
    -> deterministic sensitive-data validation
    -> rolling-hour rate limiter
    -> explicit typed draft approval workflow
      -> Freshdesk API client using backend-only Basic Auth

Browser UI
  -> local FastAPI REST API
    -> deterministic sensitive-data validation
      -> optional local model API

Tailnet device
  -> private Tailscale Serve HTTPS route
    -> optional Agent API bearer/service-token check
    -> loopback-only FastAPI REST API
```

The browser never receives the Freshdesk API key. Every future interface, including an optional AI Agent adapter, should use the same local REST API and safety controls.

## Backend Modules

| Module | Responsibility |
| --- | --- |
| `config.py` | `.env` loading and safe settings projection |
| `database.py` | SQLite connection handling and schema creation |
| `emergency.py` | `STOP` file activation, resume, and access guard |
| `rate_limit.py` | Rolling-hour read, write, and ticket-creation limits |
| `audit.py` | Local redacted SQLite audit records |
| `sensitive_data.py` | Mandatory regex-based secret detection and redaction |
| `freshdesk_client.py` | The only credentialed Freshdesk HTTP client |
| `schema_cache.py` | Local Freshdesk schema cache |
| `schema_service.py` | Permission-aware schema discovery |
| `schema_context.py` | Compact synced-schema projection for local change drafting |
| `validators.py` | Required-field and sensitive-data validation |
| `ticket_templates.py` | Legacy manual change fallback rendering |
| `draft_store.py` | Manual drafts, expiry, batch parsing, editing, and created state |
| `agent_draft_store.py` | Agent draft envelopes, update/create/bulk submit modes, row validation, revisions, and feedback payloads |
| `local_llm_client.py` | Optional local-only Ollama or OpenAI-compatible model calls |
| `ticket_defaults.py` | Editable identity and schema-aware defaults |
| `draft_assistant.py` | Schema-constrained local-model ticket suggestions |
| `change_models.py` | Authoritative structured change-document schema |
| `skill_registry.py` | Discovers manifest-backed local drafting skill folders |
| `change_renderer.py` | Escaped rich HTML Freshdesk Description renderer |
| `freshdesk_field_mapper.py` | Tenant-neutral deterministic mapping into discovered Freshdesk fields |
| `change_service.py` | Dedicated structured change generation, pre-save preview, and orchestration |
| `related_tickets.py` | Constrained identity-based Freshdesk ticket lookup |
| `main.py` | FastAPI composition, REST routes, and built-frontend serving |

## Frontend Structure

The React UI is deliberately compact:

```text
frontend/src/App.jsx
  -> application shell and always-visible emergency stop
  -> dashboard
  -> standard ticket composer
  -> change-style section editor and rich Description preview
  -> batch drafting and row editing
  -> schema viewer
  -> related-ticket search and local summary
  -> local audit viewer
  -> settings, connection tests, and directory search

frontend/src/styles.css
  -> Swiss-grid visual system
```

The design uses white and neutral surfaces, 1 px grid rules, Helvetica-style sans typography, and a single deliberate red accent for safety-critical emphasis.

## SQLite Data

SQLite stores:

- Safe runtime setting overrides
- Local audit summaries
- Rolling-hour rate events
- Freshdesk schema cache records
- Draft payloads, local structured change records, validation results, expiry, batch IDs, and created ticket IDs

The local `STOP` file is the emergency override even if SQLite is unavailable or the browser is closed.

## Local Skills

Versioned local drafting instructions live in `skills/<skill-id>/`. Each folder has a `skill.json` manifest, `SKILL.md`, `TEMPLATE.md`, and optional examples. Workflows select a registered skill by ID instead of binding the application to one global instruction file.

## Tailnet Access

FastAPI remains bound to `127.0.0.1`. `scripts/tailnet-serve.sh` publishes that loopback service through Tailscale Serve for private Tailnet access. The gateway must not use Tailscale Funnel or bind broadly to LAN interfaces by default.

When another machine, such as an OpenClaw orchestrator on a Mac Mini, calls the AI Agent API on the MacBook-hosted gateway, set `AGENT_API_TOKEN` and send it as either `Authorization: Bearer <token>` or `X-Agent-Token`.

The AI Agent review page is a draft inbox. It never manufactures example drafts for itself; it loads the latest submitted envelope from `GET /api/v1/drafts` and waits empty until OpenClaw posts a real draft. The gateway remains responsible for translating the reviewed semantic ledger into Freshdesk API fields at the approval boundary.

## Extension Rule

Do not add a generic Freshdesk passthrough route. New features should be narrow named operations that pass through stop checks, local limits, audit recording, deterministic validation where relevant, and explicit approval for every write.
