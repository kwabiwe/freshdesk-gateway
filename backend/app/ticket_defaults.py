from __future__ import annotations

import re
from typing import Any

from .config import Settings
from .schema_cache import SchemaCache


def _normalise(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


class TicketDefaultsService:
    """Build conservative, editable form defaults from local identity and cached schema."""

    def __init__(self, schema: SchemaCache, settings_provider):
        self.schema = schema
        self.settings_provider = settings_provider

    @staticmethod
    def _choice_values(choices: Any) -> list[str]:
        if isinstance(choices, list):
            return [str(value) for value in choices]
        if isinstance(choices, dict):
            values: list[str] = []
            for key, nested in choices.items():
                values.append(str(key))
                if isinstance(nested, (list, dict)):
                    values.extend(TicketDefaultsService._choice_values(nested))
            return values
        return []

    def _field(self, name: str) -> dict[str, Any] | None:
        return next((field for field in self.schema.ticket_fields() if field.get("name") == name), None)

    def _allowed_choice(self, name: str, preferred: str) -> str | None:
        field = self._field(name)
        if not field:
            return None
        choices = self._choice_values(field.get("choices"))
        return next((choice for choice in choices if choice.lower() == preferred.lower()), None)

    def _company(self, email: str) -> dict[str, Any] | None:
        domain = email.rpartition("@")[2].lower()
        if not domain:
            return None
        return next(
            (
                company
                for company in self.schema.get("companies", [])
                if domain in {str(item).lower() for item in (company.get("domains") or [])}
            ),
            None,
        )

    def _agent(self, settings: Settings) -> dict[str, Any] | None:
        for agent in self.schema.get("agents", []):
            contact = agent.get("contact") or {}
            if settings.my_email and str(contact.get("email", "")).lower() == settings.my_email.lower():
                return agent
            if settings.my_name and str(contact.get("name") or agent.get("name") or "").lower() == settings.my_name.lower():
                return agent
        return None

    def _group_id(self, preferred: str) -> Any:
        group = next(
            (item for item in self.schema.get("groups", []) if str(item.get("name", "")).lower() == preferred.lower()),
            None,
        )
        return group.get("id") if group else None

    def _customer_choice(self, company: dict[str, Any] | None) -> tuple[str, str] | None:
        if not company:
            return None
        company_name = _normalise(company.get("name", ""))
        for field in self.schema.ticket_fields():
            name = str(field.get("name", ""))
            if not name.startswith("cf_") or "customer" not in name:
                continue
            for choice in self._choice_values(field.get("choices")):
                normalised = _normalise(choice)
                if normalised and (normalised in company_name or company_name in normalised):
                    return name, choice
        return None

    def defaults(self, kind: str = "generic") -> dict[str, Any]:
        settings: Settings = self.settings_provider()
        company = self._company(settings.my_email)
        agent = self._agent(settings)
        custom_fields: dict[str, Any] = {}

        if self._field("cf_requested_by") and settings.my_name:
            custom_fields["cf_requested_by"] = settings.my_name
        customer_choice = self._customer_choice(company)
        if customer_choice:
            custom_fields[customer_choice[0]] = customer_choice[1]

        if kind == "change":
            if self._field("cf_change_owner") and settings.my_name:
                custom_fields["cf_change_owner"] = settings.my_name
            for name, preferred in (
                ("cf_form2", "Change Request"),
                ("cf_change_type", "Normal"),
                ("cf_change_state", "Pending approval"),
                ("cf_approval_state", "Not Yet Requested"),
                ("cf_type", "Change"),
            ):
                choice = self._allowed_choice(name, preferred)
                if choice:
                    custom_fields[name] = choice

        return {
            "requester_name": settings.my_name,
            "requester_email": settings.my_email,
            "company_id": None,
            "identity_company_id": company.get("id") if company else None,
            "group_id": self._group_id("L3 Engineering") if kind == "change" else None,
            "priority": 1,
            "status": 2,
            "source": 2,
            "custom_fields": custom_fields,
            "safe_payload_defaults": {
                "priority": 1,
                "status": 2,
                "source": 2,
                "group_id": self._group_id("L3 Engineering") if kind == "change" else None,
            },
            "identity": {
                "name": settings.my_name,
                "email": settings.my_email,
                "agent_id": agent.get("id") if agent else None,
                "company_id": company.get("id") if company else None,
                "company_name": company.get("name") if company else None,
            },
        }

    def apply(self, values: dict[str, Any], kind: str = "generic") -> dict[str, Any]:
        defaults = self.defaults(kind)
        merged = {**defaults, **values}
        merged.pop("identity", None)
        merged["custom_fields"] = {
            **defaults.get("custom_fields", {}),
            **{key: value for key, value in (values.get("custom_fields") or {}).items() if value not in (None, "")},
        }
        requested_email = str(values.get("requester_email") or "").lower()
        default_email = str(defaults.get("requester_email") or "").lower()
        use_identity_defaults = not requested_email or requested_email == default_email
        if merged.get("requester_email") in (None, ""):
            merged["requester_email"] = defaults.get("requester_email")
        if values.get("requester_name") in (None, ""):
            merged["requester_name"] = defaults.get("requester_name") if use_identity_defaults else ""
        if values.get("company_id") in (None, ""):
            merged["company_id"] = None
        if values.get("group_id") in (None, ""):
            merged["group_id"] = defaults.get("group_id")
        merged.pop("identity_company_id", None)
        merged.pop("safe_payload_defaults", None)
        return merged
