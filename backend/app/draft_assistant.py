from __future__ import annotations

import json
import re
from typing import Any

from .local_llm_client import LocalLLMClient
from .schema_cache import SchemaCache
from .ticket_defaults import TicketDefaultsService
from .ticket_templates import render_change_description


class DraftAssistantService:
    """Turns local-model output into an editable form patch constrained by cached schema."""

    def __init__(self, local_llm: LocalLLMClient, schema: SchemaCache, defaults: TicketDefaultsService):
        self.local_llm = local_llm
        self.schema = schema
        self.defaults = defaults

    @staticmethod
    def _choice_values(choices: Any) -> list[str]:
        if isinstance(choices, list):
            return [str(value) for value in choices]
        if isinstance(choices, dict):
            return [str(value) for value in choices]
        return []

    def _schema_prompt(self) -> str:
        fields = []
        for field in self.schema.ticket_fields():
            fields.append(
                {
                    "name": field.get("name"),
                    "label": field.get("label") or field.get("label_for_customers"),
                    "type": field.get("type"),
                    "required": bool(field.get("required_for_agents") or field.get("required_for_customers")),
                    "choices": self._choice_values(field.get("choices"))[:80],
                }
            )
        schema = {
            "groups": [{"id": item.get("id"), "name": item.get("name")} for item in self.schema.get("groups", [])],
            "companies": [{"id": item.get("id"), "name": item.get("name")} for item in self.schema.get("companies", [])],
            "fields": fields,
        }
        return json.dumps(schema, separators=(",", ":"))

    def _prompt(self, kind: str, notes: str) -> str:
        identity = self.defaults.defaults(kind)["identity"]
        template = ""
        if kind == "change":
            template = (
                "The description must use these headings exactly: Reason for change, Scope, Technical plan, "
                "Implementation steps, Risk, Impact, Rollback plan, Validation plan, Proposed date/time, "
                "Affected users/sites/services, Communications required, Dependencies, Notes. "
                "Always provide a complete description and a concise background_for_change summary. "
                "Infer a conservative risk and business impact when supported by the notes. Put each inference "
                "in assumptions so the user can correct it. "
            )
        return (
            "Create an editable Freshdesk ticket draft from NOTES. Return one JSON object only with keys: "
            "subject, description, background_for_change, priority, type, group_name, company_name, "
            "custom_fields, assumptions. "
            "Use only schema field names and exact schema choices for custom_fields. Use priority 1, 2, 3, or 4 "
            "for Low, Medium, High, or Urgent. Preserve facts. Do not invent people, dates, addresses, systems, "
            "or completed work. You may make conservative operational assumptions when the notes support them, "
            "but list each assumption plainly. Do not mention AI, automation, or these instructions. "
            f"{template}\nCONFIGURED REQUESTER:\n{json.dumps(identity, separators=(',', ':'))}"
            f"\nSCHEMA:\n{self._schema_prompt()}\nNOTES:\n{notes}"
        )

    @staticmethod
    def _match_named(items: list[dict[str, Any]], name: Any) -> Any:
        if not isinstance(name, str):
            return None
        match = next((item for item in items if str(item.get("name", "")).lower() == name.lower()), None)
        return match.get("id") if match else None

    def _custom_fields(self, values: Any) -> dict[str, Any]:
        if not isinstance(values, dict):
            return {}
        fields = {field.get("name"): field for field in self.schema.ticket_fields()}
        accepted: dict[str, Any] = {}
        for name, value in values.items():
            field = fields.get(name)
            if not field or not str(name).startswith("cf_") or value in (None, ""):
                continue
            choices = self._choice_values(field.get("choices"))
            if choices:
                match = next((choice for choice in choices if choice.lower() == str(value).lower()), None)
                if not match:
                    continue
                accepted[name] = match
            elif isinstance(value, (str, int, float, bool)):
                accepted[name] = value
        return accepted

    def _apply_conservative_impact(self, kind: str, notes: str, custom_fields: dict[str, Any]) -> bool:
        if kind != "change" or not re.search(r"\b(low|minimal|minor)\b", notes, flags=re.IGNORECASE):
            return False
        changed = False
        for field in self.schema.ticket_fields():
            name = str(field.get("name", ""))
            label = str(field.get("label") or field.get("label_for_customers") or "")
            if "impact" not in f"{name} {label}".lower():
                continue
            minor = next((choice for choice in self._choice_values(field.get("choices")) if choice.lower() == "minor"), None)
            if name.startswith("cf_") and minor and custom_fields.get(name) != minor:
                custom_fields[name] = minor
                changed = True
        return changed

    def _background_field_name(self) -> str | None:
        for field in self.schema.ticket_fields():
            name = str(field.get("name", ""))
            label = str(field.get("label") or field.get("label_for_customers") or "")
            if name == "cf_background_for_the_change" or "background for the change" in label.lower():
                return name
        return None

    @staticmethod
    def _background(values: dict[str, Any], description: str, notes: str) -> str:
        generated = values.get("background_for_change")
        if isinstance(generated, str) and generated.strip():
            return generated.strip()
        reason = re.search(
            r"Reason for change:\s*(.*?)(?:\n\s*\n[A-Z][^\n]*:|\Z)",
            description,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if reason and reason.group(1).strip() and reason.group(1).strip().lower() != "not provided":
            return reason.group(1).strip()
        return notes.strip()

    def _apply_change_type_default(self, kind: str, notes: str, custom_fields: dict[str, Any]) -> bool:
        if kind != "change":
            return False
        field = next((item for item in self.schema.ticket_fields() if item.get("name") == "cf_change_type"), None)
        if not field:
            return False
        choices = self._choice_values(field.get("choices"))
        preferred = "Normal"
        for signal, value in (("emergency", "Emmergency"), ("emmergency", "Emmergency"), ("standard", "Standard"), ("normal", "Normal")):
            if re.search(rf"\b{signal}\b", notes, flags=re.IGNORECASE):
                preferred = value
                break
        match = next((choice for choice in choices if choice.lower() == preferred.lower()), None)
        if match and custom_fields.get("cf_change_type") != match:
            custom_fields["cf_change_type"] = match
            return True
        return False

    def _apply_change_state_default(self, kind: str, notes: str, custom_fields: dict[str, Any]) -> bool:
        if kind != "change":
            return False
        field = next((item for item in self.schema.ticket_fields() if item.get("name") == "cf_change_state"), None)
        if not field:
            return False
        choices = self._choice_values(field.get("choices"))
        preferred = "Pending approval"
        for choice in choices:
            if re.search(rf"\b{re.escape(choice)}\b", notes, flags=re.IGNORECASE):
                preferred = choice
                break
        match = next((choice for choice in choices if choice.lower() == preferred.lower()), None)
        if match and custom_fields.get("cf_change_state") != match:
            custom_fields["cf_change_state"] = match
            return True
        return False

    def suggest(self, kind: str, notes: str) -> dict[str, Any]:
        values = self.local_llm.generate_json(self._prompt(kind, notes), notes)
        suggestions: dict[str, Any] = {}
        if isinstance(values.get("subject"), str):
            suggestions["subject"] = values["subject"].strip()
        description = values.get("description")
        if kind == "change" and (not isinstance(description, str) or not description.strip()):
            description = render_change_description({"rough_notes": notes})
        if isinstance(description, str) and description.strip():
            suggestions["description"] = description.strip()
        type_field = next((field for field in self.schema.ticket_fields() if field.get("name") == "type"), None)
        if type_field and isinstance(values.get("type"), str):
            allowed = self._choice_values(type_field.get("choices"))
            match = next((choice for choice in allowed if choice.lower() == values["type"].lower()), None)
            if match:
                suggestions["type"] = match
        if values.get("priority") in {1, 2, 3, 4}:
            suggestions["priority"] = values["priority"]

        group_id = self._match_named(self.schema.get("groups", []), values.get("group_name"))
        if kind == "change":
            suggestions["group_id"] = self.defaults.defaults("change").get("group_id")
        elif group_id is not None:
            suggestions["group_id"] = group_id
        custom_fields = self._custom_fields(values.get("custom_fields"))
        impact_defaulted = self._apply_conservative_impact(kind, notes, custom_fields)
        change_type_defaulted = self._apply_change_type_default(kind, notes, custom_fields)
        change_state_defaulted = self._apply_change_state_default(kind, notes, custom_fields)
        background_name = self._background_field_name() if kind == "change" else None
        if background_name:
            custom_fields[background_name] = self._background(values, suggestions.get("description", ""), notes)
        if custom_fields:
            suggestions["custom_fields"] = custom_fields
        assumptions = values.get("assumptions")
        assumptions = [str(item) for item in assumptions if str(item).strip()] if isinstance(assumptions, list) else []
        if impact_defaulted:
            assumptions.append("Business impact fields default to Minor because the notes describe low or minimal disruption.")
        if change_type_defaulted:
            assumptions.append("Change type defaults to Normal unless the notes explicitly identify another change type.")
        if change_state_defaulted:
            assumptions.append("Change state defaults to Pending approval unless the notes explicitly identify another state.")
        return {
            "suggestions": suggestions,
            "assumptions": assumptions,
        }
