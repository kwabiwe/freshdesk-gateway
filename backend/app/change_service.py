from __future__ import annotations

import calendar
import json
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException

from .change_models import ChangeDocument, ChangeGenerationResult
from .change_renderer import render_change_html
from .freshdesk_field_mapper import FreshdeskFieldMapper
from .local_llm_client import LocalLLMClient
from .models import (
    AgentAssumption,
    AgentDescriptionSection,
    AgentDraftEnvelope,
    AgentMissingInformation,
    AgentSource,
    AgentTicketField,
)
from .schema_cache import SchemaCache
from .schema_context import SchemaContextBuilder
from .skill_registry import LocalSkill, SkillRegistry
from .ticket_defaults import TicketDefaultsService
from .ticket_templates import clean_ticket_payload
from .validators import TicketValidator


def _normalise(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _lines(values: list[str]) -> str:
    return "\n".join(str(value).strip() for value in values if str(value).strip())


def _display_status(value: Any) -> str:
    if isinstance(value, int):
        return {2: "Open", 3: "Pending", 4: "Resolved", 5: "Closed"}.get(value, str(value))
    return str(value or "")


def _display_priority(value: Any) -> str:
    if isinstance(value, int):
        return {1: "Low", 2: "Medium", 3: "High", 4: "Urgent"}.get(value, str(value))
    return str(value or "")


class ChangeService:
    def __init__(
        self,
        local_llm: LocalLLMClient,
        schema: SchemaCache,
        defaults: TicketDefaultsService,
        skill: LocalSkill | None = None,
        validator: TicketValidator | None = None,
        now_provider=None,
    ):
        self.local_llm = local_llm
        self.schema = schema
        self.defaults = defaults
        self.skill = skill or SkillRegistry().get("change_management_drafting")
        self.validator = validator or TicketValidator(schema)
        self.context_builder = SchemaContextBuilder(schema)
        self.now_provider = now_provider or (lambda: datetime.now().astimezone())

    def _skill_guidance(self) -> str:
        headings = {
            "Primary Objective",
            "Evidence Handling Rules",
            "Date and Time Rules",
            "Tone and Writing Style",
            "Change Classification Rules",
            "Assumption Rules",
            "Unknowns and TBD Rules",
            "Freshdesk Gateway Behaviour",
        }
        selected: list[str] = []
        active = False
        for line in self.skill.instructions().splitlines():
            if line.startswith("## "):
                active = line[3:].strip() in headings
            if active:
                selected.append(line)
        return "\n".join(selected)[:14000]

    @staticmethod
    def _contract() -> dict[str, Any]:
        return {
            "change_document": {
                "title": "string",
                "change_type": "Normal|Standard|Emergency",
                "workflow_state": "string",
                "planned_change_date": "string",
                "planned_start": "string",
                "planned_end": "string",
                "customer": "string",
                "environment": "string",
                "configuration_items": [
                    {
                        "name": "string",
                        "item_type": "string",
                        "site_location": "string",
                        "purpose": "string",
                        "version": "string",
                    }
                ],
                "background": "string",
                "change_description": "string",
                "implementation_steps": ["string"],
                "rollback_branches": [{"scenario": "string", "steps": ["string"]}],
                "verification": {"pre_change": ["string"], "in_change": ["string"], "post_change": ["string"]},
                "risk": "string",
                "impact": "string",
                "risk_and_impact": "string",
                "risks_and_mitigations": [{"risk": "string", "mitigation": "string"}],
                "communication_plan": ["string"],
                "expected_outcome": "string",
                "success_criteria": ["string"],
                "dependencies": ["string"],
                "assumptions": ["string"],
                "open_questions": ["string"],
                "field_mapping_notes": ["string"],
                "tbd_fields": ["string"],
            },
            "freshdesk_payload": {
                "group_name": "exact discovered group name or omit",
                "priority": "integer 1..4 or omit",
                "status": "integer or omit",
                "type": "string or omit",
            },
            "custom_fields": {"discovered_cf_api_name": "exact allowed dropdown choice or concise text"},
            "assumptions": ["string"],
            "open_questions": ["string"],
            "field_mapping_notes": ["string"],
        }

    def _prompt(self, notes: str) -> str:
        now = self.now_provider()
        context = self.context_builder.compact_json()
        return (
            f"ACTIVE LOCAL SKILL: {self.skill.name} v{self.skill.version}\n\n"
            f"{self._skill_guidance()}\n\n"
            "TASK:\n"
            "Interpret the source notes into a complete operational change record and propose Freshdesk field values. "
            "First extract facts mentally, then generate the JSON result. Preserve technical values exactly. "
            "Use only Freshdesk API field names present in the supplied schema context. Use exact allowed dropdown "
            "choices when choices are supplied. Use TBD for unsupported required values and add a clear open question. "
            "Treat the Freshdesk Change Request form as the target review form: Product, Company when required, Contact, "
            "Subject, Form, Background for the Change, Change Type, Requested By, Change owner, Change Category, "
            "CHG Business Impact, Change State, Approval State, Ticket Type, Status, Business Impact, Group, Agent, "
            "Priority, Customer, Reminder Date, Tags, and one rich Description field. Do not invent Contact, Company, "
            "Agent, Group, Product, or Customer records. Use exact discovered dropdown values where available, and leave "
            "relationship fields unresolved when the notes do not identify an existing Freshdesk record. The gateway will "
            "force the human reviewer to select existing Freshdesk Contact and Company records before submission. "
            "Record every meaningful inference as an assumption. Do not invent IPs, ports, timings, approvers, versions, "
            "engineers, customer contacts, access methods, or completed checks. Return one JSON object only.\n\n"
            f"LOCAL DATE AND TIMEZONE: {now.strftime('%A %d %B %Y %Z')}\n"
            f"CONFIGURED REQUESTER: {json.dumps(self.defaults.defaults('change')['identity'], separators=(',', ':'))}\n"
            f"FRESHDESK SCHEMA CONTEXT: {context}\n"
            f"REQUIRED FRESHDESK FIELDS: {json.dumps(self.context_builder.build()['required_fields'], separators=(',', ':'))}\n"
            f"JSON OUTPUT CONTRACT: {json.dumps(self._contract(), separators=(',', ':'))}\n\n"
            f"SOURCE NOTES:\n{notes}"
        )

    def _fallback_document(self, notes: str, assumptions: list[str] | None = None) -> ChangeDocument:
        return ChangeDocument(
            title="Change request",
            background=notes.strip() or "TBD",
            change_description=notes.strip() or "TBD",
            assumptions=assumptions or ["The local model response was incomplete. Review and complete the generated sections."],
        )

    def _generation(self, raw: Any, notes: str) -> ChangeGenerationResult:
        if not isinstance(raw, dict):
            return ChangeGenerationResult(change_document=self._fallback_document(notes))
        try:
            generation = ChangeGenerationResult.model_validate(raw)
        except Exception:
            return ChangeGenerationResult(change_document=self._fallback_document(notes))
        document = generation.change_document
        if document.background.strip().lower() in {"null", "tbd"}:
            document.background = notes.strip() or "TBD"
        if document.change_description.strip().lower() in {"null", "tbd"}:
            document.change_description = notes.strip() or "TBD"
        return generation

    def _resolve_relative_date(self, notes: str, document: ChangeDocument) -> None:
        match = re.search(r"\b(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", notes, re.I)
        if not match:
            return
        now = self.now_provider()
        target = list(calendar.day_name).index(match.group(2).title())
        days = (target - now.weekday()) % 7 or 7
        resolved = now + timedelta(days=days)
        value = f"{resolved.strftime('%A')} {resolved.day} {resolved.strftime('%B %Y')}"
        if document.planned_change_date.strip().lower() in {"", "tbd", match.group(0).lower()}:
            document.planned_change_date = value
        if re.search(rf"\b{match.group(2)}\s+(night|evening|morning|afternoon)\b", notes, re.I):
            if document.planned_start.strip().lower() == "tbd":
                document.planned_start = f"{value}, time TBD"
            document.open_questions.append(f"Confirm the exact start time for the planned change on {value}.")
        assumption = f'Interpreted "{match.group(0)}" as {value} using the local timezone.'
        document.assumptions.append(assumption)

    @staticmethod
    def _extract_customer(notes: str, document: ChangeDocument) -> None:
        if document.customer.strip().lower() != "tbd":
            return
        match = re.search(r"\bfor\s+([A-Z][A-Za-z0-9_-]*(?:\s+[A-Z][A-Za-z0-9_-]*){0,3})\b", notes)
        if match:
            document.customer = match.group(1).strip()

    @staticmethod
    def _document_defaults(notes: str, document: ChangeDocument) -> None:
        if re.search(r"\bemergenc(?:y|ies)\b", notes, re.I):
            document.change_type = "Emergency"
        elif re.search(r"\bstandard\b", notes, re.I):
            document.change_type = "Standard"
        elif not document.change_type or document.change_type == "TBD":
            document.change_type = "Normal"

        workflow_match = re.search(
            r"\b(approved|rejected|pending approval|in progress|on[- ]hold)\b(?:\s+workflow\s+state)?",
            notes,
            re.I,
        )
        if workflow_match:
            workflow_states = {
                "approved": "Approved",
                "rejected": "Rejected",
                "pending approval": "Pending approval",
                "in progress": "In Progress",
                "on-hold": "On Hold",
                "on hold": "On Hold",
            }
            document.workflow_state = workflow_states[workflow_match.group(1).lower()]
        elif not document.workflow_state or document.workflow_state == "TBD":
            document.workflow_state = "Pending approval"

        if document.risk == "TBD":
            if re.search(r"\b(hsm|encryption|authentication|routing|firewall|load balancer|financial|internet edge)\b", notes, re.I):
                document.risk = "High"
            elif re.search(r"\b(non[- ]production|monitoring[- ]only|documentation[- ]only|no[- ]impact)\b", notes, re.I):
                document.risk = "Low"
            elif re.search(r"\bproduction\b", notes, re.I):
                document.risk = "Medium"
            if document.risk != "TBD":
                document.assumptions.append(f"Assumed change risk is {document.risk} based on the supplied technical scope.")

    def _tbd_fields(self, document: ChangeDocument) -> list[str]:
        values = document.model_dump()
        found: list[str] = []

        def walk(value: Any, path: str) -> None:
            if isinstance(value, str) and value.strip().lower() in {"tbd", "unknown", "not provided"}:
                found.append(path)
            elif isinstance(value, dict):
                for key, nested in value.items():
                    walk(nested, f"{path}.{key}" if path else key)
            elif isinstance(value, list):
                for index, nested in enumerate(value):
                    walk(nested, f"{path}[{index}]")

        walk(values, "")
        return _unique([re.sub(r"\[\d+\]", "", path) for path in [*document.tbd_fields, *found]])

    def _response(self, notes: str, generation: ChangeGenerationResult) -> dict[str, Any]:
        document = generation.change_document
        self._extract_customer(notes, document)
        self._resolve_relative_date(notes, document)
        self._document_defaults(notes, document)
        rendered = render_change_html(document)
        context = self.context_builder.build()
        proposed_custom = {**document.freshdesk_fields, **generation.custom_fields}
        mapped = FreshdeskFieldMapper(context).map(
            document,
            rendered,
            self.defaults.defaults("change"),
            proposed_payload=generation.freshdesk_payload,
            proposed_custom_fields=proposed_custom,
        )
        validation = self.validator.validate(clean_ticket_payload(mapped.suggestions))
        missing = [*generation.missing_required_fields, *validation["missing_fields"]]
        missing_by_name = {str(item.get("name")): item for item in missing}
        tbd_fields = self._tbd_fields(document)
        open_questions = _unique(
            [
                *generation.open_questions,
                *document.open_questions,
                *mapped.open_questions,
                *(f"Complete required Freshdesk field: {item.get('label') or item.get('name')}." for item in missing_by_name.values()),
            ]
        )
        notes_out = _unique([*generation.field_mapping_notes, *document.field_mapping_notes, *mapped.notes])
        assumptions = _unique([*generation.assumptions, *document.assumptions])
        return {
            "change_document": document.model_dump(),
            "rendered_description": rendered,
            "suggestions": mapped.suggestions,
            "assumptions": assumptions,
            "open_questions": open_questions,
            "field_mapping_notes": notes_out,
            "missing_required_fields": list(missing_by_name.values()),
            "tbd_fields": tbd_fields,
            "low_confidence_fields": mapped.low_confidence_fields,
            "validation_preview": validation,
            "skill_id": self.skill.skill_id,
            "skill_version": self.skill.version,
        }

    def agent_envelope_from_notes(self, notes: str) -> AgentDraftEnvelope:
        result = self.suggest(notes)
        return self._agent_envelope(notes, result)

    def _agent_envelope(self, notes: str, result: dict[str, Any]) -> AgentDraftEnvelope:
        document = ChangeDocument.model_validate(result.get("change_document") or {})
        suggestions = result.get("suggestions") or {}
        custom_fields = suggestions.get("custom_fields") or {}
        defaults = self.defaults.defaults("change")
        identity = defaults.get("identity", {})

        assumptions = [
            AgentAssumption(id=f"asm_{index:03d}", text=text)
            for index, text in enumerate(_unique([*(result.get("assumptions") or []), *document.assumptions]), start=1)
        ]
        assumption_ids = [item.id for item in assumptions]
        missing_items = self._agent_missing_information(result, document)
        sources = [
            AgentSource(
                id="src_rough_notes",
                kind="rough_notes",
                title="Local rough notes",
                snippet=notes.strip()[:900],
            )
        ]

        def custom_value(*names: str) -> Any:
            return next((custom_fields.get(name) for name in names if custom_fields.get(name) not in (None, "")), "")

        def field(
            key: str,
            value: Any,
            *,
            label: str = "",
            kind: str = "short_text",
            required: bool = False,
            confidence: float = 0.8,
            why: str = "",
            schema_field_name: str = "",
            resolved_id: Any = None,
        ) -> AgentTicketField:
            display = "" if value is None else str(value)
            status = "inferred" if display else "missing"
            return AgentTicketField(
                key=key,
                label=label,
                kind=kind,
                schema_field_name=schema_field_name,
                value=value,
                display_value=display,
                resolved_id=resolved_id,
                required=required,
                status=status,
                confidence=confidence if display else None,
                why_this_value=why,
                source_ids=["src_rough_notes"],
                assumption_ids=assumption_ids if display and confidence < 1 else [],
                source="ai_agent",
            )

        group_id = suggestions.get("group_id")
        group = next((item for item in self.schema.get("groups", []) if str(item.get("id")) == str(group_id)), None)
        fields = [
            field("subject", suggestions.get("subject") or document.title, label="Subject", required=True, confidence=0.9, why="Inferred from the rough change notes."),
            field("cf_form2", custom_value("cf_form2") or "Change Request", label="Form", kind="enum", schema_field_name="cf_form2", confidence=1.0, why="Change-style tickets target the Freshdesk Change Request form."),
            field("cf_background_for_the_change", custom_value("cf_background_for_the_change") or document.background, label="Background for the Change", kind="long_text", schema_field_name="cf_background_for_the_change", confidence=0.85, why="Summarises why the change is needed."),
            field("cf_change_type", custom_value("cf_change_type") or document.change_type, label="Change Type", kind="enum", schema_field_name="cf_change_type", confidence=0.75, why="Inferred from explicit change-type language or defaulted conservatively."),
            field("cf_requested_by", custom_value("cf_requested_by") or identity.get("name") or "", label="Requested By", schema_field_name="cf_requested_by", confidence=0.7, why="Defaulted to the configured gateway requester when the notes do not name a requester."),
            field("cf_change_owner", custom_value("cf_change_owner") or identity.get("name") or "", label="Change owner", schema_field_name="cf_change_owner", required=True, confidence=0.7, why="Defaulted to the configured gateway owner for review."),
            field("cf_change_catergory", custom_value("cf_change_catergory", "cf_change_category"), label="Change Category", kind="enum", schema_field_name="cf_change_catergory", confidence=0.55, why="Only filled when the rough notes or model output match a Freshdesk category."),
            field("cf_chg_business_impact", custom_value("cf_chg_business_impact") or document.impact, label="CHG Business Impact", kind="enum", schema_field_name="cf_chg_business_impact", confidence=0.7, why="Inferred from the described customer or operational impact."),
            field("cf_change_state", custom_value("cf_change_state") or document.workflow_state, label="Change State", kind="enum", schema_field_name="cf_change_state", required=True, confidence=0.75, why="Inferred from approval/state language or defaulted to pending review."),
            field("cf_approval_state", custom_value("cf_approval_state"), label="Approval State", kind="enum", schema_field_name="cf_approval_state", confidence=0.65, why="Uses Freshdesk default when available."),
            field("cf_type", custom_value("cf_type") or "Change", label="Ticket Type", kind="enum", schema_field_name="cf_type", confidence=1.0, why="Change-style workflow creates a Change ticket."),
            field("status", _display_status(suggestions.get("status") or 2), label="Status", kind="enum", required=True, confidence=1.0, why="Freshdesk create default."),
            field("cf_business_impact723800", custom_value("cf_business_impact723800", "cf_business_impact") or document.impact, label="Business Impact", kind="enum", schema_field_name="cf_business_impact723800", confidence=0.7, why="Inferred from the described business impact."),
            field("group", group.get("name") if group else "", label="Group", kind="entity_ref", confidence=1.0 if group else 0.5, resolved_id=group_id if group else None, why="Resolved from synced Freshdesk group metadata when available."),
            field("priority", _display_priority(suggestions.get("priority") or 1), label="Priority", kind="enum", required=True, confidence=1.0, why="Freshdesk create default unless rough notes imply otherwise."),
            field("cf_customer967575", custom_value("cf_customer967575", "cf_customer") or document.customer, label="Customer", kind="enum", schema_field_name="cf_customer967575", required=True, confidence=0.7, why="Inferred from the customer named in the rough notes."),
        ]

        sections = self._agent_description_sections(document, result)
        return AgentDraftEnvelope(
            schema_version="a24.freshdesk_draft.v1",
            mode="create",
            ticket_profile="change",
            status="ready_for_review",
            ticket_fields=fields,
            description_sections=sections,
            rendered_description=result.get("rendered_description") or render_change_html(document),
            sources=sources,
            assumptions=assumptions,
            missing_information=missing_items,
        )

    def _agent_missing_information(self, result: dict[str, Any], document: ChangeDocument) -> list[AgentMissingInformation]:
        items: list[AgentMissingInformation] = [
            AgentMissingInformation(field="Contact", reason="Search and select an existing Freshdesk contact before approval."),
        ]
        for field in result.get("missing_required_fields") or []:
            label = str(field.get("label") or field.get("name") or "Freshdesk field")
            items.append(AgentMissingInformation(field=label, reason="Required by the synced Freshdesk Change Request schema."))
        for question in result.get("open_questions") or []:
            items.append(AgentMissingInformation(field="Open question", reason=str(question)))
        for path in [*(result.get("tbd_fields") or []), *document.tbd_fields]:
            items.append(AgentMissingInformation(field=str(path), reason="The local LLM could not determine this from the rough notes."))
        unique: dict[tuple[str, str], AgentMissingInformation] = {}
        for item in items:
            unique[(item.field, item.reason)] = item
        return list(unique.values())

    def _agent_description_sections(self, document: ChangeDocument, result: dict[str, Any]) -> list[AgentDescriptionSection]:
        verification = document.verification
        rollback = "\n".join(
            f"{branch.scenario}: {step}"
            for branch in document.rollback_branches
            for step in branch.steps
        )
        sections = [
            ("background", "Background / reason for change", document.background),
            ("scope", "Scope", document.change_description),
            ("config_items", "Configuration items", "\n".join(
                " | ".join(filter(None, [item.name, item.item_type, item.site_location, item.purpose, item.version]))
                for item in document.configuration_items
            )),
            ("implementation", "Implementation steps", _lines(document.implementation_steps)),
            ("rollback", "Rollback plan", rollback),
            ("verification", "Verification plan", "\n".join(
                value for value in [
                    f"Pre-change: {_lines(verification.pre_change)}" if verification.pre_change else "",
                    f"In-change: {_lines(verification.in_change)}" if verification.in_change else "",
                    f"Post-change: {_lines(verification.post_change)}" if verification.post_change else "",
                ] if value
            )),
            ("risk_impact", "Risk and impact", "\n".join(filter(None, [document.risk, document.impact, document.risk_and_impact]))),
            ("communication", "Communication plan", _lines(document.communication_plan)),
            ("assumptions_missing", "Assumptions / missing information", "\n".join([
                *result.get("assumptions", []),
                *result.get("open_questions", []),
            ])),
        ]
        return [
            AgentDescriptionSection(
                key=key,
                title=title,
                content=content or "TBD",
                status="confirmed" if content and content.strip().lower() != "tbd" else "missing",
                confidence=0.8 if content and content.strip().lower() != "tbd" else None,
            )
            for key, title, content in sections
        ]

    def suggest(self, notes: str) -> dict[str, Any]:
        try:
            raw = self.local_llm.generate_json(self._prompt(notes), notes, max_tokens=5200)
            generation = self._generation(raw, notes)
        except HTTPException as exc:
            if exc.status_code != 502:
                raise
            generation = ChangeGenerationResult(
                change_document=self._fallback_document(
                    notes,
                    [
                        "The selected local model did not return a complete structured document. Review and complete the generated sections.",
                        "Consider selecting a non-reasoning instruction model in Settings for faster structured drafting.",
                    ],
                )
            )
        return self._response(notes, generation)

    def render(self, document: ChangeDocument) -> dict[str, Any]:
        return {
            "rendered_description": render_change_html(document),
            "tbd_fields": self._tbd_fields(document),
            "skill_id": self.skill.skill_id,
            "skill_version": self.skill.version,
        }

    def prepare_draft(self, values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        document_value = values.get("change_document")
        if not document_value:
            return values, ""
        document = ChangeDocument.model_validate(document_value)
        rendered = render_change_html(document)
        mapped = FreshdeskFieldMapper(self.context_builder.build()).map(
            document,
            rendered,
            self.defaults.defaults("change"),
            proposed_custom_fields=values.get("custom_fields") or {},
        )
        provided_values = {
            key: value
            for key, value in values.items()
            if key != "custom_fields" and value not in (None, "", [], {})
        }
        provided_custom_fields = {
            key: value
            for key, value in (values.get("custom_fields") or {}).items()
            if value not in (None, "")
        }
        values = {**mapped.suggestions, **provided_values, "description": rendered}
        values["custom_fields"] = {**mapped.suggestions.get("custom_fields", {}), **provided_custom_fields}
        stored = {
            "change_document": document.model_dump(),
            "assumptions": values.get("assumptions", []),
            "skill_id": self.skill.skill_id,
            "skill_version": values.get("skill_version") or self.skill.version,
        }
        return values, json.dumps(stored)
