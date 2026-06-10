from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.audit import AuditLog
from app.change_models import ChangeDocument
from app.change_renderer import render_change_html
from app.change_service import ChangeService
from app.config import Settings, load_settings
from app.database import Database
from app.draft_assistant import DraftAssistantService
from app.draft_store import DraftStore
from app.emergency import EmergencyStop
from app.freshdesk_field_mapper import FreshdeskFieldMapper
from app.freshdesk_client import FreshdeskClient
from app.main import create_app
from app.local_llm_client import LocalLLMClient
from app.ollama_client import OllamaClient
from app.rate_limit import RateLimiter
from app.schema_cache import SchemaCache
from app.schema_context import SchemaContextBuilder
from app.schema_service import SchemaService
from app.sensitive_data import detect_secrets
from app.skill_registry import SkillRegistry
from app.ticket_defaults import TicketDefaultsService
from app.validators import ALLOWED_TICKET_FIELDS, TicketValidator


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        freshdesk_domain="example",
        freshdesk_api_key="personal-key",
        ollama_url="http://127.0.0.1:11434",
        ollama_model="llama3.1",
        local_llm_provider="auto",
        ollama_generation_timeout_seconds=300,
        max_writes_per_hour=5,
        max_reads_per_hour=60,
        max_ticket_creations_per_hour=5,
        my_name="Test User",
        my_email="test@example.com",
        app_host="127.0.0.1",
        app_port=8787,
        draft_expiry_minutes=30,
        database_path=tmp_path / "gateway.db",
        stop_file=tmp_path / "STOP",
    )


@pytest.fixture
def core(settings: Settings):
    db = Database(settings.database_path)
    audit = AuditLog(db)
    emergency = EmergencyStop(settings.stop_file, audit)
    limiter = RateLimiter(db, lambda: settings, audit)
    schema = SchemaCache(db, audit)
    drafts = DraftStore(db, lambda: settings, TicketValidator(schema), audit)
    return db, audit, emergency, limiter, schema, drafts


def test_config_loading(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FRESHDESK_DOMAIN", "acme")
    monkeypatch.setenv("FRESHDESK_API_KEY", "secret")
    monkeypatch.setenv("MAX_WRITES_PER_HOUR", "7")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "config.db"))
    loaded = load_settings(tmp_path / "missing.env")
    assert loaded.freshdesk_base_url == "https://acme.freshdesk.com"
    assert loaded.max_writes_per_hour == 7
    assert "freshdesk_api_key" not in loaded.safe_dict()


def test_freshdesk_auth_header():
    expected = base64.b64encode(b"abc123:X").decode("ascii")
    assert FreshdeskClient.build_auth_header("abc123") == f"Basic {expected}"


def test_emergency_stop_active_and_resume(core):
    _, _, emergency, _, _, _ = core
    assert emergency.is_active() is False
    emergency.activate("STOP")
    assert emergency.is_active() is True
    with pytest.raises(HTTPException) as exc:
        emergency.require_clear()
    assert exc.value.status_code == 423
    emergency.resume("RESUME")
    assert emergency.is_active() is False


def test_rate_limit_blocks_after_maximum(core, settings: Settings):
    _, _, _, limiter, _, _ = core
    limited = replace(settings, max_writes_per_hour=2, max_ticket_creations_per_hour=2)
    limiter.settings_provider = lambda: limited
    limiter.record("write", "ticket_create")
    limiter.record("write", "ticket_create")
    with pytest.raises(HTTPException) as exc:
        limiter.ensure_available("write", "ticket_create")
    assert exc.value.status_code == 429


def test_draft_creation_validation_and_expiry(core):
    db, _, _, _, schema, drafts = core
    schema.put("ticket_fields", [{"name": "group", "label": "Group", "type": "default_group", "required_for_agents": True}])
    draft = drafts.create({"subject": "Subject", "description": "Body", "requester_email": "requester@example.com"})
    assert draft["validation_status"] == "invalid"
    assert draft["validation_result"]["missing_fields"][0]["label"] == "Group"
    drafts.update(draft["draft_id"], {"group_id": 123})
    assert drafts.get(draft["draft_id"])["validation_status"] == "valid"
    with db.connect() as conn:
        conn.execute(
            "UPDATE drafts SET expires_at = ? WHERE draft_id = ?",
            ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), draft["draft_id"]),
        )
    assert drafts.get(draft["draft_id"])["expired"] is True


def test_ticket_validator_rejects_unsupported_top_level_fields(core):
    _, _, _, _, schema, _ = core
    result = TicketValidator(schema).validate(
        {
            "subject": "Subject",
            "description": "Body",
            "email": "requester@example.com",
            "product": "A24 Support",
            "contact": "Ada",
            "agent": "Engineer",
            "group": "L3 Engineering",
            "form": "Change Request",
        }
    )

    assert result["valid"] is False
    assert result["invalid_fields"] == ["agent", "contact", "form", "group", "product"]


def test_ticket_validator_rejects_malformed_tags(core):
    _, _, _, _, schema, _ = core
    result = TicketValidator(schema).validate(
        {
            "subject": "Subject",
            "description": "Body",
            "email": "requester@example.com",
            "tags": "change,network",
        }
    )

    assert result["valid"] is False
    assert result["invalid_tags"] == ["change,network"]


def test_ticket_validator_rejects_company_without_resolved_requester(core):
    _, _, _, _, schema, _ = core
    schema.put("companies", [{"id": 7, "name": "Example Limited", "domains": ["example.com"]}])
    result = TicketValidator(schema).validate(
        {
            "subject": "Subject",
            "description": "Body",
            "email": "requester@other.example",
            "company_id": 7,
        }
    )

    assert result["valid"] is False
    assert result["invalid_company_association"][0]["field"] == "company_id"
    assert result["invalid_company_association"][0]["company_name"] == "Example Limited"
    assert "resolved to a Freshdesk contact" in result["invalid_company_association"][0]["message"]


def test_ticket_validator_accepts_requester_id_for_required_requester(core):
    _, _, _, _, schema, _ = core
    schema.put(
        "ticket_fields",
        [{"name": "requester", "label": "Search a requester", "type": "default_requester", "required_for_agents": True}],
    )
    result = TicketValidator(schema).validate(
        {"subject": "Subject", "description": "Body", "requester_id": 123, "priority": 1, "status": 2, "source": 2}
    )

    assert result["valid"] is True
    assert result["missing_fields"] == []


def test_ticket_validator_rejects_unknown_custom_fields(core):
    _, _, _, _, schema, _ = core
    schema.put("ticket_fields", [{"name": "cf_change_state", "label": "Change State"}])
    result = TicketValidator(schema).validate(
        {
            "subject": "Subject",
            "description": "Body",
            "email": "requester@example.com",
            "custom_fields": {"cf_unknown": "value"},
        }
    )

    assert result["valid"] is False
    assert result["invalid_custom_fields"] == ["cf_unknown"]


def test_ticket_validator_rejects_invalid_custom_dropdown_values(core):
    _, _, _, _, schema, _ = core
    schema.put(
        "ticket_fields",
        [{"name": "cf_change_state", "label": "Change State", "choices": ["Pending approval", "Approved"]}],
    )
    result = TicketValidator(schema).validate(
        {
            "subject": "Subject",
            "description": "Body",
            "email": "requester@example.com",
            "custom_fields": {"cf_change_state": "Banana"},
        }
    )

    assert result["valid"] is False
    assert result["invalid_custom_field_values"][0]["name"] == "cf_change_state"
    assert result["invalid_custom_field_values"][0]["allowed_values"] == ["Pending approval", "Approved"]


@pytest.mark.parametrize(
    "text",
    [
        "password=hunter2",
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456",
        "-----BEGIN PRIVATE KEY-----",
        "postgres://user:supersecret@localhost/db",
        "api_key=abcdefghijklmno123456",
    ],
)
def test_sensitive_data_detection(text: str):
    assert detect_secrets(text)


def test_batch_csv_and_json_parsing():
    csv_rows = DraftStore.parse_rows("name,email\nAda,ada@example.com\nLin,lin@example.com")
    json_rows = DraftStore.parse_rows('[{"name":"Ada","email":"ada@example.com"}]')
    assert csv_rows[0]["name"] == "Ada"
    assert json_rows[0]["email"] == "ada@example.com"


def test_audit_logging_redacts_secrets(core):
    _, audit, _, _, _, _ = core
    audit.record("test", request_summary="password=hunter2")
    row = audit.list()[0]
    assert "hunter2" not in row["request_summary"]
    assert "[REDACTED]" in row["request_summary"]


def test_ollama_unavailable_fallback(core, settings: Settings):
    _, audit, _, _, _, _ = core
    transport = httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    ollama = OllamaClient(lambda: settings, audit, transport=transport)
    assert ollama.test_connection()["connected"] is False
    with pytest.raises(HTTPException) as exc:
        ollama.rewrite("Plain notes")
    assert exc.value.status_code == 503


def test_ollama_timeout_has_accurate_message(core, settings: Settings):
    _, audit, _, _, _, _ = core

    def timeout_handler(request: httpx.Request):
        raise httpx.ReadTimeout("timed out", request=request)

    ollama = OllamaClient(lambda: settings, audit, transport=httpx.MockTransport(timeout_handler))
    with pytest.raises(HTTPException) as exc:
        ollama.rewrite("Plain notes")
    assert exc.value.status_code == 504
    assert "exceeded 300 seconds" in exc.value.detail


def test_local_llm_discovers_ollama_models_and_generates(core, settings: Settings):
    _, audit, _, _, _, _ = core

    def handler(request: httpx.Request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "gemma4:31b"}, {"name": "mistral-small3.1:24b"}]}, request=request)
        payload = json.loads(request.content)
        assert request.url.path == "/api/generate"
        assert payload["model"] == "llama3.1"
        return httpx.Response(200, json={"response": "Rewritten body"}, request=request)

    local_llm = LocalLLMClient(lambda: settings, audit, transport=httpx.MockTransport(handler))
    result = local_llm.test_connection()
    assert result["provider"] == "ollama"
    assert result["available_models"] == ["gemma4:31b", "mistral-small3.1:24b"]
    assert local_llm.rewrite("Plain notes") == "Rewritten body"


def test_local_llm_supports_openai_compatible_server(core, settings: Settings):
    _, audit, _, _, _, _ = core
    compatible = replace(settings, ollama_url="http://127.0.0.1:1234", local_llm_provider="openai-compatible")

    def handler(request: httpx.Request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "local-model"}]}, request=request)
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": "Local response"}}]}, request=request)

    local_llm = LocalLLMClient(lambda: compatible, audit, transport=httpx.MockTransport(handler))
    assert local_llm.list_models()["models"] == ["local-model"]
    assert local_llm.rewrite("Plain notes") == "Local response"


