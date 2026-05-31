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
