from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .schema_cache import SchemaCache


def normalise(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def as_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class ResolvedEntity:
    key: str
    label: str = ""
    display_value: str = ""
    value: Any = None
    resolved_id: int | None = None
    email: str = ""
    company_id: int | None = None
    other_company_ids: set[int] = field(default_factory=set)
    payload_path: str = ""
    status: str = "missing"
    error: str = ""
    warning: str = ""
    record: dict[str, Any] = field(default_factory=dict)


class FreshdeskResolver:
    def __init__(self, schema: SchemaCache):
        self.schema = schema

    @staticmethod
    def choice_values(choices: Any) -> list[str]:
        if isinstance(choices, list):
            return [str(value) for value in choices]
        if isinstance(choices, dict):
            values: list[str] = []
            for key, nested in choices.items():
                values.append(str(key))
                if isinstance(nested, (list, dict)):
                    values.extend(FreshdeskResolver.choice_values(nested))
            return values
        return []

    def _record_match(
        self,
        records: list[dict[str, Any]],
        value: Any,
        keys: tuple[str, ...] = ("name",),
    ) -> dict[str, Any] | None:
        wanted = normalise(value)
        if not wanted:
            return None
        for record in records:
            if str(record.get("id")) == str(value):
                return record
            for key in keys:
                candidate = normalise(record.get(key))
                if candidate and (candidate == wanted or candidate in wanted or wanted in candidate):
                    return record
        return None

    def _company_records(self) -> list[dict[str, Any]]:
        return self.schema.get("companies", [])

    def _product_records(self) -> list[dict[str, Any]]:
        products = self.schema.get("products", [])
        if products:
            return products
        field = next((item for item in self.schema.ticket_fields() if item.get("name") == "product"), {})
        choices = field.get("choices")
        if isinstance(choices, dict):
            return [{"id": value, "name": name, "source": "ticket_fields"} for name, value in choices.items()]
        return []

    def contact_company_ids(self, contact: dict[str, Any]) -> set[int]:
        ids: set[int] = set()
        primary = as_int(contact.get("company_id"))
        if primary is not None:
            ids.add(primary)
        for item in contact.get("other_companies") or []:
            if isinstance(item, dict):
                company_id = as_int(item.get("company_id") or item.get("id"))
            else:
                company_id = as_int(item)
            if company_id is not None:
                ids.add(company_id)
        return ids

    def requester_belongs_to_company(self, contact: dict[str, Any], company_id: int | None) -> bool:
        if company_id is None:
            return True
        return company_id in self.contact_company_ids(contact)

    def resolve_contact(self, field: dict[str, Any]) -> ResolvedEntity:
        display_value = field.get("display_value") or field.get("value") or ""
        record = field.get("record") if isinstance(field.get("record"), dict) else {}
        resolved_id = as_int(field.get("resolved_id") or record.get("id"))
        email = str(field.get("email") or record.get("email") or "")
        company_id = as_int(field.get("company_id") or record.get("company_id"))
        other_ids = self.contact_company_ids(record)
        if company_id is not None:
            other_ids.add(company_id)
        if resolved_id is not None:
            return ResolvedEntity(
                key="contact",
                label="Contact",
                display_value=str(record.get("name") or display_value or ""),
                resolved_id=resolved_id,
                email=email,
                company_id=company_id,
                other_company_ids=other_ids,
                payload_path="requester_id",
                status="confirmed",
                record=record,
            )
        if re.search(r"[^<>\s@]+@[^<>\s@]+\.[^<>\s@]+", str(display_value)):
            return ResolvedEntity(
                key="contact",
                label="Contact",
                display_value=str(display_value),
                email=str(display_value),
                payload_path="email/name",
                status="confirmed",
                record=record,
            )
        return ResolvedEntity(
            key="contact",
            label="Contact",
            display_value=str(display_value or ""),
            payload_path="requester_id or email/name",
            status="needs_human_choice" if display_value else "missing",
            error="Search and select an existing Freshdesk contact." if display_value else "Search and select a Freshdesk contact.",
            record=record,
        )

    def resolve_company(self, display_value: Any = None, resolved_id: Any = None) -> ResolvedEntity:
        records = self._company_records()
        match = None
        if resolved_id not in (None, ""):
            match = next((item for item in records if str(item.get("id")) == str(resolved_id)), None)
        match = match or self._record_match(records, display_value)
        if match:
            return ResolvedEntity(
                key="company",
                label="Company",
                display_value=str(match.get("name") or display_value or ""),
                resolved_id=as_int(match.get("id")),
                payload_path="company_id",
                status="confirmed",
                record=match,
            )
        return ResolvedEntity(
            key="company",
            label="Company",
            display_value=str(display_value or ""),
            payload_path="company_id",
            status="needs_human_choice" if display_value else "missing",
            error="Select a Freshdesk company." if display_value else "",
        )

    def resolve_group(self, display_value: Any = None, resolved_id: Any = None) -> ResolvedEntity:
        records = self.schema.get("groups", [])
        match = None
        if resolved_id not in (None, ""):
            match = next((item for item in records if str(item.get("id")) == str(resolved_id)), None)
        match = match or self._record_match(records, display_value)
        if match:
            return ResolvedEntity(
                key="group",
                label="Group",
                display_value=str(match.get("name") or display_value or ""),
                resolved_id=as_int(match.get("id")),
                payload_path="group_id",
                status="confirmed",
                record=match,
            )
        return ResolvedEntity(
            key="group",
            label="Group",
            display_value=str(display_value or ""),
            payload_path="group_id",
            status="needs_human_choice" if display_value else "missing",
            error="Select a Freshdesk group." if display_value else "",
        )

    def resolve_agent(self, display_value: Any = None, resolved_id: Any = None) -> ResolvedEntity:
        records = self.schema.get("agents", [])
        match = None
        if resolved_id not in (None, ""):
            match = next((item for item in records if str(item.get("id")) == str(resolved_id)), None)
        if not match:
            wanted = normalise(display_value)
            for agent in records:
                contact = agent.get("contact") or {}
                names = [agent.get("name"), contact.get("name"), contact.get("email")]
                if any(normalise(item) == wanted for item in names if item):
                    match = agent
                    break
        if match:
            contact = match.get("contact") or {}
            return ResolvedEntity(
                key="agent",
                label="Agent",
                display_value=str(contact.get("name") or match.get("name") or display_value or ""),
                resolved_id=as_int(match.get("id")),
                email=str(contact.get("email") or ""),
                payload_path="responder_id",
                status="confirmed",
                record=match,
            )
        return ResolvedEntity(
            key="agent",
            label="Agent",
            display_value=str(display_value or ""),
            payload_path="responder_id",
            status="needs_human_choice" if display_value else "missing",
            error="Select a Freshdesk agent." if display_value else "",
        )

    def resolve_product(self, display_value: Any = None, resolved_id: Any = None) -> ResolvedEntity:
        records = self._product_records()
        match = None
        if resolved_id not in (None, ""):
            match = next((item for item in records if str(item.get("id")) == str(resolved_id)), None)
        match = match or self._record_match(records, display_value)
        if match:
            return ResolvedEntity(
                key="product",
                label="Product",
                display_value=str(match.get("name") or display_value or ""),
                resolved_id=as_int(match.get("id")),
                payload_path="product_id",
                status="confirmed",
                record=match,
            )
        if display_value:
            return ResolvedEntity(
                key="product",
                label="Product",
                display_value=str(display_value),
                payload_path="product_id",
                status="needs_human_choice",
                error="Product must resolve to a Freshdesk product ID before it can be submitted.",
            )
        return ResolvedEntity(key="product", label="Product", payload_path="product_id", status="missing")

    def resolve_customer_choice(self, field_name: str, display_value: Any) -> ResolvedEntity:
        field = next((item for item in self.schema.ticket_fields() if item.get("name") == field_name), None)
        choices = self.choice_values((field or {}).get("choices"))
        match = next((choice for choice in choices if normalise(choice) == normalise(display_value)), None)
        if match:
            return ResolvedEntity(
                key="customer",
                label=(field or {}).get("label") or "Customer",
                display_value=match,
                value=match,
                payload_path=f"custom_fields.{field_name}",
                status="confirmed",
            )
        return ResolvedEntity(
            key="customer",
            label=(field or {}).get("label") or "Customer",
            display_value=str(display_value or ""),
            payload_path=f"custom_fields.{field_name}",
            status="needs_human_choice" if display_value else "missing",
            error="Select an allowed Customer value from Freshdesk." if display_value else "",
        )
