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
    "tags",
}


class TicketValidator:
    def __init__(self, schema: SchemaCache):
        self.schema = schema

    @staticmethod
    def _choice_values(choices: Any) -> list[str]:
        if isinstance(choices, list):
            return [str(value) for value in choices]
        if isinstance(choices, dict):
            values: list[str] = []
            for key, nested in choices.items():
                values.append(str(key))
                if isinstance(nested, (list, dict)):
                    values.extend(TicketValidator._choice_values(nested))
            return values
        return []

    @staticmethod
    def _missing(value: Any) -> bool:
        return value is None or value == "" or value == [] or (
            isinstance(value, str) and value.strip().lower() in {"tbd", "not provided", "unknown"}
        )

    def validate(self, payload: dict[str, Any], *, require_requester: bool = True) -> dict[str, Any]:
        missing: list[dict[str, Any]] = []
        warnings: list[str] = []
        invalid_fields = sorted(key for key in payload if key not in ALLOWED_TICKET_FIELDS)
        invalid_custom_fields: list[str] = []
        invalid_custom_field_values: list[dict[str, Any]] = []
        invalid_company_association: list[dict[str, Any]] = []
        invalid_tags: list[Any] = []
        required_fields = self.schema.required_ticket_fields()
        fields_by_name = {str(field.get("name")): field for field in self.schema.ticket_fields()}

        if "tags" in payload:
            tags = payload.get("tags")
            if not isinstance(tags, list) or any(not isinstance(tag, str) or self._missing(tag.strip()) for tag in tags):
                invalid_tags = tags if isinstance(tags, list) else [tags]

        company_id = payload.get("company_id")
        requester_email = str(payload.get("email") or "").strip().lower()
        if company_id not in (None, "") and requester_email:
            company = self._company_by_id(company_id)
            domain = requester_email.rpartition("@")[2]
            domains = {str(item).lower() for item in (company or {}).get("domains", [])}
            if domains and domain not in domains:
                invalid_company_association.append(
                    {
                        "field": "company_id",
                        "company_id": company_id,
                        "company_name": (company or {}).get("name"),
                        "requester_email": requester_email,
                        "message": "Requester email domain does not belong to the selected Freshdesk company.",
                    }
                )

        for key, value in (payload.get("custom_fields") or {}).items():
            name = str(key)
            field = fields_by_name.get(name)
            if not field or not name.startswith("cf_"):
                invalid_custom_fields.append(name)
                continue
            choices = self._choice_values(field.get("choices"))
            if choices and not self._missing(value) and str(value) not in choices:
                invalid_custom_field_values.append(
                    {
                        "name": name,
                        "label": field.get("label") or field.get("label_for_customers") or name,
                        "value": value,
                        "allowed_values": choices,
                    }
                )

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
        if invalid_custom_fields:
            warnings.append(f"Unsupported Freshdesk custom field(s): {', '.join(invalid_custom_fields)}.")
        if invalid_company_association:
            warnings.append("Requester and company selection do not match Freshdesk company metadata.")
        if invalid_tags:
            warnings.append("Freshdesk tags must be an array of non-empty strings.")

        return {
            "valid": not missing and not findings and not invalid_fields and not invalid_custom_fields and not invalid_custom_field_values and not invalid_company_association and not invalid_tags,
            "missing_fields": missing,
            "invalid_fields": invalid_fields,
            "invalid_custom_fields": sorted(invalid_custom_fields),
            "invalid_custom_field_values": invalid_custom_field_values,
            "invalid_company_association": invalid_company_association,
            "invalid_tags": invalid_tags,
            "sensitive_data_findings": [finding.to_dict() for finding in findings],
            "warnings": warnings,
        }

    def _company_by_id(self, company_id: Any) -> dict[str, Any] | None:
        return next((company for company in self.schema.get("companies", []) if str(company.get("id")) == str(company_id)), None)
