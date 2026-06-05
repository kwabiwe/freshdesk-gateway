from __future__ import annotations

import json
from typing import Any

from .schema_cache import SchemaCache
from .sensitive_data import detect_secrets


DEFAULT_FIELD_MAP = {
    "requester": "email",
    "subject": "subject",
    "description": "description",
    "status": "status",
    "priority": "priority",
    "source": "source",
    "group": "group_id",
    "company": "company_id",
    "agent": "responder_id",
    "type": "type",
    "ticket_type": "type",
}


class TicketValidator:
    def __init__(self, schema: SchemaCache):
        self.schema = schema

    @staticmethod
    def _missing(value: Any) -> bool:
        return value is None or value == "" or value == [] or (
            isinstance(value, str) and value.strip().lower() in {"tbd", "not provided", "unknown"}
        )

    def validate(self, payload: dict[str, Any], *, require_requester: bool = True) -> dict[str, Any]:
        missing: list[dict[str, Any]] = []
        warnings: list[str] = []
        required_fields = self.schema.required_ticket_fields()
        for field in required_fields:
            name = field.get("name", "")
            api_name = DEFAULT_FIELD_MAP.get(name, name)
            if not require_requester and api_name in {"email", "requester_id"}:
                continue
            if name.startswith("cf_"):
                value = payload.get("custom_fields", {}).get(name)
            else:
                value = payload.get(api_name)
            if self._missing(value):
                missing.append(
                    {
                        "name": name,
                        "label": field.get("label") or field.get("label_for_customers") or name,
                        "type": field.get("type", "unknown"),
                        "allowed_values": field.get("choices") or [],
                        "user_input_required": True,
                    }
                )

        # Freshdesk's ticket create endpoint needs these API-level values even before a schema sync.
        api_required = [("subject", "Subject"), ("description", "Description")]
        if require_requester:
            api_required.insert(0, ("email", "Requester email"))
        for key, label in api_required:
            if self._missing(payload.get(key)) and not any(item["name"] == key for item in missing):
                missing.append(
                    {"name": key, "label": label, "type": "text", "allowed_values": [], "user_input_required": True}
                )

        findings = detect_secrets(json.dumps(payload, default=str))
        if findings:
            warnings.append("Potential sensitive data detected. Remove or redact it before creation.")

        return {
            "valid": not missing and not findings,
            "missing_fields": missing,
            "sensitive_data_findings": [finding.to_dict() for finding in findings],
            "warnings": warnings,
        }
