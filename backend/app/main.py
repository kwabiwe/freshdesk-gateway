from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .audit import AuditLog
from .change_models import ChangeRenderRequest, ChangeSuggestionRequest
from .change_service import ChangeService
from .config import Settings, load_settings
from .database import Database
from .draft_assistant import DraftAssistantService
from .draft_store import DraftStore
from .emergency import EmergencyStop
from .freshdesk_client import FreshdeskClient
from .models import (
    BatchCreateRequest,
    BatchDraftRequest,
    ChangeDraftRequest,
    ConfirmationRequest,
    DraftUpdateRequest,
    DraftSuggestionRequest,
    RewriteRequest,
    SearchRequest,
    SettingsUpdateRequest,
    SummariseRequest,
    TicketDraftRequest,
    AgentDraftEnvelope,
    AgentDraftPatch,
    AgentFeedbackRequest,
)
from .agent_draft_store import AgentDraftStore
from .local_llm_client import LocalLLMClient
from .rate_limit import RateLimiter
from .related_tickets import RelatedTicketsService
from .schema_cache import SchemaCache
from .schema_service import SchemaService
from .skill_registry import SkillRegistry
from .ticket_templates import render_change_description
from .ticket_defaults import TicketDefaultsService
from .validators import TicketValidator


class Services:
    def __init__(self, base_settings: Settings):
        self.base_settings = base_settings
        self.db = Database(base_settings.database_path)
        self.audit = AuditLog(self.db)

        def settings_provider() -> Settings:
            return self.base_settings.with_overrides(self.db.get_overrides())

        self.settings = settings_provider
        self.emergency = EmergencyStop(base_settings.stop_file, self.audit)
        self.limiter = RateLimiter(self.db, settings_provider, self.audit)
        self.schema_cache = SchemaCache(self.db, self.audit)
        self.freshdesk = FreshdeskClient(settings_provider, self.emergency, self.limiter, self.audit)
        self.local_llm = LocalLLMClient(settings_provider, self.audit)
        self.ollama = self.local_llm
        self.validator = TicketValidator(self.schema_cache)
        self.drafts = DraftStore(self.db, settings_provider, self.validator, self.audit)
        self.schema = SchemaService(self.freshdesk, self.schema_cache, self.audit)
        self.defaults = TicketDefaultsService(self.schema_cache, settings_provider)
        self.assistant = DraftAssistantService(self.local_llm, self.schema_cache, self.defaults)
        self.agent = AgentDraftStore(self.db, self.schema_cache, self.audit, self.freshdesk, self.validator, self.defaults)
        self.skill_registry = SkillRegistry()
        self.change_skill = self.skill_registry.get(base_settings.change_drafting_skill)
        self.changes = ChangeService(self.local_llm, self.schema_cache, self.defaults, self.change_skill)
        self.related = RelatedTicketsService(self.freshdesk, self.schema_cache, settings_provider, self.audit)


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Freshdesk Gateway", version="0.1.0")
    services = Services(settings or load_settings())
    app.state.services = services

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {"ok": True, "service": "freshdesk-gateway", "local_only": True}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        settings = services.settings()
        schema_overview = services.schema_cache.overview()
        freshdesk_check = services.schema_cache.get("connection_status", {})
        local_llm_check = services.schema_cache.get("local_llm_status", services.schema_cache.get("ollama_status", {}))
        drafts = services.drafts.list(limit=500)
        awaiting = sum(1 for draft in drafts if draft["approval_status"] == "awaiting_approval" and not draft["expired"])
        return {
            "emergency_stop": services.emergency.status(),
            "freshdesk": {
                "configured": settings.freshdesk_configured,
                "connected": freshdesk_check.get("connected", False),
                "domain": settings.freshdesk_domain,
            },
            "local_llm": {
                "url": settings.ollama_url,
                "model": settings.ollama_model,
                "provider": local_llm_check.get("provider", settings.local_llm_provider),
                "connected": local_llm_check.get("connected", False),
            },
            "schema": {"last_sync": schema_overview["last_sync"]},
            "rate_limit": services.limiter.status(),
            "drafts_awaiting_approval": awaiting,
            "local_only": True,
        }

    @app.post("/api/admin/emergency-stop")
    def emergency_stop(body: ConfirmationRequest) -> dict[str, object]:
        return services.emergency.activate(body.confirmation)

    @app.post("/api/admin/resume")
    def emergency_resume(body: ConfirmationRequest) -> dict[str, object]:
        return services.emergency.resume(body.confirmation)

    @app.get("/api/settings")
    def get_settings() -> dict[str, object]:
        return services.settings().safe_dict()

    @app.put("/api/settings")
    def update_settings(body: SettingsUpdateRequest) -> dict[str, object]:
        values = body.model_dump(exclude_none=True)
        services.db.set_overrides(values)
        services.audit.record("settings_updated", "local", request_summary=", ".join(sorted(values)))
        return services.settings().safe_dict()

    @app.get("/api/rate-limit/status")
    def rate_limit_status() -> dict[str, int]:
        return services.limiter.status()

    @app.get("/api/audit")
    def audit(limit: int = Query(default=100, ge=1, le=500), action_mode: str | None = None):
        return services.audit.list(limit=limit, action_mode=action_mode)

    @app.post("/api/freshdesk/test")
    def freshdesk_test():
        result = services.freshdesk.test_connection()
        services.schema_cache.put("connection_status", result)
        return result

    @app.post("/api/freshdesk/sync-schema")
    def freshdesk_sync_schema():
        services.emergency.require_clear()
        return services.schema.sync()

    @app.get("/api/freshdesk/schema")
    def freshdesk_schema():
        services.emergency.require_clear()
        overview = services.schema_cache.overview()
        return {**overview, "required_fields": services.schema_cache.required_ticket_fields()}

    @app.get("/api/v1/metadata")
    def agent_metadata():
        services.emergency.require_clear()
        return services.agent.metadata()

    @app.post("/api/v1/drafts")
    def agent_create_draft(body: AgentDraftEnvelope):
        services.emergency.require_clear()
        return services.agent.create(body)

    @app.get("/api/v1/drafts/{draft_id}")
    def agent_get_draft(draft_id: str):
        services.emergency.require_clear()
        return services.agent.get(draft_id)

    @app.patch("/api/v1/drafts/{draft_id}")
    def agent_update_draft(draft_id: str, body: AgentDraftPatch):
        services.emergency.require_clear()
        return services.agent.update(draft_id, body)

    @app.post("/api/v1/drafts/{draft_id}/validate")
    def agent_validate_draft(draft_id: str):
        services.emergency.require_clear()
        return services.agent.validate(draft_id)

    @app.post("/api/v1/drafts/{draft_id}/approve-and-submit")
    def agent_approve_and_submit(draft_id: str):
        services.emergency.require_clear()
        return services.agent.approve_and_submit(draft_id)

    @app.post("/api/v1/feedback/approved-drafts")
    def agent_feedback(body: AgentFeedbackRequest):
        services.emergency.require_clear()
        return services.agent.record_feedback(body)

    @app.get("/api/freshdesk/groups")
    def freshdesk_groups():
        services.emergency.require_clear()
        return services.schema_cache.get("groups", [])

    @app.get("/api/freshdesk/agents")
    def freshdesk_agents():
        services.emergency.require_clear()
        return services.schema_cache.get("agents", [])

    @app.get("/api/freshdesk/ticket-fields")
    def freshdesk_ticket_fields():
        services.emergency.require_clear()
        return services.schema_cache.ticket_fields()

    @app.post("/api/freshdesk/search-contacts")
    def freshdesk_search_contacts(body: SearchRequest):
        return services.freshdesk.search_contacts(body.query)

    @app.post("/api/freshdesk/search-companies")
    def freshdesk_search_companies(body: SearchRequest):
        return services.freshdesk.search_companies(body.query)

    @app.post("/api/local-llm/test")
    @app.post("/api/ollama/test", include_in_schema=False)
    def local_llm_test():
        result = services.local_llm.test_connection()
        services.schema_cache.put("local_llm_status", result)
        return result

    @app.get("/api/local-llm/models")
    def local_llm_models():
        return services.local_llm.list_models()

    @app.post("/api/local-llm/rewrite")
    @app.post("/api/ollama/rewrite")
    def local_llm_rewrite(body: RewriteRequest):
        services.emergency.require_clear()
        return {"text": services.local_llm.rewrite(body.text)}

    @app.post("/api/local-llm/structure-change")
    @app.post("/api/ollama/structure-change")
    def local_llm_structure_change(body: RewriteRequest):
        services.emergency.require_clear()
        return {"text": services.local_llm.structure_change(body.text)}

    @app.post("/api/local-llm/summarise")
    @app.post("/api/ollama/summarise")
    def local_llm_summarise(body: SummariseRequest):
        return {"text": services.local_llm.summarise(body.text)}

    @app.post("/api/local-llm/suggest-ticket")
    def local_llm_suggest_ticket(body: DraftSuggestionRequest):
        services.emergency.require_clear()
        if body.kind == "change":
            return services.changes.suggest(body.text)
        return services.assistant.suggest(body.kind, body.text)

    @app.post("/api/local-llm/suggest-change")
    def local_llm_suggest_change(body: ChangeSuggestionRequest):
        services.emergency.require_clear()
        return services.changes.suggest(body.text)

    @app.get("/api/local-llm/change-skill")
    def local_llm_change_skill():
        return services.change_skill.overview()

    @app.get("/api/local-llm/skills")
    def local_llm_skills():
        return {"active_change_skill": services.change_skill.skill_id, "skills": services.skill_registry.list()}

    @app.get("/api/local-llm/skills/{skill_id}")
    def local_llm_skill(skill_id: str):
        try:
            return services.skill_registry.get(skill_id).overview()
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/tickets/render-change")
    def ticket_render_change(body: ChangeRenderRequest):
        services.emergency.require_clear()
        return services.changes.render(body.change_document)

    @app.get("/api/tickets/defaults")
    def ticket_defaults(kind: str = Query(default="generic", pattern="^(generic|change)$")):
        services.emergency.require_clear()
        return services.defaults.defaults(kind)

    @app.post("/api/tickets/draft")
    def ticket_draft(body: TicketDraftRequest):
        services.emergency.require_clear()
        return services.drafts.create(services.defaults.apply(body.model_dump(), "generic"), kind="generic")

    @app.post("/api/tickets/draft-change")
    def ticket_draft_change(body: ChangeDraftRequest):
        services.emergency.require_clear()
        values = services.defaults.apply(body.model_dump(), "change")
        values, generated_output = services.changes.prepare_draft(values)
        if not values["description"]:
            values["description"] = render_change_description(values)
        return services.drafts.create(values, kind="change", generated_output=generated_output)

    @app.post("/api/tickets/draft-batch")
    def ticket_draft_batch(body: BatchDraftRequest):
        services.emergency.require_clear()
        return services.drafts.create_batch(body.model_dump())

    @app.get("/api/tickets/drafts")
    def ticket_drafts():
        services.emergency.require_clear()
        return services.drafts.list()

    @app.get("/api/tickets/drafts/{draft_id}")
    def ticket_draft_get(draft_id: str):
        services.emergency.require_clear()
        return services.drafts.get(draft_id)

    @app.put("/api/tickets/drafts/{draft_id}")
    def ticket_draft_update(draft_id: str, body: DraftUpdateRequest):
        services.emergency.require_clear()
        return services.drafts.update(draft_id, body.model_dump(exclude_unset=True))

    @app.delete("/api/tickets/drafts/{draft_id}", status_code=204)
    def ticket_draft_delete(draft_id: str):
        services.emergency.require_clear()
        services.drafts.delete(draft_id)

    @app.post("/api/tickets/drafts/{draft_id}/validate")
    def ticket_draft_validate(draft_id: str):
        services.emergency.require_clear()
        return services.drafts.validate(draft_id)

    def create_one(draft_id: str) -> dict[str, Any]:
        draft = services.drafts.validate(draft_id)
        if draft["approval_status"] == "created":
            raise HTTPException(status_code=409, detail="This draft has already created a Freshdesk ticket.")
        if draft["expired"]:
            raise HTTPException(status_code=410, detail="Draft expired. Create a fresh draft before approval.")
        if not draft["validation_result"]["valid"]:
            services.audit.record(
                "ticket_create_blocked",
                "write",
                draft_id=draft_id,
                ticket_subject=draft["payload"].get("subject"),
                validation_result=draft["validation_result"],
                approval_result="blocked",
            )
            raise HTTPException(status_code=422, detail={"message": "Draft validation failed.", **draft["validation_result"]})
        result = services.freshdesk.create_ticket(draft["payload"])
        created = services.drafts.mark_created(draft_id, result)
        services.audit.record(
            "ticket_created",
            "write",
            draft_id=draft_id,
            ticket_id=result.get("id"),
            ticket_subject=draft["payload"].get("subject"),
            validation_result=draft["validation_result"],
            approval_result="approved",
            api_result={"id": result.get("id"), "status": "created"},
        )
        return created

    @app.post("/api/tickets/drafts/{draft_id}/approve-create")
    def ticket_draft_approve_create(draft_id: str, body: ConfirmationRequest):
        services.emergency.require_clear()
        if body.confirmation != "CREATE":
            raise HTTPException(status_code=400, detail='Type "CREATE" to approve this exact draft.')
        return create_one(draft_id)

    @app.post("/api/tickets/batch/{batch_id}/approve-create")
    def ticket_batch_approve_create(batch_id: str, body: BatchCreateRequest):
        services.emergency.require_clear()
        if body.confirmation != "CREATE BATCH":
            raise HTTPException(status_code=400, detail='Type "CREATE BATCH" to approve selected drafts.')
        if len(set(body.draft_ids)) != len(body.draft_ids):
            raise HTTPException(status_code=422, detail="A draft can be selected only once per batch.")
        drafts = [services.drafts.get(draft_id) for draft_id in body.draft_ids]
        if any(draft["batch_id"] != batch_id for draft in drafts):
            raise HTTPException(status_code=422, detail="Every selected draft must belong to this batch.")
        validated = [services.drafts.validate(draft["draft_id"]) for draft in drafts]
        if any(draft["expired"] for draft in validated):
            raise HTTPException(status_code=410, detail="At least one selected batch draft has expired.")
        if any(not draft["validation_result"]["valid"] for draft in validated):
            raise HTTPException(status_code=422, detail="Every selected batch draft must pass validation.")
        services.limiter.ensure_available("write", "ticket_create", amount=len(drafts))
        created = [create_one(draft["draft_id"]) for draft in drafts]
        services.audit.record("batch_created", "write", request_summary=f"{len(created)} tickets", approval_result="approved")
        return {"batch_id": batch_id, "created": created}

    @app.get("/api/tickets/related-to-me")
    def tickets_related_to_me():
        services.emergency.require_clear()
        return services.related.list()

    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="frontend-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def frontend(full_path: str):
            requested = frontend_dist / full_path
            if full_path and requested.is_file():
                return FileResponse(requested)
            return FileResponse(frontend_dist / "index.html")

    return app


app = create_app()
