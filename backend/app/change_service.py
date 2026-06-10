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
                "company_name": "exact discovered company name or omit",
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
