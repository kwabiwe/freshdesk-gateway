from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .change_models import ChangeDocument


FIELD_INTENTS = {
    "background": ["background", "reason for change", "change reason", "business reason"],
    "change_description": ["change description", "description", "scope", "summary"],
    "implementation_steps": ["implementation plan", "implementation", "technical plan", "plan"],
    "rollback": ["rollback plan", "rollback", "backout plan", "backout", "revert"],
    "verification": ["verification plan", "verification", "validation", "test plan", "testing"],
    "risk": ["change risk", "risk"],
    "impact": ["business impact", "service impact", "impact"],
    "planned_start": ["planned start", "start time", "start date", "change start"],
    "planned_end": ["planned end", "end time", "end date", "change end"],
    "change_type": ["change type"],
    "workflow_state": ["change state", "workflow state"],
    "approval_state": ["approval state"],
    "customer": ["customer", "client"],
    "environment": ["environment", "env"],
    "communication_plan": ["communications required", "communication plan", "communication"],
    "dependencies": ["dependencies", "prerequisites", "dependency"],
}
DEFAULT_API_FIELDS = {"subject", "description", "email", "name", "priority", "status", "source", "group_id", "company_id", "type"}


def _normalise(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def _compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _is_tbd(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() in {"", "tbd", "not provided", "unknown"}


def _lines(values: list[str]) -> str:
    return "\n".join(f"{index}. {value}" for index, value in enumerate(values, start=1))


@dataclass
class MappingResult:
    suggestions: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    low_confidence_fields: list[str] = field(default_factory=list)


class FreshdeskFieldMapper:
    """Map a structured change into discovered Freshdesk fields without trusting arbitrary model keys."""

    def __init__(self, schema_context: dict[str, Any]):
        self.context = schema_context
        self.fields = schema_context.get("fields", [])
        self.fields_by_name = {str(field.get("name")): field for field in self.fields}

    @staticmethod
    def _choice(field: dict[str, Any], preferred: Any) -> str | None:
        if preferred in (None, ""):
            return None
        wanted = _compact(preferred)
        aliases = {"emergency": {"emergency", "emmergency"}}
        accepted = aliases.get(wanted, {wanted})
        return next((str(choice) for choice in field.get("choices", []) if _compact(choice) in accepted), None)

    @staticmethod
    def _intent(field: dict[str, Any]) -> str | None:
        haystack = _normalise(f"{field.get('name', '')} {field.get('label', '')}")
        matches = [
            (len(alias), intent)
            for intent, aliases in FIELD_INTENTS.items()
            for alias in aliases
            if _normalise(alias) in haystack
        ]
        return max(matches, default=(0, None))[1]

    @staticmethod
    def _rollback(document: ChangeDocument) -> str:
        blocks = []
        for branch in document.rollback_branches:
            steps = _lines(branch.steps) if branch.steps else "TBD"
            blocks.append(f"{branch.scenario}:\n{steps}")
        return "\n\n".join(blocks)

    @staticmethod
    def _verification(document: ChangeDocument) -> str:
        return "\n\n".join(
            [
                f"Pre-change verification:\n{_lines(document.verification.pre_change) or 'TBD'}",
                f"In-change verification:\n{_lines(document.verification.in_change) or 'TBD'}",
                f"Post-change verification:\n{_lines(document.verification.post_change) or 'TBD'}",
            ]
        )

    def _intent_values(self, document: ChangeDocument) -> dict[str, str]:
        return {
            "background": document.background,
            "change_description": document.change_description,
            "implementation_steps": _lines(document.implementation_steps),
            "rollback": self._rollback(document),
            "verification": self._verification(document),
            "risk": document.risk if not _is_tbd(document.risk) else document.risk_and_impact,
            "impact": document.impact if not _is_tbd(document.impact) else document.risk_and_impact,
            "planned_start": document.planned_start if not _is_tbd(document.planned_start) else document.planned_change_date,
            "planned_end": document.planned_end,
            "change_type": document.change_type,
            "workflow_state": document.workflow_state,
            "approval_state": "",
            "customer": document.customer,
            "environment": document.environment,
            "communication_plan": _lines(document.communication_plan),
            "dependencies": _lines(document.dependencies),
        }

    def _safe_custom_value(self, field: dict[str, Any], preferred: Any) -> Any:
        if preferred in (None, "", [], {}):
            return None
        if field.get("choices"):
            return self._choice(field, preferred)
        if isinstance(preferred, (str, int, float, bool)):
            text = str(preferred).strip()
            return text[:4000] if text and not _is_tbd(text) else None
        return None

    def _directory_id(self, resource: str, preferred: Any) -> Any:
        if preferred in (None, ""):
            return None
        wanted = _compact(preferred)
        for item in self.context.get(resource, []):
            if str(item.get("id")) == str(preferred) or _compact(item.get("name")) == wanted:
                return item.get("id")
        return None

    def map(
        self,
        document: ChangeDocument,
        rendered_description: str,
        defaults: dict[str, Any],
        *,
        proposed_payload: dict[str, Any] | None = None,
        proposed_custom_fields: dict[str, Any] | None = None,
    ) -> MappingResult:
        proposed_payload = proposed_payload or {}
        custom_fields = dict(defaults.get("custom_fields", {}))
        notes: list[str] = []
        open_questions: list[str] = []
        low_confidence: list[str] = []

        suggestions: dict[str, Any] = {
            "subject": document.title,
            "description": rendered_description,
            "requester_name": defaults.get("requester_name"),
            "requester_email": defaults.get("requester_email"),
            "group_id": defaults.get("group_id"),
            "company_id": defaults.get("company_id"),
            "priority": defaults.get("priority", 1),
            "status": defaults.get("status", 2),
            "source": defaults.get("source", 2),
        }
        for key in ("priority", "status", "source", "type"):
            value = proposed_payload.get(key)
            if value not in (None, "") and (key == "type" or isinstance(value, int)):
                suggestions[key] = value
        for key, resource in (("group_id", "groups"), ("company_id", "companies")):
            preferred = proposed_payload.get(key) or proposed_payload.get(key.removesuffix("_id") + "_name")
            resolved = self._directory_id(resource, preferred)
            if resolved is not None:
                suggestions[key] = resolved
                notes.append(f"Mapped proposed {key} to discovered Freshdesk ID {resolved}.")

        customer_company = self._directory_id("companies", document.customer)
        if customer_company is not None:
            suggestions["company_id"] = customer_company
            notes.append(f"Mapped customer {document.customer} to discovered Freshdesk company ID {customer_company}.")

        for name, preferred in (proposed_custom_fields or {}).items():
            field = self.fields_by_name.get(str(name))
            if not field or not field.get("custom"):
                continue
            value = self._safe_custom_value(field, preferred)
            if value is not None:
                custom_fields[name] = value
                notes.append(f"Accepted proposed Freshdesk field {field['label']} ({name}).")

        values = self._intent_values(document)
        for schema_field in self.fields:
            name = str(schema_field.get("name", ""))
            if not schema_field.get("custom"):
                continue
            intent = self._intent(schema_field)
            preferred = values.get(intent or "")
            if not intent or preferred in (None, "") or _is_tbd(preferred):
                continue
            value = self._safe_custom_value(schema_field, preferred)
            if value is not None:
                if custom_fields.get(name) != value:
                    custom_fields[name] = value
                    notes.append(f"Mapped {intent.replace('_', ' ')} to {schema_field['label']} ({name}).")
            elif schema_field.get("choices"):
                label = schema_field.get("label") or name
                low_confidence.append(name)
                if intent == "customer" and custom_fields.get(name) not in (None, ""):
                    custom_fields.pop(name, None)
                    notes.append(f"Cleared the default value for {label} ({name}) because it did not match the generated customer.")
                if schema_field.get("required_for_agents") or schema_field.get("required_for_customers"):
                    open_questions.append(f"Select an allowed value for required dropdown {label}.")

        suggestions["custom_fields"] = custom_fields
        return MappingResult(
            suggestions=suggestions,
            notes=list(dict.fromkeys(notes)),
            open_questions=list(dict.fromkeys(open_questions)),
            low_confidence_fields=list(dict.fromkeys(low_confidence)),
        )
