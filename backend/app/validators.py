from __future__ import annotations

import json
from typing import Any

from .schema_cache import SchemaCache
from .sensitive_data import detect_secrets


DEFAULT_FIELD_MAP = {
    "subject": "subject",
    "description": "description",
    "status": "status",
    "priority": "priority",
    "source": "source",
    "group": "group_id",
    "company": "company_id",
    "agent": "responder_id",
    "product": "product_id",
    "type": "type",
    "ticket_type": "type",
}

REQUESTER_FIELDS = {"email", "requester_id"}
ALLOWED_TICKET_FIELDS = {
    "subject",
    "description",
    "email",
    "name",
    "requester_id",
    "priority",
    "status",
    "source",
    "group_id",
    "company_id",
    "responder_id",
    "product_id",
    "type",
    "custom_fields",
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
        invalid_fields = sorted(key for key in payload if key not in ALLOWED_TICKET_FIELDS)
        required_fields = self.schema.required_ticket_fields()
        for field in required_fields:
            name = field.get("name", "")
            api_name = DEFAULT_FIELD_MAP.get(name, name)
            if name == "requester":
                if not require_requester:
                    continue
                value = next((payload.get(key) for key in REQUESTER_FIELDS if not self._missing(payload.get(key))), None)
            elif not require_requester and api_name in REQUESTER_FIELDS:
                continue
            elif name.startswith("cf_"):
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
        for key, label in api_required:
            if self._missing(payload.get(key)) and not any(item["name"] == key for item in missing):
                missing.append(
                    {"name": key, "label": label, "type": "text", "allowed_values": [], "user_input_required": True}
                )
        if (
            require_requester
            and all(self._missing(payload.get(key)) for key in REQUESTER_FIELDS)
            and not any(item["name"] == "requester" for item in missing)
        ):
            missing.append(
                {
                    "name": "requester",
                    "label": "Requester",
                    "type": "default_requester",
                    "allowed_values": [],
                    "user_input_required": True,
                }
            )

        findings = detect_secrets(json.dumps(payload, default=str))
        if findings:
            warnings.append("Potential sensitive data detected. Remove or redact it before creation.")
        if invalid_fields:
            warnings.append(f"Unsupported Freshdesk ticket field(s): {', '.join(invalid_fields)}.")

        return {
            "valid": not missing and not findings and not invalid_fields,
            "missing_fields": missing,
            "invalid_fields": invalid_fields,
            "sensitive_data_findings": [finding.to_dict() for finding in findings],
            "warnings": warnings,
        }