def test_local_llm_repairs_invalid_json_once(core, settings: Settings):
    _, audit, _, _, _, _ = core
    responses = iter(["not-json", '{"change_document":{"title":"Repaired"}}'])

    def handler(request: httpx.Request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.1"}]}, request=request)
        return httpx.Response(200, json={"response": next(responses)}, request=request)

    local_llm = LocalLLMClient(lambda: settings, audit, transport=httpx.MockTransport(handler))
    assert local_llm.generate_json("Create JSON", "Plain notes")["change_document"]["title"] == "Repaired"


def test_openai_compatible_json_mode_falls_back_when_unsupported(core, settings: Settings):
    _, audit, _, _, _, _ = core
    compatible = replace(settings, ollama_url="http://127.0.0.1:1234", local_llm_provider="openai-compatible")
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "local-model"}]}, request=request)
        payload = json.loads(request.content)
        payloads.append(payload)
        if "response_format" in payload:
            return httpx.Response(400, json={"error": "unsupported"}, request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"title":"Local JSON"}'}}]}, request=request)

    local_llm = LocalLLMClient(lambda: compatible, audit, transport=httpx.MockTransport(handler))
    assert local_llm.generate_json("Create JSON", "Plain notes") == {"title": "Local JSON"}
    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in payloads[1]


def test_freshdesk_client_constructs_ticket_request(core, settings: Settings):
    _, audit, emergency, limiter, _, _ = core
    captured: dict[str, object] = {}

    def handler(request: httpx.Request):
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": 42}, request=request)

    client = FreshdeskClient(lambda: settings, emergency, limiter, audit, transport=httpx.MockTransport(handler))
    result = client.create_ticket({"subject": "Safe ticket"})
    assert result["id"] == 42
    assert captured["url"] == "https://example.freshdesk.com/api/v2/tickets"
    assert captured["authorization"] == FreshdeskClient.build_auth_header("personal-key")
    assert captured["body"] == {"subject": "Safe ticket"}


def test_freshdesk_ticket_forms_uses_documented_hyphenated_path(core, settings: Settings):
    _, audit, emergency, limiter, _, _ = core
    captured: dict[str, object] = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json=[], request=request)

    client = FreshdeskClient(lambda: settings, emergency, limiter, audit, transport=httpx.MockTransport(handler))
    client.ticket_forms()
    assert captured["url"] == "https://example.freshdesk.com/api/v2/ticket-forms"


def test_freshdesk_contact_and_company_search_use_autocomplete_endpoints(core, settings: Settings):
    _, audit, emergency, limiter, _, _ = core
    urls: list[str] = []

    def handler(request: httpx.Request):
        urls.append(str(request.url))
        payload = {"companies": [{"id": 7, "name": "Acme"}]} if "companies" in request.url.path else [{"id": 8, "name": "Ada"}]
        return httpx.Response(200, json=payload, request=request)

    client = FreshdeskClient(lambda: settings, emergency, limiter, audit, transport=httpx.MockTransport(handler))
    assert client.search_contacts("Ada")[0]["name"] == "Ada"
    assert client.search_companies("Acme")[0]["name"] == "Acme"
    assert urls == [
        "https://example.freshdesk.com/api/v2/contacts/autocomplete?term=Ada",
        "https://example.freshdesk.com/api/v2/contacts/8",
        "https://example.freshdesk.com/api/v2/companies/autocomplete?name=Acme",
    ]


def test_freshdesk_email_contact_search_uses_exact_email_filter(core, settings: Settings):
    _, audit, emergency, limiter, _, _ = core
    captured: dict[str, str] = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        return httpx.Response(200, json=[{"id": 8, "email": "ada@example.com"}], request=request)

    client = FreshdeskClient(lambda: settings, emergency, limiter, audit, transport=httpx.MockTransport(handler))
    assert client.search_contacts("ada@example.com")[0]["id"] == 8
    assert captured["url"] == "https://example.freshdesk.com/api/v2/contacts?email=ada%40example.com"


def test_schema_sync_falls_back_to_ticket_field_group_and_agent_choices(core):
    _, audit, _, _, schema, _ = core

    class StubFreshdesk:
        def ticket_fields(self):
            return [
                {"name": "group", "choices": {"L1 Operations": 10}},
                {"name": "agent", "choices": {"Test User": 20}},
            ]

        def groups(self):
            raise HTTPException(status_code=403, detail="forbidden")

        def agents(self):
            raise HTTPException(status_code=403, detail="forbidden")

        def companies(self):
            return []

        def ticket_forms(self):
            raise HTTPException(status_code=404, detail="missing")

    result = SchemaService(StubFreshdesk(), schema, audit).sync()
    assert result["resources"]["groups"]["status"] == "fallback"
    assert schema.get("groups") == [{"id": 10, "name": "L1 Operations", "source": "ticket_fields"}]
    assert result["resources"]["agents"]["status"] == "fallback"
    assert schema.get("agents")[0]["contact"]["name"] == "Test User"
    assert result["resources"]["ticket_forms"]["error"].startswith("Ticket forms are not exposed")


def test_ticket_defaults_use_configured_identity_and_cached_schema(core, settings: Settings):
    _, _, _, _, schema, _ = core
    schema.put(
        "ticket_fields",
        [
            {"name": "cf_requested_by"},
            {"name": "cf_change_owner"},
            {"name": "cf_form2", "choices": ["Change Request", "Incident"]},
            {"name": "cf_change_type", "choices": ["Standard", "Normal", "Emmergency"]},
            {"name": "cf_change_state", "choices": ["Pending approval", "Approved"]},
            {"name": "cf_customer", "choices": ["Example"]},
        ],
    )
    schema.put("companies", [{"id": 7, "name": "Example Limited", "domains": ["example.com"]}])
    schema.put("agents", [{"id": 8, "contact": {"name": "Test User", "email": "test@example.com"}}])
    schema.put("groups", [{"id": 9, "name": "L3 Engineering"}])
    defaults = TicketDefaultsService(schema, lambda: settings).defaults("change")
    assert defaults["requester_email"] == "test@example.com"
    assert defaults["company_id"] is None
    assert defaults["identity_company_id"] == 7
    assert defaults["group_id"] == 9
    assert defaults["identity"]["agent_id"] == 8
    assert defaults["custom_fields"] == {
        "cf_requested_by": "Test User",
        "cf_customer": "Example",
        "cf_change_owner": "Test User",
        "cf_form2": "Change Request",
        "cf_change_type": "Normal",
        "cf_change_state": "Pending approval",
    }


def test_draft_assistant_accepts_only_cached_schema_values(core, settings: Settings):
    _, _, _, _, schema, _ = core
    schema.put("ticket_fields", [{"name": "cf_business_impact", "choices": ["Minor", "Moderate"]}])
    schema.put("groups", [{"id": 5, "name": "Operations"}])
    schema.put("companies", [{"id": 7, "name": "Example Limited", "domains": ["example.com"]}])

    class StubLocalLLM:
        def generate_json(self, prompt, source_text):
            return {
                "subject": "Reviewed subject",
                "description": "Reviewed description",
                "priority": 2,
                "group_name": "Operations",
                "company_name": "Example Limited",
                "custom_fields": {"cf_business_impact": "Minor", "cf_unknown": "ignored"},
                "assumptions": ["Business impact is minor."],
            }

    defaults = TicketDefaultsService(schema, lambda: settings)
    result = DraftAssistantService(StubLocalLLM(), schema, defaults).suggest("generic", "Notes")
    assert result["suggestions"]["group_id"] == 5
    assert "company_id" not in result["suggestions"]
    assert result["suggestions"]["custom_fields"] == {"cf_business_impact": "Minor"}
    assert result["assumptions"] == ["Business impact is minor."]


def test_change_assistant_defaults_minor_impact_and_rejects_undiscovered_type(core, settings: Settings):
    _, _, _, _, schema, _ = core
    schema.put("ticket_fields", [{"name": "cf_chg_business_impact", "label": "CHG Business Impact", "choices": ["Moderate", "Significant", "Minor"]}])

    class StubLocalLLM:
        def generate_json(self, prompt, source_text):
            return {"subject": "Change", "description": "Risk: Low", "type": "Request", "custom_fields": {}, "assumptions": []}

    defaults = TicketDefaultsService(schema, lambda: settings)
    result = DraftAssistantService(StubLocalLLM(), schema, defaults).suggest("change", "Low expected disruption.")
    assert "type" not in result["suggestions"]
    assert result["suggestions"]["custom_fields"] == {"cf_chg_business_impact": "Minor"}
    assert result["assumptions"] == ["Business impact fields default to Minor because the notes describe low or minimal disruption."]


def test_change_assistant_populates_description_background_group_and_normal_type(core, settings: Settings):
    _, _, _, _, schema, _ = core
    schema.put(
        "ticket_fields",
        [
            {"name": "cf_background_for_the_change", "label": "Background for the Change"},
            {"name": "cf_change_type", "label": "Change Type", "choices": ["Standard", "Normal", "Emmergency"]},
        ],
    )
    schema.put("groups", [{"id": 9, "name": "L3 Engineering"}, {"id": 10, "name": "L2 Operations"}])

    class StubLocalLLM:
        def generate_json(self, prompt, source_text):
            return {
                "subject": "Firewall monitoring change",
                "description": "",
                "custom_fields": {"cf_change_type": "Standard"},
                "group_name": "L2 Operations",
                "assumptions": [],
            }

    defaults = TicketDefaultsService(schema, lambda: settings)
    result = DraftAssistantService(StubLocalLLM(), schema, defaults).suggest("change", "Allow restricted SNMP monitoring traffic.")
    assert result["suggestions"]["group_id"] == 9
    assert "Reason for change:" in result["suggestions"]["description"]
    assert result["suggestions"]["custom_fields"] == {
        "cf_change_type": "Normal",
        "cf_background_for_the_change": "Allow restricted SNMP monitoring traffic.",
    }
    assert result["assumptions"] == ["Change type defaults to Normal unless the notes explicitly identify another change type."]


def change_schema(schema: SchemaCache):
    schema.put(
        "ticket_fields",
        [
            {"name": "cf_background_for_the_change", "label": "Background for the Change"},
            {"name": "cf_form2", "choices": ["Change Request"]},
            {"name": "cf_type", "choices": ["Change"]},
            {"name": "cf_change_type", "choices": ["Standard", "Normal", "Emmergency"]},
            {"name": "cf_change_state", "choices": ["Pending approval", "Approved"]},
            {"name": "cf_approval_state", "choices": ["Not Yet Requested"]},
            {"name": "cf_change_owner"},
            {"name": "cf_requested_by"},
            {"name": "cf_customer967575", "choices": ["A24", "Wise_UK"]},
            {"name": "cf_chg_business_impact", "choices": ["Minor", "Moderate", "Significant"]},
            {"name": "cf_change_catergory", "choices": ["Application", "Network"]},
            {"name": "cf_risk", "label": "Risk", "choices": ["Low", "Medium", "High"]},
        ],
    )
    schema.put("groups", [{"id": 9, "name": "L3 Engineering"}])


