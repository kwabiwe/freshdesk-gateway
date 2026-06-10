from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .schema_cache import SchemaCache
from .ticket_defaults import TicketDefaultsService


EMAIL_RE = re.compile(r"[^<>\s@]+@[^<>\s@]+\.[^<>\s@]+")


def _normalise(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _missing(value: Any) -> bool:
    return value is None or value == "" or value == [] or (
        isinstance(value, str) and value.strip().lower() in {"tbd", "unknown", "not provided"}
    )


def _email_from(value: str) -> str | None:
    match = EMAIL_RE.search(value)
    return match.group(0) if match else None


def _loose_match(left: Any, right: Any) -> bool:
    a = _normalise(left)
    b = _normalise(right)
    return bool(a and b and (a == b or a in b or b in a))


def coerce_tags(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    raw_values = value
    if isinstance(value, str):
        raw_values = re.split(r"[\n,]+", value)
    if not isinstance(raw_values, list):
        return []
    tags: list[str] = []
    for item in raw_values:
        tag = str(item).strip()
        if tag:
            tags.append(tag)
    return list(dict.fromkeys(tags))


@dataclass
class PayloadBuildResult:
    payload: dict[str, Any]
    mapping_notes: list[str] = field(default_factory=list)


class FreshdeskPayloadBuilder:
    """Build the exact Freshdesk ticket API payload from a reviewed draft ledger."""

    def __init__(self, schema: SchemaCache, defaults: TicketDefaultsService):
        self.schema = schema
        self.defaults = defaults

    def build(self, envelope: dict[str, Any], bulk_item: dict[str, Any] | None = None) -> PayloadBuildResult:
        source = bulk_item or envelope
        fields = {field["key"]: field for field in source.get("ticket_fields", [])}
        notes: list[str] = []

        def value(key: str) -> Any:
            field = fields.get(key) or {}
            return field.get("display_value") or field.get("value")

        mode = envelope.get("mode", "create")
        defaults = self.defaults.defaults(source.get("ticket_profile") or envelope.get("ticket_profile", "change"))
        payload: dict[str, Any] = {
            "subject": _display(value("subject")).strip(),
            "description": _display(source.get("rendered_description", "")).strip(),
            "priority": fields.get("priority", {}).get("value") or defaults.get("priority", 1),
            "status": fields.get("status", {}).get("value") or defaults.get("status", 2),
            "source": defaults.get("source", 2),
        }

        default_company_id = defaults.get("company_id")
        if mode != "update" and default_company_id not in (None, ""):
            payload["company_id"] = int(default_company_id)
            notes.append(f"Mapped configured company to company_id {payload['company_id']}.")

        self._apply_contact(payload, fields.get("contact", {}), value("contact"), defaults, include_requester=mode != "update")
        self._apply_directory_id(payload, "group_id", fields.get("group", {}), "Group", notes)
        self._apply_directory_id(payload, "responder_id", fields.get("agent", {}), "Agent", notes)

        custom_fields = dict(defaults.get("custom_fields", {}))
        for key, field_record in fields.items():
            self._apply_review_field(payload, custom_fields, key, field_record, value(key), notes)
        if custom_fields:
            payload["custom_fields"] = custom_fields
        return PayloadBuildResult(payload=payload, mapping_notes=list(dict.fromkeys(notes)))

    def payload_path(self, key: str, schema_field_name: str = "") -> str:
        if key == "product":
            return "product_id"
        if key == "contact":
            return "requester_id or email/name"
        if key == "group":
            return "group_id"
        if key == "agent":
            return "responder_id"
        if key in {"subject", "status", "priority", "tags"}:
            return key
        field = self._schema_field_for_key(key, schema_field_name)
        name = str((field or {}).get("name") or schema_field_name or "")
        if name.startswith("cf_"):
            return f"custom_fields.{name}"
        if name in {"type", "ticket_type"}:
            return "type"
        if name in {"product", "product_id"}:
            return "product_id"
        return ""

    def _apply_contact(
        self,
        payload: dict[str, Any],
        contact: dict[str, Any],
        raw_value: Any,
        defaults: dict[str, Any],
        *,
        include_requester: bool,
    ) -> None:
        contact_value = _display(raw_value).strip()
        default_contact_email = defaults.get("requester_email", "")
        default_contact_name = defaults.get("requester_name", "")
        use_default_contact = bool(default_contact_email) and (
            not contact_value or _loose_match(contact_value, default_contact_name) or _loose_match(contact_value, default_contact_email)
        )
        explicit_contact = contact.get("source") in {"ai_agent", "user_edit"} or contact.get("resolved_id") not in (None, "")
        if not include_requester and not explicit_contact:
            return

        contact_email = _email_from(contact_value)
        if contact_email:
            payload["email"] = contact_email
            payload["name"] = contact_value
        elif use_default_contact:
            payload["email"] = default_contact_email
            payload["name"] = contact_value or default_contact_name
        elif contact_value:
            payload["name"] = contact_value

        contact_id = contact.get("resolved_id")
        if contact_id not in (None, ""):
            payload.pop("email", None)
            payload.pop("name", None)
            payload["requester_id"] = int(contact_id)

    @staticmethod
    def _apply_directory_id(payload: dict[str, Any], payload_key: str, field_record: dict[str, Any], label: str, notes: list[str]) -> None:
        resolved_id = field_record.get("resolved_id")
        if resolved_id in (None, ""):
            return
        payload[payload_key] = int(resolved_id)
        notes.append(f"Mapped {label} to {payload_key} {payload[payload_key]}.")

    def _apply_review_field(
        self,
        payload: dict[str, Any],
        custom_fields: dict[str, Any],
        key: str,
        field_record: dict[str, Any],
        field_value: Any,
        notes: list[str],
    ) -> None:
        if _missing(field_value):
            return
        if key == "tags":
            tags = coerce_tags(field_value)
            if tags:
                payload["tags"] = tags
                notes.append("Converted review Tags into the Freshdesk tags array.")
            return

        field = self._schema_field_for_key(key, str(field_record.get("schema_field_name") or ""))
        if not field:
            return
        name = str(field.get("name") or "")
        if name.startswith("cf_"):
            custom_fields[name] = field_value
            notes.append(f"Mapped {field_record.get('label') or name} to custom_fields.{name}.")
        elif name in {"product", "product_id"}:
            product_id = self._product_id(field, field_record, field_value)
            if product_id is not None:
                payload["product_id"] = int(product_id)
                notes.append(f"Mapped Product to product_id {payload['product_id']}.")
        elif name in {"type", "ticket_type"}:
            payload["type"] = field_value
            notes.append("Mapped Ticket Type to top-level type.")

    @staticmethod
    def _product_id(field: dict[str, Any], field_record: dict[str, Any], field_value: Any) -> int | None:
        resolved = field_record.get("resolved_id")
        if resolved not in (None, ""):
            return int(resolved)
        if isinstance(field_value, int):
            return field_value
        choices = field.get("choices")
        if isinstance(choices, dict):
            for label, choice_value in choices.items():
                if _normalise(label) == _normalise(field_value) and not isinstance(choice_value, (list, dict)):
                    return int(choice_value)
        return None

    def _schema_field_for_key(self, key: str, schema_field_name: str = "") -> dict[str, Any] | None:
        if schema_field_name:
            match = next((item for item in self.schema.ticket_fields() if item.get("name") == schema_field_name), None)
            if match:
                return match
        lookup = {
            "product": ("product",),
            "form": ("cf_form2",),
            "change_type": ("cf_change_type",),
            "requested_by": ("cf_requested_by",),
            "change_owner": ("cf_change_owner",),
            "change_category": ("cf_change_catergory", "cf_change_category"),
            "chg_business_impact": ("cf_chg_business_impact",),
            "change_state": ("cf_change_state",),
            "approval_state": ("cf_approval_state",),
            "ticket_type": ("cf_type", "cf_ticket_type", "ticket_type", "type"),
            "business_impact": ("cf_business_impact723800", "cf_business_impact"),
            "customer": ("cf_customer967575", "cf_customer"),
            "reminder_date": ("cf_reminder_date",),
        }.get(key, (key,))
        for name in lookup:
            match = next((item for item in self.schema.ticket_fields() if item.get("name") == name), None)
            if match:
                return match
        return None
