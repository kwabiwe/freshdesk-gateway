from __future__ import annotations

import json
import re
from typing import Any

from .schema_cache import SchemaCache


DEFAULT_FIELDS = {
    "requester",
    "subject",
    "description",
    "group",
    "company",
    "agent",
    "status",
    "priority",
    "source",
    "type",
    "ticket_type",
}
CHANGE_TERMS = {
    "approval",
    "background",
    "backout",
    "category",
    "change",
    "client",
    "communication",
    "customer",
    "dependency",
    "description",
    "environment",
    "form",
    "impact",
    "implementation",
    "owner",
    "prerequisite",
    "reason",
    "requested",
    "risk",
    "rollback",
    "scope",
    "state",
    "test",
    "validation",
    "verification",
}


def _normalise(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


class SchemaContextBuilder:
    """Project cached Freshdesk metadata into a compact, tenant-neutral LLM context."""

    def __init__(self, schema: SchemaCache, *, choice_limit: int = 60, record_limit: int = 100):
        self.schema = schema
        self.choice_limit = choice_limit
        self.record_limit = record_limit

    def choice_values(self, choices: Any) -> list[str]:
        values: list[str] = []
        if isinstance(choices, list):
            values.extend(str(value) for value in choices)
        elif isinstance(choices, dict):
            for key, nested in choices.items():
                values.append(str(key))
                if isinstance(nested, (list, dict)):
                    values.extend(self.choice_values(nested))
        return list(dict.fromkeys(values))[: self.choice_limit]

    def compact_field(self, field: dict[str, Any]) -> dict[str, Any]:
        name = str(field.get("name", ""))
        result: dict[str, Any] = {
            "name": name,
            "label": field.get("label") or field.get("label_for_customers") or name,
            "type": field.get("type", "unknown"),
            "required_for_agents": bool(field.get("required_for_agents")),
            "required_for_customers": bool(field.get("required_for_customers")),
            "custom": name.startswith("cf_"),
        }
        choices = self.choice_values(field.get("choices"))
        if choices:
            result["choices"] = choices
        return result

    @staticmethod
    def _change_related(field: dict[str, Any]) -> bool:
        name = _normalise(field.get("name", ""))
        label = _normalise(field.get("label") or field.get("label_for_customers") or "")
        words = set(f"{name} {label}".split())
        return bool(words & CHANGE_TERMS)

    @staticmethod
    def _default_field(field: dict[str, Any]) -> bool:
        return str(field.get("name", "")).lower() in DEFAULT_FIELDS

    @staticmethod
    def _record(item: dict[str, Any]) -> dict[str, Any]:
        return {key: item.get(key) for key in ("id", "name") if item.get(key) not in (None, "")}

    def build(self) -> dict[str, Any]:
        fields = self.schema.ticket_fields()
        required = [self.compact_field(field) for field in fields if field.get("required_for_agents") or field.get("required_for_customers")]
        custom_fields = [self.compact_field(field) for field in fields if str(field.get("name", "")).startswith("cf_")]
        change_related = [self.compact_field(field) for field in fields if self._change_related(field)]
        default_fields = [self.compact_field(field) for field in fields if self._default_field(field)]
        selected = {
            field["name"]: field
            for field in [*required, *custom_fields, *change_related, *default_fields]
            if field.get("name")
        }
        return {
            "required_fields": required,
            "custom_fields": custom_fields,
            "change_related_fields": change_related,
            "default_fields": default_fields,
            "fields": list(selected.values()),
            "groups": [self._record(item) for item in self.schema.get("groups", [])[: self.record_limit]],
            "companies": [self._record(item) for item in self.schema.get("companies", [])[: self.record_limit]],
            "ticket_forms": [self._record(item) for item in self.schema.get("ticket_forms", [])[: self.record_limit]],
        }

    def compact_json(self) -> str:
        return json.dumps(self.build(), separators=(",", ":"))