def full_change_request_schema(schema: SchemaCache):
    schema.put(
        "ticket_fields",
        [
            {"name": "product", "label": "Product", "type": "default_product", "choices": {"A24 Support": 205000014435}},
            {"name": "requester", "label": "Contact", "type": "default_requester", "required_for_agents": True},
            {"name": "subject", "label": "Subject", "type": "default_subject", "required_for_agents": True},
            {"name": "cf_form2", "label": "Form", "type": "custom_dropdown", "choices": ["Change Request"]},
            {"name": "cf_background_for_the_change", "label": "Background for the Change", "type": "custom_paragraph"},
            {"name": "cf_change_type", "label": "Change Type", "type": "custom_dropdown", "choices": ["Standard", "Normal", "Emmergency"]},
            {"name": "cf_requested_by", "label": "Requested By", "type": "custom_text"},
            {"name": "cf_change_owner", "label": "Change owner", "type": "custom_text", "required_for_agents": True},
            {"name": "cf_change_catergory", "label": "Change Category", "type": "custom_dropdown", "choices": ["Application", "Network"]},
            {"name": "cf_chg_business_impact", "label": "CHG Business Impact", "type": "custom_dropdown", "choices": ["Minor", "Moderate", "Significant"]},
            {"name": "cf_change_state", "label": "Change State", "type": "custom_dropdown", "required_for_agents": True, "choices": ["In progress", "Pending approval", "On-Hold", "Approved", "Rejected"]},
            {"name": "cf_approval_state", "label": "Approval State", "type": "custom_dropdown", "choices": ["Not Yet Requested", "Requested", "Approved", "Rejected"]},
            {"name": "cf_type", "label": "Ticket Type", "type": "nested_field", "choices": {"Change": {}, "Incident": {}}},
            {"name": "status", "label": "Status", "type": "default_status", "required_for_agents": True, "choices": {"2": ["Open", "Open"], "3": ["Pending", "Pending"]}},
            {"name": "cf_business_impact723800", "label": "Business Impact", "type": "custom_dropdown", "choices": ["Extensive", "Significant", "Moderate", "Minor"]},
            {"name": "group", "label": "Group", "type": "default_group"},
            {"name": "agent", "label": "Agent", "type": "default_agent"},
            {"name": "priority", "label": "Priority", "type": "default_priority", "required_for_agents": True, "choices": {"Low": 1, "Medium": 2, "High": 3, "Urgent": 4}},
            {"name": "description", "label": "Description", "type": "default_description", "required_for_agents": True},
            {"name": "cf_customer967575", "label": "Customer", "type": "custom_dropdown", "required_for_agents": True, "choices": ["Example", "A24"]},
            {"name": "cf_reminder_date", "label": "Reminder Date", "type": "custom_date"},
        ],
    )


def wise_change_document():
    return {
        "title": "Change Request - Wise UK - HSM upgrade and mTLS rollout",
        "planned_change_date": "next Tuesday",
        "customer": "Wise UK",
        "environment": "Production HSM environment",
        "configuration_items": [
            {"name": "wiseld5-hsm-1", "item_type": "HSM", "site_location": "LD5", "purpose": "Firmware upgrade", "version": "Target 2.3a"},
            {"name": "wiseld5-hsm-2", "item_type": "HSM", "site_location": "LD5", "purpose": "Firmware upgrade", "version": "Target 2.3a"},
            {"name": "wiseld8-hsm-1", "item_type": "HSM", "site_location": "LD8", "purpose": "Firmware upgrade", "version": "Target 2.3a"},
            {"name": "wiseld8-hsm-2", "item_type": "HSM", "site_location": "LD8", "purpose": "Firmware upgrade", "version": "Target 2.3a"},
            {"name": "Stargate", "item_type": "Application", "site_location": "Production", "purpose": "Validate commands against upgraded HSMs"},
        ],
        "background": "Upgrade firmware to version 2.3a to resolve the mTLS-related bug before rollout.",
        "change_description": "Upgrade the four HSMs to 2.3a and roll out mTLS using a phased LD5-first approach.",
        "implementation_steps": [
            "Verify the software image against the supplied MD5 hashes.",
            "Upgrade one LD5 HSM and add it to the separate validation load balancer.",
            "Validate commands using Stargate before upgrading the second LD5 HSM.",
            "Add known-good upgraded HSMs to the production pool, then upgrade the LD8 HSMs.",
        ],
        "rollback_branches": [
            {"scenario": "HSM validation fails", "steps": ["Remove the affected HSM from the pool and restore known-good routing."]},
            {"scenario": "mTLS validation fails", "steps": ["Revert certificate changes and keep traffic on known-good HSMs."]},
        ],
        "verification": {
            "pre_change": ["Verify image MD5 hashes and confirm certificates are available."],
            "in_change": ["Validate commands through Stargate after each HSM upgrade."],
            "post_change": ["Confirm all four HSMs process production-scenario commands using mTLS."],
        },
        "risk_and_impact": "Moderate operational risk managed through phased upgrades and isolated validation.",
        "expected_outcome": "All four HSMs run 2.3a with mTLS validated.",
        "success_criteria": ["All four HSMs are upgraded.", "mTLS is validated.", "Production traffic uses the expected pool."],
        "dependencies": ["Firmware image 2.3a", "MD5 hashes", "Stargate", "Validation load balancer"],
        "assumptions": [],
        "freshdesk_fields": {"cf_change_catergory": "Application"},
    }


def test_change_skill_wise_uk_fixture_maps_full_document(core, settings: Settings):
    _, _, _, _, schema, _ = core
    change_schema(schema)
    source = (Path(__file__).parent / "fixtures" / "wise_uk_hsm_notes.txt").read_text()

    class StubLocalLLM:
        def generate_json(self, prompt, source_text, max_tokens=0):
            assert "Return one JSON object only" in prompt
            assert "SOURCE NOTES:" in prompt
            assert source_text == source
            return wise_change_document()

    result = ChangeService(
        StubLocalLLM(),
        schema,
        TicketDefaultsService(schema, lambda: settings),
        now_provider=lambda: datetime(2026, 5, 31, 9, tzinfo=ZoneInfo("Europe/London")),
    ).suggest(source)
    document = result["change_document"]
    custom = result["suggestions"]["custom_fields"]
    assert document["planned_change_date"] == "Tuesday 2 June 2026"
    assert {item["name"] for item in document["configuration_items"] if item["item_type"] == "HSM"} == {
        "wiseld5-hsm-1",
        "wiseld5-hsm-2",
        "wiseld8-hsm-1",
        "wiseld8-hsm-2",
    }
    assert "Stargate" in {item["name"] for item in document["configuration_items"]}
    assert custom["cf_customer967575"] == "Wise_UK"
    assert custom["cf_change_type"] == "Normal"
    assert custom["cf_change_state"] == "Pending approval"
    assert custom["cf_approval_state"] == "Not Yet Requested"
    assert custom["cf_risk"] == "High"
    assert result["suggestions"]["group_id"] == 9
    assert "2.3a" in result["rendered_description"]
    assert "mTLS" in result["rendered_description"]
    assert "Tuesday 2 June 2026" in result["assumptions"][0]
    assert result["skill_id"] == "change_management_drafting"
    assert result["skill_version"] == "2.1.0"


def test_schema_context_includes_required_and_change_related_fields(core):
    _, _, _, _, schema, _ = core
    schema.put(
        "ticket_fields",
        [
            {"name": "subject", "label": "Subject", "type": "default_subject"},
            {
                "name": "cf_rollback_plan",
                "label": "Rollback Plan",
                "type": "custom_paragraph",
                "required_for_agents": True,
            },
        ],
    )
    context = SchemaContextBuilder(schema).build()
    assert context["required_fields"][0]["name"] == "cf_rollback_plan"
    assert context["required_fields"][0]["required_for_agents"] is True
    assert "cf_rollback_plan" in {field["name"] for field in context["change_related_fields"]}


def test_dynamic_custom_field_mapper_populates_rollback_plan(core, settings: Settings):
    _, _, _, _, schema, _ = core
    schema.put("ticket_fields", [{"name": "cf_backout", "label": "Rollback Plan", "type": "custom_paragraph"}])
    document = ChangeDocument.model_validate(
        {"rollback_branches": [{"scenario": "Validation fails", "steps": ["Remove the firewall rule.", "Confirm known-good path."]}]}
    )
    mapped = FreshdeskFieldMapper(SchemaContextBuilder(schema).build()).map(
        document,
        render_change_html(document),
        TicketDefaultsService(schema, lambda: settings).defaults("change"),
    )
    assert "Remove the firewall rule." in mapped.suggestions["custom_fields"]["cf_backout"]
    assert "Mapped rollback to Rollback Plan" in mapped.notes[0]


def test_dynamic_mapper_clears_conflicting_customer_default_but_keeps_approval_default(core):
    _, _, _, _, schema, _ = core
    schema.put(
        "ticket_fields",
        [
            {"name": "cf_customer", "label": "Customer", "choices": ["A24", "Wise_UK"], "required_for_agents": True},
            {"name": "cf_approval_state", "label": "Approval State", "choices": ["Not Yet Requested"]},
        ],
    )
    document = ChangeDocument(customer="Acme Inc")
    mapped = FreshdeskFieldMapper(SchemaContextBuilder(schema).build()).map(
        document,
        render_change_html(document),
        {"custom_fields": {"cf_customer": "A24", "cf_approval_state": "Not Yet Requested"}},
    )
    assert "cf_customer" not in mapped.suggestions["custom_fields"]
    assert mapped.suggestions["custom_fields"]["cf_approval_state"] == "Not Yet Requested"
    assert mapped.low_confidence_fields == ["cf_customer"]
    assert mapped.open_questions == ["Select an allowed value for required dropdown Customer."]


