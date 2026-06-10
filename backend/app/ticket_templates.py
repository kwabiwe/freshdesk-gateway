from __future__ import annotations

from typing import Any

from .freshdesk_payload_builder import coerce_tags


CHANGE_SECTIONS = (
    ("Reason for change", "reason_for_change"),
    ("Scope", "scope"),
    ("Technical plan", "technical_plan"),
    ("Implementation steps", "implementation_steps"),
    ("Risk", "risk"),
    ("Impact", "impact"),
    ("Rollback plan", "rollback_plan"),
    ("Validation plan", "validation_plan"),
    ("Proposed date/time", "proposed_date_time"),
    ("Affected users/sites/services", "affected_users_sites_services"),
    ("Communications required", "communications_required"),
    ("Dependencies", "dependencies"),
    ("Notes", "notes"),
)


def render_change_description(values: dict[str, Any]) -> str:
    sections: list[str] = []
    fallback = values.get("rough_notes", "").strip() or "Not provided"
    for heading, key in CHANGE_SECTIONS:
        value = str(values.get(key, "")).strip()
        if not value and key == "notes":
            value = fallback
        sections.append(f"{heading}:\n{value or 'Not provided'}")
    return "\n\n".join(sections)


def clean_ticket_payload(values: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "subject": values.get("subject", "").strip(),
        "description": values.get("description", "").strip(),
        "email": values.get("requester_email", "").strip(),
        "priority": values.get("priority", 1),
        "status": values.get("status", 2),
        "source": values.get("source", 2),
    }
    optional_mapping = {
        "requester_name": "name",
        "requester_id": "requester_id",
        "group_id": "group_id",
        "company_id": "company_id",
        "responder_id": "responder_id",
        "product_id": "product_id",
        "type": "type",
    }
    for source, destination in optional_mapping.items():
        value = values.get(source)
        if value not in (None, ""):
            payload[destination] = value
    custom_fields = values.get("custom_fields") or {}
    if custom_fields:
        payload["custom_fields"] = custom_fields
    tags = coerce_tags(values.get("tags"))
    if tags:
        payload["tags"] = tags
    return payload
