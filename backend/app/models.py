from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .change_models import ChangeDocument


class ConfirmationRequest(BaseModel):
    confirmation: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class RewriteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class SummariseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=30000)


class DraftSuggestionRequest(BaseModel):
    kind: Literal["generic", "change"] = "generic"
    text: str = Field(min_length=1, max_length=20000)


class TicketDraftRequest(BaseModel):
    subject: str = ""
    description: str = ""
    rough_notes: str = ""
    requester_email: str = ""
    requester_name: str = ""
    priority: int = 1
    status: int = 2
    source: int = 2
    group_id: int | None = None
    company_id: int | None = None
    type: str | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)
    affected_site: str = ""
    target_date: str = ""


class ChangeDraftRequest(TicketDraftRequest):
    reason_for_change: str = ""
    scope: str = ""
    technical_plan: str = ""
    implementation_steps: str = ""
    risk: str = ""
    impact: str = ""
    rollback_plan: str = ""
    validation_plan: str = ""
    proposed_date_time: str = ""
    affected_users_sites_services: str = ""
    communications_required: str = ""
    dependencies: str = ""
    notes: str = ""
    change_document: ChangeDocument | None = None
    assumptions: list[str] = Field(default_factory=list)
    skill_version: str = ""


class DraftUpdateRequest(BaseModel):
    subject: str | None = None
    description: str | None = None
    requester_email: str | None = None
    requester_name: str | None = None
    priority: int | None = None
    status: int | None = None
    source: int | None = None
    group_id: int | None = None
    company_id: int | None = None
    type: str | None = None
    custom_fields: dict[str, Any] | None = None
    affected_site: str | None = None
    target_date: str | None = None


class BatchDraftRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100000)
    base_subject: str = "New user request"
    base_description: str = "Please process the following new user request."
    requester_email: str = ""
    priority: int = 1
    status: int = 2
    source: int = 2
    group_id: int | None = None
    company_id: int | None = None
    type: str | None = None
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class BatchCreateRequest(BaseModel):
    draft_ids: list[str] = Field(min_length=1)
    confirmation: str


class SettingsUpdateRequest(BaseModel):
    local_llm_url: str | None = None
    local_llm_model: str | None = None
    local_llm_provider: Literal["auto", "ollama", "openai-compatible"] | None = None
    local_llm_generation_timeout_seconds: int | None = Field(default=None, ge=30, le=1800)
    max_writes_per_hour: int | None = Field(default=None, ge=1, le=500)
    max_reads_per_hour: int | None = Field(default=None, ge=1, le=2000)
    max_ticket_creations_per_hour: int | None = Field(default=None, ge=1, le=500)
    draft_expiry_minutes: int | None = Field(default=None, ge=1, le=1440)


class AgentSource(BaseModel):
    id: str
    kind: str = "note"
    title: str = ""
    ref: str = ""
    snippet: str = ""


class AgentAssumption(BaseModel):
    id: str
    text: str


class AgentMissingInformation(BaseModel):
    field: str
    reason: str


class AgentTicketField(BaseModel):
    key: str
    label: str = ""
    kind: Literal["short_text", "enum", "entity_ref", "long_text"] = "short_text"
    schema_field_name: str = ""
    payload_path: str = ""
    value: Any = None
    display_value: str = ""
    resolved_id: int | str | None = None
    email: str = ""
    company_id: int | str | None = None
    other_company_ids: list[int | str] = Field(default_factory=list)
    record: dict[str, Any] = Field(default_factory=dict)
    required: bool = False
    choices: list[Any] = Field(default_factory=list)
    field_errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: Literal["confirmed", "inferred", "missing", "conflict", "needs_human_choice", "approved"] = "inferred"
    confidence: float | None = Field(default=None, ge=0, le=1)
    why_this_value: str = ""
    source_ids: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(default_factory=list)
    missing_reason: str = ""
    source: Literal["default", "ai_agent", "freshdesk_metadata", "user_edit"] = "ai_agent"


class AgentDescriptionSection(BaseModel):
    key: str
    title: str = ""
    content: str = ""
    status: Literal["confirmed", "inferred", "missing", "conflict", "needs_human_choice", "approved"] = "inferred"
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_ids: list[str] = Field(default_factory=list)
    assumption_ids: list[str] = Field(default_factory=list)


class AgentRevision(BaseModel):
    number: int = 1
    created_by: str = "ai_agent"
    events: list[dict[str, Any]] = Field(default_factory=list)


class AgentValidation(BaseModel):
    warnings: list[str] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    valid: bool = True


class AgentBulkItem(BaseModel):
    row_id: str = ""
    title: str = ""
    ticket_profile: Literal["standard", "change"] | None = None
    ticket_fields: list[AgentTicketField] = Field(default_factory=list)
    description_sections: list[AgentDescriptionSection] = Field(default_factory=list)
    rendered_description: str = ""
    sources: list[AgentSource] = Field(default_factory=list)
    assumptions: list[AgentAssumption] = Field(default_factory=list)
    missing_information: list[AgentMissingInformation] = Field(default_factory=list)
    validation: AgentValidation = Field(default_factory=AgentValidation)


class AgentDraftEnvelope(BaseModel):
    schema_version: Literal["a24.freshdesk_draft.v1"]
    draft_id: str = ""
    mode: Literal["create", "update", "bulk_create"] = "create"
    ticket_profile: Literal["standard", "change"] = "change"
    status: Literal["ready_for_review", "ready_with_gaps", "blocked", "conflict"] = "ready_for_review"
    target_ticket_id: int | str | None = None
    ticket_fields: list[AgentTicketField] = Field(default_factory=list)
    description_sections: list[AgentDescriptionSection] = Field(default_factory=list)
    bulk_items: list[AgentBulkItem] = Field(default_factory=list)
    rendered_description: str = ""
    sources: list[AgentSource] = Field(default_factory=list)
    assumptions: list[AgentAssumption] = Field(default_factory=list)
    missing_information: list[AgentMissingInformation] = Field(default_factory=list)
    validation: AgentValidation = Field(default_factory=AgentValidation)
    revision: AgentRevision = Field(default_factory=AgentRevision)


class AgentDraftPatch(BaseModel):
    edited_by: str = "kb"
    reason: str = ""
    ticket_fields: list[AgentTicketField] | None = None
    description_sections: list[AgentDescriptionSection] | None = None


class AgentApprovalRequest(BaseModel):
    confirmation: str


class AgentFeedbackRequest(BaseModel):
    schema_version: str = "a24.freshdesk_feedback.v1"
    draft_id: str
    ticket_id: str | int | None = None
    final_fields: dict[str, Any] = Field(default_factory=dict)
    freshdesk_payload: dict[str, Any] = Field(default_factory=dict)
    final_description_sections: dict[str, Any] = Field(default_factory=dict)
    changed_fields: list[dict[str, Any]] = Field(default_factory=list)
    final_selected: dict[str, Any] = Field(default_factory=dict)