def test_sparse_firewall_change_preserves_engineering_detail_and_flags_window(core, settings: Settings):
    _, _, _, _, schema, _ = core
    change_schema(schema)
    notes = (
        "Need a change for Acme. Allow new SFTP traffic from 10.10.50.25 to partner "
        "203.0.113.15 on TCP 22. Production firewall. Doing it Thursday night. "
        "Rollback is remove rule. Verify with test connection."
    )

    class StubLocalLLM:
        def generate_json(self, prompt, source_text, max_tokens=0):
            return {
                "title": "Change Request - Acme - Allow production SFTP traffic",
                "customer": "Acme",
                "environment": "Production firewall",
                "background": "Allow partner SFTP connectivity.",
                "description": "Allow 10.10.50.25 to reach 203.0.113.15 on TCP 22 through the production firewall.",
                "implementation_steps": ["Add the restricted firewall rule for 10.10.50.25 to 203.0.113.15 on TCP 22."],
                "rollback_plan": ["Remove the newly added firewall rule."],
                "verification": {"post_change": ["Run a test connection and confirm the firewall logs show the expected TCP 22 flow."]},
            }

    result = ChangeService(
        StubLocalLLM(),
        schema,
        TicketDefaultsService(schema, lambda: settings),
        now_provider=lambda: datetime(2026, 5, 31, 9, tzinfo=ZoneInfo("Europe/London")),
    ).suggest(notes)
    rendered = result["rendered_description"]
    assert "10.10.50.25" in rendered
    assert "203.0.113.15" in rendered
    assert "TCP 22" in rendered
    assert "Remove the newly added firewall rule." in rendered
    assert "firewall logs" in rendered
    assert "Thursday 4 June 2026" in result["assumptions"][0]
    assert any("exact start time" in question for question in result["open_questions"])


def test_suggest_change_previews_missing_required_field_before_save(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    services.schema_cache.put(
        "ticket_fields",
        [{"name": "cf_implementation_owner", "label": "Implementation Owner", "type": "custom_text", "required_for_agents": True}],
    )

    class StubLocalLLM:
        def generate_json(self, prompt, source_text, max_tokens=0):
            return {"title": "Change request", "background": "Background", "description": "Description"}

    services.changes.local_llm = StubLocalLLM()
    result = TestClient(app).post("/api/local-llm/suggest-change", json={"text": "Update routing policy."})
    assert result.status_code == 200
    body = result.json()
    assert body["validation_preview"]["valid"] is False
    assert body["missing_required_fields"][0]["name"] == "cf_implementation_owner"


def test_skill_registry_discovers_manifest_backed_change_skill():
    registry = SkillRegistry()
    skills = registry.list()
    assert skills == [
        {
            "id": "change_management_drafting",
            "name": "Change Management Drafting",
            "version": "2.1.0",
            "summary": "Convert sparse operational notes and pasted evidence into a complete, approval-ready change record.",
            "sections": [
                "Title",
                "Change classification",
                "Planned window",
                "Customer / environment",
                "Configuration items",
                "Background",
                "Change description",
                "Implementation steps",
                "Rollback plan",
                "Verification plan",
                "Risk and impact",
                "Risks and mitigations",
                "Communication plan",
                "Expected outcome",
                "Success criteria",
                "Dependencies",
                "Assumptions requiring review",
                "Open questions for local review",
            ],
        }
    ]
    skill = registry.get("change_management_drafting")
    assert "Use clear British English." in skill.instructions()
    assert skill.overview()["version"] == "2.1.0"


def test_configuration_item_accepts_improved_skill_field_aliases():
    document = ChangeDocument.model_validate(
        {
            "configuration_items": [
                {
                    "name": "wiseld5-hsm-1",
                    "type": "HSM",
                    "site_or_environment": "LD5 / Production",
                    "role_in_change": "Target firmware upgrade",
                    "version": "2.3a",
                }
            ]
        }
    )
    item = document.configuration_items[0]
    assert item.item_type == "HSM"
    assert item.site_location == "LD5 / Production"
    assert item.purpose == "Target firmware upgrade"
    assert item.version == "2.3a"


def test_change_renderer_escapes_unsafe_text_and_omits_assumptions():
    html = render_change_html(ChangeDocument(title="<script>alert(1)</script>", background="Safe & controlled", assumptions=["Do not render me"]))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Safe &amp; controlled" in html
    assert "Do not render me" not in html


def test_change_service_sparse_and_malformed_sections_fall_back_safely(core, settings: Settings):
    _, _, _, _, schema, _ = core
    change_schema(schema)

    class StubLocalLLM:
        def generate_json(self, prompt, source_text, max_tokens=0):
            return {"title": None, "background": None, "change_description": None, "implementation_steps": None, "rollback_branches": ["Remove the change."], "verification": ["Confirm service health."]}

    result = ChangeService(StubLocalLLM(), schema, TicketDefaultsService(schema, lambda: settings)).suggest("Update firewall policy for monitoring.")
    document = result["change_document"]
    assert document["background"] == "Update firewall policy for monitoring."
    assert document["change_description"] == "Update firewall policy for monitoring."
    assert document["rollback_branches"][0]["steps"] == ["Remove the change."]
    assert document["verification"]["post_change"] == ["Confirm service health."]


def test_change_service_enriches_weak_hsm_notes_instead_of_repeating_source(core, settings: Settings):
    _, _, _, _, schema, _ = core
    full_change_request_schema(schema)
    notes = (
        "Next Tuesday I need to upgrade two HSMs for Wise and these are wiseld5-hsm-2 and wiseld2-hsm-2. "
        "we need to upgrade the software to version 2.3a first and then install mTLS "
        "the change window for this will be from 9 a.m. to 6 p.m that day"
    )

    class StubLocalLLM:
        def generate_json(self, prompt, source_text, max_tokens=0):
            assert "Do not simply copy the full rough notes" in prompt
            assert "phased device work" in prompt
            assert "Freshdesk-visible fields must read as if written by the change requester" in prompt
            return {
                "title": "Change request",
                "background": source_text,
                "description": source_text,
                "configuration_items": [],
                "implementation_steps": [],
                "rollback_plan": [],
                "verification": {},
            }

    service = ChangeService(
        StubLocalLLM(),
        schema,
        TicketDefaultsService(schema, lambda: settings),
        now_provider=lambda: datetime(2026, 6, 10, 9, tzinfo=ZoneInfo("Europe/London")),
    )

    result = service.suggest(notes)
    document = result["change_document"]
    assert document["planned_change_date"] == "Tuesday 16 June 2026"
    assert document["planned_start"] == "Tuesday 16 June 2026, 09:00 BST"
    assert document["planned_end"] == "Tuesday 16 June 2026, 18:00 BST"
    assert document["background"] != notes
    assert "notes" not in document["background"].lower()
    assert document["change_description"] != notes
    assert {item["name"] for item in document["configuration_items"] if item["item_type"] == "HSM"} == {
        "wiseld5-hsm-2",
        "wiseld2-hsm-2",
    }
    assert all(item["version"] == "Target software version 2.3a" for item in document["configuration_items"] if item["item_type"] == "HSM")
    assert any("Upgrade wiseld5-hsm-2 to software version 2.3a." == step for step in document["implementation_steps"])
    assert any("Install or enable the required mTLS configuration on wiseld2-hsm-2" in step for step in document["implementation_steps"])
    assert "Stop further upgrades" in document["rollback_branches"][0]["steps"][0]
    assert any("mTLS handshake" in item for item in document["verification"]["in_change"])
    assert document["impact"] == "Moderate"
    rendered = result["rendered_description"].lower()
    for forbidden in ["rough notes", "source notes", "source material", "prompt", "model", "ai wrote", "the notes identify"]:
        assert forbidden not in rendered

    envelope = service._agent_envelope(notes, result)
    sections = {section.key: section.content for section in envelope.description_sections}
    assert "TBD" not in sections["config_items"]
    assert "wiseld5-hsm-2" in sections["config_items"]
    assert "Upgrade wiseld5-hsm-2 to software version 2.3a." in sections["implementation"]
    assert "vendor or approved runbook" in sections["rollback"]
    assert "mTLS handshake" in sections["verification"]
    assert any("target software version" in item.text for item in envelope.assumptions)


def test_change_service_returns_editable_fallback_for_invalid_model_json(core, settings: Settings):
    _, _, _, _, schema, _ = core
    change_schema(schema)

    class StubLocalLLM:
        def generate_json(self, prompt, source_text, max_tokens=0):
            raise HTTPException(status_code=502, detail="Invalid structured output")

    result = ChangeService(StubLocalLLM(), schema, TicketDefaultsService(schema, lambda: settings)).suggest("Update the monitoring firewall rule.")
    assert result["change_document"]["background"] == "Update the monitoring firewall rule."
    assert "did not return a complete structured document" in result["assumptions"][0]


@pytest.mark.parametrize(
    ("notes", "expected_type", "expected_state"),
    [
        ("This is a Standard change.", "Standard", "Pending approval"),
        ("Emergency change requiring Approved workflow state.", "Emmergency", "Approved"),
    ],
)
def test_change_service_only_overrides_defaults_when_notes_are_explicit(core, settings: Settings, notes: str, expected_type: str, expected_state: str):
    _, _, _, _, schema, _ = core
    change_schema(schema)

    class StubLocalLLM:
        def generate_json(self, prompt, source_text, max_tokens=0):
            return {**wise_change_document(), "freshdesk_fields": {"cf_change_catergory": "Not allowed"}}

    result = ChangeService(StubLocalLLM(), schema, TicketDefaultsService(schema, lambda: settings)).suggest(notes)
    custom = result["suggestions"]["custom_fields"]
    assert custom["cf_change_type"] == expected_type
    assert custom["cf_change_state"] == expected_state
    assert "cf_change_catergory" not in custom


def test_change_draft_save_rerenders_description_and_stores_structured_record(core, settings: Settings):
    _, _, _, _, schema, drafts = core
    change_schema(schema)
    document = ChangeDocument.model_validate(wise_change_document())
    service = ChangeService(None, schema, TicketDefaultsService(schema, lambda: settings))
    values, generated = service.prepare_draft(
        {"subject": document.title, "description": "stale preview", "requester_email": "test@example.com", "change_document": document, "assumptions": ["Review date"]}
    )
    draft = drafts.create(values, kind="change", generated_output=generated)
    assert draft["payload"]["description"] == render_change_html(document)
    assert draft["generated_output"]["change_document"]["title"] == document.title
    assert draft["generated_output"]["assumptions"] == ["Review date"]


def test_change_draft_prepare_uses_mapped_title_when_form_subject_is_empty(core, settings: Settings):
    _, _, _, _, schema, _ = core
    change_schema(schema)
    document = ChangeDocument.model_validate(wise_change_document())
    service = ChangeService(None, schema, TicketDefaultsService(schema, lambda: settings))

    values, _ = service.prepare_draft({"subject": "", "requester_email": "test@example.com", "change_document": document})

    assert values["subject"] == document.title
    assert values["description"] == render_change_html(document)


def test_change_draft_from_structured_notes_uses_valid_freshdesk_payload(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    change_schema(services.schema_cache)
    client = TestClient(app)
    document_value = {**wise_change_document(), "impact": "Moderate"}
    document = ChangeDocument.model_validate(document_value)

    response = client.post(
        "/api/tickets/draft-change",
        json={"requester_email": "requester@example.com", "change_document": document_value},
    )

    assert response.status_code == 200
    draft = response.json()
    payload = draft["payload"]
    assert set(payload) <= ALLOWED_TICKET_FIELDS
    assert "product" not in payload
    assert payload["subject"] == document.title
    assert payload["description"] == render_change_html(document)
    assert payload["custom_fields"]["cf_form2"] == "Change Request"
    assert payload["custom_fields"]["cf_type"] == "Change"
    assert payload["custom_fields"]["cf_customer967575"] == "Wise_UK"
    assert payload["custom_fields"]["cf_change_type"] == "Normal"
    assert payload["custom_fields"]["cf_change_state"] == "Pending approval"
    assert payload["custom_fields"]["cf_chg_business_impact"] == "Moderate"
    assert draft["validation_result"]["invalid_fields"] == []
    assert draft["validation_result"]["invalid_custom_fields"] == []
    assert draft["validation_result"]["invalid_custom_field_values"] == []


def test_change_style_llm_creates_agent_review_draft(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    full_change_request_schema(services.schema_cache)
    services.schema_cache.put(
        "ticket_fields",
        [
            *services.schema_cache.ticket_fields(),
            {"name": "company", "label": "Company", "type": "default_company", "required_for_agents": True},
        ],
    )
    services.schema_cache.put("companies", [{"id": 7, "name": "Example Limited", "domains": ["example.com"]}])
    services.schema_cache.put("groups", [{"id": 9, "name": "L3 Engineering"}])
    services.schema_cache.put("agents", [{"id": 8, "contact": {"name": "Kwabiwe Sibanda"}}])

    class StubLocalLLM:
        def generate_json(self, prompt, source_text, max_tokens=0):
            assert "Freshdesk Change Request form" in prompt
            assert "relationship fields unresolved" in prompt
            return {
                "change_document": {**wise_change_document(), "customer": "Example"},
                "custom_fields": {"cf_customer967575": "Example", "cf_change_type": "Normal"},
                "assumptions": ["Assumed phased HSM upgrade is a normal change."],
                "open_questions": ["Confirm exact implementation window."],
            }

    services.changes.local_llm = StubLocalLLM()

    response = TestClient(app).post("/api/tickets/draft-change-review", json={"text": "Upgrade Wise UK HSMs next Tuesday."})

    assert response.status_code == 200
    body = response.json()
    draft = body["draft"]
    fields = draft["envelope"]["ticket_fields"]
    labels = [field["label"] for field in fields]
    assert labels.index("Company") < labels.index("Contact")
    assert "Description" not in labels
    field_by_key = {field["key"]: field for field in fields}
    assert field_by_key["form"]["display_value"] == "Change Request"
    assert field_by_key["customer"]["display_value"] == "Example"
    assert field_by_key["company"]["status"] == "missing"
    assert field_by_key["contact"]["status"] in {"missing", "needs_human_choice"}
    assert "Search and select" in " ".join(field_by_key["contact"]["field_errors"])
    assert draft["payload_preview"]["payload"]["description"]
    assert "company_id" not in draft["payload_preview"]["payload"]
    assert "requester_id" not in draft["payload_preview"]["payload"]
    assert any(item["text"] == "Assumed phased HSM upgrade is a normal change." for item in draft["envelope"]["assumptions"])
    assert any(item["field"] == "Open question" and "implementation window" in item["reason"] for item in draft["envelope"]["missing_information"])


def test_change_draft_blocks_company_without_resolved_requester(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    change_schema(services.schema_cache)
    services.schema_cache.put("companies", [{"id": 7, "name": "Example Limited", "domains": ["example.com"]}])
    sent: list[dict[str, object]] = []
    services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 99}
    client = TestClient(app)

    response = client.post(
        "/api/tickets/draft-change",
        json={
            "requester_email": "requester@example.com",
            "company_id": 7,
            "change_document": wise_change_document(),
        },
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["validation_status"] == "invalid"
    assert draft["payload"]["company_id"] == 7
    assert "resolved to a Freshdesk contact" in draft["validation_result"]["invalid_company_association"][0]["message"]

    approval = client.post(f"/api/tickets/drafts/{draft['draft_id']}/approve-create", json={"confirmation": "CREATE"})

    assert approval.status_code == 422
    assert sent == []


def test_change_draft_approval_blocks_invalid_custom_field_override(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    change_schema(services.schema_cache)
    sent: list[dict[str, object]] = []
    services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 99}
    client = TestClient(app)
    response = client.post(
        "/api/tickets/draft-change",
        json={
            "requester_email": "requester@example.com",
            "change_document": wise_change_document(),
            "custom_fields": {"cf_change_state": "Banana"},
        },
    )
    assert response.status_code == 200
    draft = response.json()
    assert draft["validation_result"]["valid"] is False
    assert draft["validation_result"]["invalid_custom_field_values"][0]["name"] == "cf_change_state"

    response = client.post(f"/api/tickets/drafts/{draft['draft_id']}/approve-create", json={"confirmation": "CREATE"})

    assert response.status_code == 422
    assert sent == []


def test_approval_workflow_creates_exact_draft(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    sent: list[dict[str, object]] = []
    services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 99}
    client = TestClient(app)
    response = client.post(
        "/api/tickets/draft",
        json={"subject": "Reviewed subject", "description": "Reviewed body", "requester_email": "requester@example.com"},
    )
    assert response.status_code == 200
    draft_id = response.json()["draft_id"]
    response = client.post(f"/api/tickets/drafts/{draft_id}/approve-create", json={"confirmation": "CREATE"})
    assert response.status_code == 200
    assert sent == [
        {
            "subject": "Reviewed subject",
            "description": "Reviewed body",
            "email": "requester@example.com",
            "priority": 1,
            "status": 2,
            "source": 2,
        }
    ]
    response = client.post(f"/api/tickets/drafts/{draft_id}/approve-create", json={"confirmation": "CREATE"})
    assert response.status_code == 409
    assert len(sent) == 1


def test_schema_sync_is_blocked_by_emergency_stop(settings: Settings):
    app = create_app(settings)
    client = TestClient(app)
    assert client.post("/api/admin/emergency-stop", json={"confirmation": "STOP"}).status_code == 200
    response = client.post("/api/freshdesk/sync-schema")
    assert response.status_code == 423


def agent_payload() -> dict[str, object]:
    return {
        "schema_version": "a24.freshdesk_draft.v1",
        "mode": "create",
        "status": "ready_for_review",
        "ticket_fields": [
            {"key": "subject", "kind": "short_text", "display_value": "Mailbox routing change", "required": True, "status": "confirmed", "confidence": 0.9},
            {"key": "contact", "kind": "entity_ref", "display_value": "Test User <test@example.com>", "required": True, "status": "confirmed", "confidence": 0.9},
            {"key": "form", "kind": "enum", "display_value": "Change Request", "required": True, "status": "inferred"},
            {"key": "ticket_type", "kind": "enum", "display_value": "Change", "required": True, "status": "inferred"},
            {"key": "status", "kind": "enum", "display_value": "Open", "required": True, "status": "confirmed"},
            {"key": "business_impact", "kind": "enum", "display_value": "Minor", "required": True, "status": "confirmed"},
            {"key": "priority", "kind": "enum", "display_value": "Low", "required": True, "status": "confirmed"},
        ],
        "description_sections": [
            {"key": "scope", "title": "Scope of the change", "content": "Update mailbox routing only.", "status": "confirmed"},
            {"key": "implementation", "title": "Implementation steps", "content": "Update routing rule and test delivery.", "status": "confirmed"},
            {"key": "rollback", "title": "Rollback plan", "content": "Restore the previous mailbox routing rule.", "status": "confirmed"},
            {"key": "verification", "title": "Test or verification steps", "content": "Send a controlled test message.", "status": "confirmed"},
            {"key": "config_items", "title": "Configuration Items", "content": "Shared mailbox routing rule.", "status": "confirmed"},
            {"key": "requester_context", "title": "Requester context", "content": "Sample email context.", "status": "confirmed"},
            {"key": "assumptions_missing", "title": "Assumptions or missing information", "content": "No known gaps.", "status": "confirmed"},
        ],
        "sources": [{"id": "src_email_1", "kind": "email", "title": "Sample email context", "snippet": "Mailbox routing request."}],
        "assumptions": [{"id": "asm_1", "text": "Business impact assumed Minor."}],
        "missing_information": [],
        "validation": {"warnings": [], "blocking": [], "valid": True},
        "revision": {"number": 1, "created_by": "ai_agent", "events": []},
    }


def test_agent_draft_accepts_normalizes_and_resolves_metadata(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    services.schema_cache.put("groups", [{"id": 9, "name": "L3 Engineering"}])
    services.schema_cache.put("agents", [{"id": 8, "contact": {"name": "Kwabiwe Sibanda"}}])
    services.schema_cache.put("ticket_forms", [{"id": 4, "title": "Change Request"}])
    services.schema_cache.put(
        "ticket_fields",
        [
            {"name": "cf_form2", "label": "Form", "choices": ["Change Request", "A24 Incident"]},
            {"name": "cf_business_impact", "label": "Business Impact", "choices": ["Minor", "Major"]},
            {"name": "cf_ticket_type", "label": "Ticket Type", "choices": ["Change", "Incident"]},
        ],
    )
    response = TestClient(app).post("/api/v1/drafts", json=agent_payload())
    assert response.status_code == 200
    body = response.json()
    fields = {field["key"]: field for field in body["envelope"]["ticket_fields"]}
    assert fields["group"]["resolved_id"] == 9
    assert fields["agent"]["resolved_id"] == 8
    assert fields["form"]["schema_field_name"] == "cf_form2"
    assert fields["form"]["display_value"] == "Change Request"
    assert fields["business_impact"]["display_value"] == "Minor"
    assert body["validation_result"]["valid"] is True
    assert body["validation_result"]["warnings"] == []


def test_agent_change_request_profile_adds_a24_form_fields(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    change_schema(services.schema_cache)
    services.schema_cache.put("agents", [{"id": 8, "contact": {"name": "Kwabiwe Sibanda"}}])
    services.schema_cache.put("groups", [{"id": 9, "name": "L3 Engineering"}])

    response = TestClient(app).post("/api/v1/drafts", json=agent_payload())

    assert response.status_code == 200
    fields = {field["key"]: field for field in response.json()["envelope"]["ticket_fields"]}
    assert fields["form"]["schema_field_name"] == "cf_form2"
    assert fields["ticket_type"]["schema_field_name"] == "cf_type"
    assert fields["ticket_type"]["display_value"] == "Change"
    assert fields["background_for_the_change"]["label"] == "Background for the Change"
    assert fields["change_owner"]["display_value"] == "Test User"
    assert fields["change_state"]["display_value"] == "Pending approval"
    assert fields["approval_state"]["display_value"] == "Not Yet Requested"
    assert fields["change_type"]["payload_path"] == "custom_fields.cf_change_type"


def test_agent_change_request_ledger_matches_freshdesk_form_order(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    full_change_request_schema(services.schema_cache)
    services.schema_cache.put("agents", [{"id": 8, "contact": {"name": "Kwabiwe Sibanda"}}])
    services.schema_cache.put("groups", [{"id": 9, "name": "L3 Engineering"}])

    response = TestClient(app).post("/api/v1/drafts", json=agent_payload())

    assert response.status_code == 200
    fields = response.json()["envelope"]["ticket_fields"]
    assert [field["label"] for field in fields] == [
        "Product",
        "Contact",
        "Subject",
        "Form",
        "Background for the Change",
        "Change Type",
        "Requested By",
        "Change owner",
        "Change Category",
        "CHG Business Impact",
        "Change State",
        "Approval State",
        "Ticket Type",
        "Status",
        "Business Impact",
        "Group",
        "Agent",
        "Priority",
        "Customer",
        "Reminder Date",
        "Tags",
    ]
    assert "Description" not in [field["label"] for field in fields]
    payload_paths = {field["key"]: field["payload_path"] for field in fields}
    assert payload_paths["product"] == "product_id"
    assert payload_paths["contact"] == "email/name"
    assert payload_paths["change_category"] == "custom_fields.cf_change_catergory"
    assert payload_paths["ticket_type"] == "custom_fields.cf_type"
    assert payload_paths["business_impact"] == "custom_fields.cf_business_impact723800"
    assert payload_paths["tags"] == "tags"


def test_agent_change_request_adds_required_company_before_contact(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    full_change_request_schema(services.schema_cache)
    services.schema_cache.put(
        "ticket_fields",
        [
            *services.schema_cache.ticket_fields(),
            {"name": "company", "label": "Company", "type": "default_company", "required_for_agents": True},
        ],
    )
    services.schema_cache.put("companies", [{"id": 7, "name": "Example Limited", "domains": ["example.com"]}])
    services.schema_cache.put("agents", [{"id": 8, "contact": {"name": "Kwabiwe Sibanda"}}])
    services.schema_cache.put("groups", [{"id": 9, "name": "L3 Engineering"}])

    response = TestClient(app).post("/api/v1/drafts", json=agent_payload())

    assert response.status_code == 200
    fields = response.json()["envelope"]["ticket_fields"]
    labels = [field["label"] for field in fields]
    assert labels.index("Company") < labels.index("Contact")
    company = next(field for field in fields if field["key"] == "company")
    assert company["payload_path"] == "company_id"
    assert company["status"] == "missing"


def test_agent_autofills_company_from_selected_contact(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    full_change_request_schema(services.schema_cache)
    services.schema_cache.put(
        "ticket_fields",
        [
            *services.schema_cache.ticket_fields(),
            {"name": "company", "label": "Company", "type": "default_company", "required_for_agents": True},
        ],
    )
    services.schema_cache.put("companies", [{"id": 7, "name": "Example Limited", "domains": ["example.com"]}])
    services.schema_cache.put("agents", [{"id": 8, "contact": {"name": "Kwabiwe Sibanda"}}])
    services.schema_cache.put("groups", [{"id": 9, "name": "L3 Engineering"}])
    client = TestClient(app)
    created = client.post("/api/v1/drafts", json=agent_payload()).json()
    contact = next(field for field in created["envelope"]["ticket_fields"] if field["key"] == "contact")
    contact.update(
        {
            "display_value": "Ada Lovelace",
            "value": "Ada Lovelace",
            "resolved_id": 321,
            "email": "ada@example.com",
            "company_id": 7,
            "record": {"id": 321, "name": "Ada Lovelace", "email": "ada@example.com", "company_id": 7},
        }
    )

    patched = client.patch(f"/api/v1/drafts/{created['draft_id']}", json={"edited_by": "kb", "ticket_fields": [contact]}).json()

    fields = {field["key"]: field for field in patched["envelope"]["ticket_fields"]}
    assert fields["company"]["display_value"] == "Example Limited"
    assert fields["company"]["resolved_id"] == 7
    assert patched["payload_preview"]["payload"]["company_id"] == 7
    assert patched["validation_result"]["valid"] is True


def test_agent_lists_submitted_drafts_for_review_inbox(settings: Settings):
    client = TestClient(create_app(settings))
    first = client.post("/api/v1/drafts", json={**agent_payload(), "draft_id": "agd_first"}).json()
    second = client.post("/api/v1/drafts", json={**agent_payload(), "draft_id": "agd_second"}).json()

    response = client.get("/api/v1/drafts?limit=10")

    assert response.status_code == 200
    listed_ids = {draft["draft_id"] for draft in response.json()}
    assert {first["draft_id"], second["draft_id"]} <= listed_ids
    latest = client.get("/api/v1/drafts?limit=1").json()
    assert len(latest) == 1
    assert latest[0]["draft_id"] == second["draft_id"]


def test_agent_rejects_unsupported_schema_version(settings: Settings):
    payload = {**agent_payload(), "schema_version": "a24.freshdesk_draft.v9"}
    response = TestClient(create_app(settings)).post("/api/v1/drafts", json=payload)
    assert response.status_code == 422


def test_agent_patch_tracks_revision_and_feedback_payload(settings: Settings):
    app = create_app(settings)
    app.state.services.schema_cache.put(
        "ticket_fields",
        [
            {"name": "cf_form2", "label": "Form", "choices": ["Change Request"]},
            {"name": "cf_ticket_type", "label": "Ticket Type", "choices": ["Change"]},
        ],
    )
    sent: list[dict[str, object]] = []
    app.state.services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 1234}
    client = TestClient(app)
    created = client.post("/api/v1/drafts", json=agent_payload()).json()
    draft_id = created["draft_id"]
    subject = next(field for field in created["envelope"]["ticket_fields"] if field["key"] == "subject")
    subject["display_value"] = "Mailbox routing change - reviewed"
    subject["value"] = "Mailbox routing change - reviewed"
    response = client.patch(
        f"/api/v1/drafts/{draft_id}",
        json={"edited_by": "kb", "ticket_fields": [subject], "reason": "Tightened subject"},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["revision_events"][0]["field_key"] == "subject"
    assert updated["revision_events"][0]["old_value"] == "Mailbox routing change"
    assert updated["revision_events"][0]["new_value"] == "Mailbox routing change - reviewed"

    response = client.post(f"/api/v1/drafts/{draft_id}/approve-and-submit", json={"confirmation": "CREATE"})
    assert response.status_code == 200
    submitted = response.json()
    assert submitted["approval_status"] == "submitted"
    assert submitted["ticket_id"] == "1234"
    assert sent[0]["subject"] == "Mailbox routing change - reviewed"
    assert sent[0]["custom_fields"]["cf_ticket_type"] == "Change"
    assert sent[0]["priority"] == 1
    assert sent[0]["status"] == 2
    assert submitted["feedback_payload"]["changed_fields"][0]["field_key"] == "subject"
    assert submitted["feedback_payload"]["final_fields"]["subject"] == "Mailbox routing change - reviewed"
    assert submitted["feedback_payload"]["freshdesk_payload"]["subject"] == "Mailbox routing change - reviewed"


def test_agent_submit_includes_contact_company_when_required(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    services.schema_cache.put("companies", [{"id": 7, "name": "Example Limited", "domains": ["example.com"]}])
    services.schema_cache.put(
        "ticket_fields",
        [
            {"name": "company", "label": "Company", "type": "default_company", "required_for_agents": True},
            {"name": "cf_form2", "label": "Form", "choices": ["Change Request"]},
            {"name": "cf_ticket_type", "label": "Ticket Type", "choices": ["Change"]},
        ],
    )
    sent: list[dict[str, object]] = []
    services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 1234}
    client = TestClient(app)
    created = client.post("/api/v1/drafts", json=agent_payload()).json()
    contact = next(field for field in created["envelope"]["ticket_fields"] if field["key"] == "contact")
    contact.update(
        {
            "display_value": "Ada Lovelace",
            "value": "Ada Lovelace",
            "resolved_id": 321,
            "company_id": 7,
            "record": {"id": 321, "name": "Ada Lovelace", "email": "ada@example.com", "company_id": 7},
        }
    )
    patched = client.patch(f"/api/v1/drafts/{created['draft_id']}", json={"edited_by": "kb", "ticket_fields": [contact]}).json()

    response = client.post(f"/api/v1/drafts/{patched['draft_id']}/approve-and-submit", json={"confirmation": "CREATE"})

    assert response.status_code == 200
    assert sent[0]["company_id"] == 7


def test_agent_submit_maps_change_request_fields_to_valid_freshdesk_payload(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    services.schema_cache.put("companies", [{"id": 7, "name": "Example Limited", "domains": ["example.com"]}])
    services.schema_cache.put("agents", [{"id": 8, "name": "Kwabiwe Sibanda", "contact": {"name": "Kwabiwe Sibanda"}}])
    services.schema_cache.put("groups", [{"id": 9, "name": "L3 Engineering"}])
    services.schema_cache.put(
        "ticket_fields",
        [
            {"name": "requester", "label": "Search a requester", "type": "default_requester", "required_for_agents": True},
            {"name": "subject", "label": "Subject", "type": "default_subject", "required_for_agents": True},
            {"name": "status", "label": "Status", "type": "default_status", "required_for_agents": True, "choices": {"2": ["Open", "Open"], "3": ["Pending", "Pending"]}},
            {"name": "priority", "label": "Priority", "type": "default_priority", "required_for_agents": True, "choices": {"Low": 1, "Medium": 2}},
            {"name": "description", "label": "Description", "type": "default_description", "required_for_agents": True},
            {"name": "company", "label": "Company", "type": "default_company", "required_for_agents": True},
            {"name": "product", "label": "Product", "type": "default_product", "choices": {"A24 Support": 205000014435}},
            {"name": "cf_form2", "label": "Form", "type": "custom_dropdown", "choices": ["Change Request"]},
            {"name": "cf_type", "label": "Ticket Type", "type": "nested_field", "choices": {"Change": {}}},
            {"name": "cf_customer967575", "label": "Customer", "type": "custom_dropdown", "required_for_agents": True, "choices": ["Example", "A24"]},
            {"name": "cf_business_impact723800", "label": "Business Impact", "type": "custom_dropdown", "choices": ["Minor", "Moderate"]},
            {"name": "cf_change_type", "label": "Change Type", "type": "custom_dropdown", "choices": ["Standard", "Normal"]},
            {"name": "cf_change_state", "label": "Change State", "type": "custom_dropdown", "required_for_agents": True, "choices": ["Pending approval", "Approved"]},
            {"name": "cf_change_owner", "label": "Change owner", "type": "custom_text", "required_for_agents": True},
            {"name": "cf_requested_by", "label": "Requested by", "type": "custom_text"},
            {"name": "cf_approval_state", "label": "Approval State", "type": "custom_dropdown", "choices": ["Not Yet Requested"]},
        ],
    )
    sent: list[dict[str, object]] = []
    services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 1234}
    client = TestClient(app)
    created = client.post("/api/v1/drafts", json=agent_payload()).json()
    contact = next(field for field in created["envelope"]["ticket_fields"] if field["key"] == "contact")
    contact.update(
        {
            "display_value": "Ada Lovelace",
            "value": "Ada Lovelace",
            "resolved_id": 321,
            "company_id": 7,
            "record": {"id": 321, "name": "Ada Lovelace", "email": "ada@example.com", "company_id": 7},
        }
    )
    created = client.patch(f"/api/v1/drafts/{created['draft_id']}", json={"edited_by": "kb", "ticket_fields": [contact]}).json()

    response = client.post(f"/api/v1/drafts/{created['draft_id']}/approve-and-submit", json={"confirmation": "CREATE"})

    assert response.status_code == 200
    payload = sent[0]
    assert set(payload) <= ALLOWED_TICKET_FIELDS
    assert "product" not in payload
    assert payload["product_id"] == 205000014435
    assert payload["company_id"] == 7
    assert payload["group_id"] == 9
    assert payload["responder_id"] == 8
    assert payload["requester_id"] == 321
    assert "email" not in payload
    assert payload["priority"] == 1
    assert payload["status"] == 2
    assert "<h2>Scope of the change</h2><p>Update mailbox routing only.</p>" in payload["description"]
    assert "<h2>Implementation steps</h2><p>Update routing rule and test delivery.</p>" in payload["description"]
    assert payload["custom_fields"]["cf_form2"] == "Change Request"
    assert payload["custom_fields"]["cf_type"] == "Change"
    assert payload["custom_fields"]["cf_customer967575"] == "Example"
    assert payload["custom_fields"]["cf_business_impact723800"] == "Minor"
    assert payload["custom_fields"]["cf_change_type"] == "Normal"
    assert payload["custom_fields"]["cf_change_state"] == "Pending approval"
    assert payload["custom_fields"]["cf_change_owner"] == "Test User"


def test_agent_payload_preview_matches_payload_sent_on_approval(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    services.schema_cache.put("companies", [{"id": 7, "name": "Example Limited", "domains": ["example.com"]}])
    services.schema_cache.put("agents", [{"id": 8, "name": "Kwabiwe Sibanda", "contact": {"name": "Kwabiwe Sibanda"}}])
    services.schema_cache.put("groups", [{"id": 9, "name": "L3 Engineering"}])
    full_change_request_schema(services.schema_cache)
    sent: list[dict[str, object]] = []
    services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 1234}
    client = TestClient(app)
    created = client.post("/api/v1/drafts", json=agent_payload()).json()
    preview = client.get(f"/api/v1/drafts/{created['draft_id']}/payload-preview").json()

    response = client.post(f"/api/v1/drafts/{created['draft_id']}/approve-and-submit", json={"confirmation": "CREATE"})

    assert response.status_code == 200
    assert preview["validation"]["valid"] is True
    assert preview["payload"] == sent[0]
    assert "description" in preview["payload"]
    assert "product" not in preview["payload"]


def test_agent_description_sections_map_to_one_description_payload_field(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    services.schema_cache.put(
        "ticket_fields",
        [
            {"name": "requester", "label": "Contact", "type": "default_requester", "required_for_agents": True},
            {"name": "cf_form2", "label": "Form", "choices": ["Change Request"]},
            {"name": "cf_ticket_type", "label": "Ticket Type", "choices": ["Change"]},
        ],
    )
    sent: list[dict[str, object]] = []
    services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 1234}
    client = TestClient(app)
    created = client.post("/api/v1/drafts", json=agent_payload()).json()

    response = client.post(f"/api/v1/drafts/{created['draft_id']}/approve-and-submit", json={"confirmation": "CREATE"})

    assert response.status_code == 200
    payload = sent[0]
    assert list(key for key in payload if key == "description") == ["description"]
    assert "<h2>Implementation steps</h2>" in payload["description"]
    assert "<h2>Rollback plan</h2>" in payload["description"]
    assert "<h2>Test or verification steps</h2>" in payload["description"]
    assert "implementation" not in payload
    assert "rollback" not in payload
    assert "verification" not in payload
    assert not {"implementation", "rollback", "verification"} & set(payload.get("custom_fields", {}))


def test_agent_custom_fields_use_synced_freshdesk_names(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    services.schema_cache.put("companies", [{"id": 7, "name": "Example Limited", "domains": ["example.com"]}])
    services.schema_cache.put("agents", [{"id": 8, "name": "Kwabiwe Sibanda", "contact": {"name": "Kwabiwe Sibanda"}}])
    services.schema_cache.put("groups", [{"id": 9, "name": "L3 Engineering"}])
    full_change_request_schema(services.schema_cache)
    sent: list[dict[str, object]] = []
    services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 1234}
    payload = agent_payload()
    payload["ticket_fields"] = [
        *payload["ticket_fields"],
        {"key": "background_for_the_change", "display_value": "Reduce manual intervention.", "status": "confirmed"},
        {"key": "change_type", "display_value": "Normal", "status": "confirmed"},
        {"key": "requested_by", "display_value": "Test User", "status": "confirmed"},
        {"key": "change_owner", "display_value": "Test User", "required": True, "status": "confirmed"},
        {"key": "change_category", "display_value": "Application", "status": "confirmed"},
        {"key": "chg_business_impact", "display_value": "Moderate", "status": "confirmed"},
        {"key": "change_state", "display_value": "Pending approval", "required": True, "status": "confirmed"},
        {"key": "approval_state", "display_value": "Not Yet Requested", "status": "confirmed"},
        {"key": "customer", "display_value": "Example", "required": True, "status": "confirmed"},
        {"key": "reminder_date", "display_value": "2026-06-15", "status": "confirmed"},
        {"key": "tags", "display_value": "change, network\napproved", "status": "confirmed"},
    ]
    client = TestClient(app)
    created = client.post("/api/v1/drafts", json=payload).json()

    response = client.post(f"/api/v1/drafts/{created['draft_id']}/approve-and-submit", json={"confirmation": "CREATE"})

    assert response.status_code == 200
    custom_fields = sent[0]["custom_fields"]
    assert custom_fields["cf_form2"] == "Change Request"
    assert custom_fields["cf_change_type"] == "Normal"
    assert custom_fields["cf_change_owner"] == "Test User"
    assert custom_fields["cf_change_catergory"] == "Application"
    assert custom_fields["cf_chg_business_impact"] == "Moderate"
    assert custom_fields["cf_change_state"] == "Pending approval"
    assert custom_fields["cf_approval_state"] == "Not Yet Requested"
    assert custom_fields["cf_type"] == "Change"
    assert custom_fields["cf_customer967575"] == "Example"
    assert custom_fields["cf_business_impact723800"] == "Minor"
    assert custom_fields["cf_reminder_date"] == "2026-06-15"
    assert sent[0]["tags"] == ["change", "network", "approved"]


def test_agent_dropdown_choices_are_enforced(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    services.schema_cache.put(
        "ticket_fields",
        [
            {"name": "requester", "label": "Contact", "type": "default_requester", "required_for_agents": True},
            {"name": "cf_form2", "label": "Form", "choices": ["Change Request"]},
            {"name": "cf_ticket_type", "label": "Ticket Type", "choices": ["Change"]},
            {"name": "cf_change_type", "label": "Change Type", "required_for_agents": True, "choices": ["Standard", "Normal", "Emmergency"]},
        ],
    )
    sent: list[dict[str, object]] = []
    services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 1234}
    payload = agent_payload()
    payload["ticket_fields"] = [
        *payload["ticket_fields"],
        {"key": "change_type", "display_value": "Emergency", "required": True, "status": "confirmed"},
    ]
    client = TestClient(app)
    created = client.post("/api/v1/drafts", json=payload).json()
    field = next(item for item in created["envelope"]["ticket_fields"] if item["key"] == "change_type")

    response = client.post(f"/api/v1/drafts/{created['draft_id']}/approve-and-submit", json={"confirmation": "CREATE"})

    assert field["status"] == "needs_human_choice"
    assert response.status_code == 422
    assert sent == []
    assert "Choose an allowed value for Change Type." in response.json()["detail"]["blocking"]


def test_agent_submit_blocks_required_product_without_safe_product_id(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    services.schema_cache.put(
        "ticket_fields",
        [
            {"name": "product", "label": "Product", "type": "default_product", "required_for_agents": True, "choices": ["A24 Support"]},
            {"name": "cf_form2", "label": "Form", "choices": ["Change Request"]},
            {"name": "cf_ticket_type", "label": "Ticket Type", "choices": ["Change"]},
        ],
    )
    sent: list[dict[str, object]] = []
    services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 1234}
    client = TestClient(app)
    created = client.post("/api/v1/drafts", json=agent_payload()).json()

    response = client.post(f"/api/v1/drafts/{created['draft_id']}/approve-and-submit", json={"confirmation": "CREATE"})

    assert response.status_code == 422
    assert sent == []
    detail = response.json()["detail"]
    assert detail["message"] == "AI agent draft validation failed."
    assert "Freshdesk payload is missing Product." in detail["blocking"]


def test_agent_submit_blocks_unresolved_non_default_contact(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    services.schema_cache.put(
        "ticket_fields",
        [
            {"name": "requester", "label": "Search a requester", "type": "default_requester", "required_for_agents": True},
            {"name": "cf_form2", "label": "Form", "choices": ["Change Request"]},
            {"name": "cf_ticket_type", "label": "Ticket Type", "choices": ["Change"]},
        ],
    )
    sent: list[dict[str, object]] = []
    services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 1234}
    client = TestClient(app)
    created = client.post("/api/v1/drafts", json=agent_payload()).json()
    contact = next(field for field in created["envelope"]["ticket_fields"] if field["key"] == "contact")
    contact["display_value"] = "Ada Lovelace"
    contact["value"] = "Ada Lovelace"
    contact["resolved_id"] = None
    patched = client.patch(
        f"/api/v1/drafts/{created['draft_id']}",
        json={"edited_by": "kb", "ticket_fields": [contact], "reason": "Test unresolved requester"},
    ).json()

    response = client.post(f"/api/v1/drafts/{patched['draft_id']}/approve-and-submit", json={"confirmation": "CREATE"})

    assert response.status_code == 422
    assert sent == []
    detail = response.json()["detail"]
    assert detail["message"] == "AI agent draft validation failed."
    assert "Freshdesk payload is missing Search a requester." in detail["blocking"]


def test_agent_contact_email_maps_to_email(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    services.schema_cache.put(
        "ticket_fields",
        [
            {"name": "requester", "label": "Contact", "type": "default_requester", "required_for_agents": True},
            {"name": "cf_form2", "label": "Form", "choices": ["Change Request"]},
            {"name": "cf_ticket_type", "label": "Ticket Type", "choices": ["Change"]},
        ],
    )
    sent: list[dict[str, object]] = []
    services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 1234}
    client = TestClient(app)
    created = client.post("/api/v1/drafts", json=agent_payload()).json()
    contact = next(field for field in created["envelope"]["ticket_fields"] if field["key"] == "contact")
    contact.update({"display_value": "Ada Lovelace <ada@example.com>", "value": "Ada Lovelace <ada@example.com>", "resolved_id": None})
    patched = client.patch(f"/api/v1/drafts/{created['draft_id']}", json={"edited_by": "kb", "ticket_fields": [contact]}).json()

    response = client.post(f"/api/v1/drafts/{patched['draft_id']}/approve-and-submit", json={"confirmation": "CREATE"})

    assert response.status_code == 200
    assert sent[0]["email"] == "ada@example.com"
    assert "contact" not in sent[0]
    assert "requester_id" not in sent[0]


def test_agent_contact_resolved_id_maps_to_requester_id(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    services.schema_cache.put(
        "ticket_fields",
        [
            {"name": "requester", "label": "Contact", "type": "default_requester", "required_for_agents": True},
            {"name": "cf_form2", "label": "Form", "choices": ["Change Request"]},
            {"name": "cf_ticket_type", "label": "Ticket Type", "choices": ["Change"]},
        ],
    )
    sent: list[dict[str, object]] = []
    services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 1234}
    client = TestClient(app)
    created = client.post("/api/v1/drafts", json=agent_payload()).json()
    contact = next(field for field in created["envelope"]["ticket_fields"] if field["key"] == "contact")
    contact.update({"display_value": "Ada Lovelace", "value": "Ada Lovelace", "resolved_id": 321})
    patched = client.patch(f"/api/v1/drafts/{created['draft_id']}", json={"edited_by": "kb", "ticket_fields": [contact]}).json()

    response = client.post(f"/api/v1/drafts/{patched['draft_id']}/approve-and-submit", json={"confirmation": "CREATE"})

    assert response.status_code == 200
    assert sent[0]["requester_id"] == 321
    assert "email" not in sent[0]
    assert "contact" not in sent[0]


def test_agent_omits_default_company_for_unverified_non_default_contact(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    services.schema_cache.put("companies", [{"id": 7, "name": "Example Limited", "domains": ["example.com"]}])
    services.schema_cache.put(
        "ticket_fields",
        [
            {"name": "requester", "label": "Contact", "type": "default_requester", "required_for_agents": True},
            {"name": "cf_form2", "label": "Form", "choices": ["Change Request"]},
            {"name": "cf_ticket_type", "label": "Ticket Type", "choices": ["Change"]},
        ],
    )
    sent: list[dict[str, object]] = []
    services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 1234}
    client = TestClient(app)
    created = client.post("/api/v1/drafts", json=agent_payload()).json()
    contact = next(field for field in created["envelope"]["ticket_fields"] if field["key"] == "contact")
    contact.update({"display_value": "Ada Lovelace <ada@other.example>", "value": "Ada Lovelace <ada@other.example>", "resolved_id": None})
    patched = client.patch(f"/api/v1/drafts/{created['draft_id']}", json={"edited_by": "kb", "ticket_fields": [contact]}).json()

    response = client.post(f"/api/v1/drafts/{patched['draft_id']}/approve-and-submit", json={"confirmation": "CREATE"})

    assert response.status_code == 200
    assert sent[0]["email"] == "ada@other.example"
    assert "company_id" not in sent[0]
    assert patched["payload_preview"]["field_errors"] == {}


def test_agent_blocks_required_company_when_contact_company_is_unverified(settings: Settings):
    app = create_app(settings)
    services = app.state.services
    services.schema_cache.put("companies", [{"id": 7, "name": "Example Limited", "domains": ["example.com"]}])
    services.schema_cache.put(
        "ticket_fields",
        [
            {"name": "requester", "label": "Contact", "type": "default_requester", "required_for_agents": True},
            {"name": "company", "label": "Company", "type": "default_company", "required_for_agents": True},
            {"name": "cf_form2", "label": "Form", "choices": ["Change Request"]},
            {"name": "cf_ticket_type", "label": "Ticket Type", "choices": ["Change"]},
        ],
    )
    sent: list[dict[str, object]] = []
    services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 1234}
    client = TestClient(app)
    created = client.post("/api/v1/drafts", json=agent_payload()).json()
    contact = next(field for field in created["envelope"]["ticket_fields"] if field["key"] == "contact")
    contact.update({"display_value": "Ada Lovelace <ada@other.example>", "value": "Ada Lovelace <ada@other.example>", "resolved_id": None})
    patched = client.patch(f"/api/v1/drafts/{created['draft_id']}", json={"edited_by": "kb", "ticket_fields": [contact]}).json()

    response = client.post(f"/api/v1/drafts/{patched['draft_id']}/approve-and-submit", json={"confirmation": "CREATE"})

    assert response.status_code == 422
    assert sent == []
    detail = response.json()["detail"]
    assert detail["message"] == "AI agent draft validation failed."
    assert any("could not verify that the selected Contact belongs" in item for item in detail["blocking"])


def test_agent_delete_removes_unsubmitted_draft_from_review_inbox(settings: Settings):
    client = TestClient(create_app(settings))
    created = client.post("/api/v1/drafts", json=agent_payload()).json()
    draft_id = created["draft_id"]

    response = client.delete(f"/api/v1/drafts/{draft_id}")

    assert response.status_code == 200
    assert response.json() == {"draft_id": draft_id, "deleted": True}
    assert client.get(f"/api/v1/drafts/{draft_id}").status_code == 404


def test_agent_submit_requires_exact_confirmation(settings: Settings):
    app = create_app(settings)
    client = TestClient(app)
    created = client.post("/api/v1/drafts", json=agent_payload()).json()
    response = client.post(
        f"/api/v1/drafts/{created['draft_id']}/approve-and-submit",
        json={"confirmation": "APPROVE"},
    )
    assert response.status_code == 400
    assert 'Type "CREATE"' in response.json()["detail"]


def test_agent_update_mode_updates_existing_ticket(settings: Settings):
    app = create_app(settings)
    sent: list[tuple[str, dict[str, object]]] = []
    app.state.services.freshdesk.update_ticket = lambda ticket_id, payload: sent.append((str(ticket_id), payload)) or {"id": ticket_id}
    client = TestClient(app)
    payload = {**agent_payload(), "mode": "update", "target_ticket_id": 7654}
    payload["ticket_fields"] = [field for field in payload["ticket_fields"] if field["key"] != "contact"]
    created = client.post("/api/v1/drafts", json=payload).json()
    response = client.post(
        f"/api/v1/drafts/{created['draft_id']}/approve-and-submit",
        json={"confirmation": "UPDATE"},
    )
    assert response.status_code == 200
    assert response.json()["ticket_id"] == "7654"
    assert sent[0][0] == "7654"
    assert sent[0][1]["subject"] == "Mailbox routing change"
    assert "email" not in sent[0][1]
    assert "name" not in sent[0][1]


def test_agent_standard_profile_does_not_require_change_sections(settings: Settings):
    payload = {
        **agent_payload(),
        "ticket_profile": "standard",
        "description_sections": [
            {"key": "description", "title": "Description", "content": "Create a normal support ticket.", "status": "confirmed"}
        ],
    }
    response = TestClient(create_app(settings)).post("/api/v1/drafts", json=payload)
    assert response.status_code == 200
    assert response.json()["validation_result"]["valid"] is True


def test_agent_bulk_create_validates_all_rows_before_creating(settings: Settings):
    app = create_app(settings)
    sent: list[dict[str, object]] = []
    app.state.services.freshdesk.create_ticket = lambda payload: sent.append(payload) or {"id": 2000 + len(sent)}
    client = TestClient(app)
    payload = {
        **agent_payload(),
        "mode": "bulk_create",
        "ticket_profile": "standard",
        "description_sections": [],
        "bulk_items": [
            {
                "row_id": "user_1",
                "title": "User 1",
                "ticket_fields": [
                    {"key": "subject", "display_value": "Onboard User 1", "required": True, "status": "confirmed"},
                    {"key": "contact", "display_value": "User One <one@example.com>", "required": True, "status": "confirmed"},
                ],
                "description_sections": [{"key": "description", "title": "Description", "content": "Create onboarding ticket for User 1.", "status": "confirmed"}],
            },
            {
                "row_id": "user_2",
                "title": "User 2",
                "ticket_fields": [
                    {"key": "subject", "display_value": "Onboard User 2", "required": True, "status": "confirmed"},
                    {"key": "contact", "display_value": "User Two <two@example.com>", "required": True, "status": "confirmed"},
                ],
                "description_sections": [{"key": "description", "title": "Description", "content": "Create onboarding ticket for User 2.", "status": "confirmed"}],
            },
        ],
    }
    created = client.post("/api/v1/drafts", json=payload).json()
    assert created["validation_result"]["valid"] is True
    response = client.post(
        f"/api/v1/drafts/{created['draft_id']}/approve-and-submit",
        json={"confirmation": "CREATE BULK"},
    )
    assert response.status_code == 200
    assert len(sent) == 2
    assert sent[0]["subject"] == "Onboard User 1"
    assert sent[0]["email"] == "one@example.com"
    assert response.json()["ticket_id"] == "2001,2002"


def test_agent_api_token_is_required_when_configured(settings: Settings):
    protected = replace(settings, agent_api_token="agent-secret")
    client = TestClient(create_app(protected))
    assert client.get("/api/v1/metadata").status_code == 401
    assert client.get("/api/v1/metadata", headers={"X-Agent-Token": "agent-secret"}).status_code == 200


def test_agent_routes_respect_emergency_stop(settings: Settings):
    app = create_app(settings)
    client = TestClient(app)
    assert client.post("/api/admin/emergency-stop", json={"confirmation": "STOP"}).status_code == 200
    assert client.get("/api/v1/metadata").status_code == 423
