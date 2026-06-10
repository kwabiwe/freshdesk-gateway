from __future__ import annotations

import base64
from typing import Any

import httpx
from fastapi import HTTPException

from .audit import AuditLog
from .config import Settings
from .emergency import EmergencyStop
from .rate_limit import RateLimiter
from .sensitive_data import redact_text


class FreshdeskClient:
    def __init__(
        self,
        settings_provider,
        emergency: EmergencyStop,
        limiter: RateLimiter,
        audit: AuditLog,
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings_provider = settings_provider
        self.emergency = emergency
        self.limiter = limiter
        self.audit = audit
        self.transport = transport

    @staticmethod
    def build_auth_header(api_key: str) -> str:
        token = base64.b64encode(f"{api_key}:X".encode("utf-8")).decode("ascii")
        return f"Basic {token}"

    def _settings(self) -> Settings:
        settings = self.settings_provider()
        if not settings.freshdesk_configured:
            raise HTTPException(status_code=503, detail="Freshdesk is not configured. Add domain and API key to .env.")
        return settings

    def request(
        self,
        method: str,
        path: str,
        *,
        action_type: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        self.emergency.require_clear()
        settings = self._settings()
        mode = "read" if method.upper() == "GET" else "write"
        self.limiter.ensure_available(mode, action_type)
        headers = {
            "Authorization": self.build_auth_header(settings.freshdesk_api_key),
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=15.0, transport=self.transport) as client:
                response = client.request(
                    method,
                    f"{settings.freshdesk_base_url}{path}",
                    params=params,
                    json=json,
                    headers=headers,
                )
            self.limiter.record(mode, action_type)
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()
        except HTTPException:
            raise
        except httpx.HTTPStatusError as exc:
            detail = f"Freshdesk returned HTTP {exc.response.status_code}: {redact_text(exc.response.text, 240)}"
            self.audit.record("freshdesk_api_error", mode, request_summary=path, error=detail)
            raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
        except httpx.HTTPError as exc:
            detail = f"Freshdesk connection failed: {redact_text(str(exc), 240)}"
            self.audit.record("freshdesk_connection_error", mode, request_summary=path, error=detail)
            raise HTTPException(status_code=502, detail=detail) from exc

    def test_connection(self) -> dict[str, Any]:
        result = self.request("GET", "/api/v2/agents/me", action_type="freshdesk_connection_test")
        return {
            "connected": True,
            "agent": {"id": result.get("id"), "name": result.get("contact", {}).get("name") or result.get("name")},
        }

    def ticket_fields(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/v2/ticket_fields", action_type="schema_ticket_fields")

    def groups(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/v2/groups", action_type="schema_groups")

    def agents(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/v2/agents", action_type="schema_agents")

    def companies(self) -> list[dict[str, Any]]:
        companies = self.request("GET", "/api/v2/companies", action_type="schema_companies")
        return [{key: company.get(key) for key in ("id", "name", "domains")} for company in companies]

    def products(self) -> list[dict[str, Any]]:
        products = self.request("GET", "/api/v2/products", action_type="schema_products")
        return [{key: product.get(key) for key in ("id", "name", "description")} for product in products]

    def ticket_forms(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/v2/ticket-forms", action_type="schema_ticket_forms")

    def search_contacts(self, query: str) -> list[dict[str, Any]]:
        if "@" in query:
            return [self._contact_summary(contact) for contact in self.find_contacts_by_email(query)]
        response = self.request(
            "GET", "/api/v2/contacts/autocomplete", action_type="search_contacts", params={"term": query}
        )
        contacts = response.get("contacts", response) if isinstance(response, dict) else response
        return [self._hydrate_contact(contact) for contact in contacts]

    def find_contacts_by_email(self, email: str) -> list[dict[str, Any]]:
        return self.request(
            "GET", "/api/v2/contacts", action_type="search_contacts", params={"email": email}
        )

    def view_contact(self, contact_id: int | str) -> dict[str, Any]:
        response = self.request("GET", f"/api/v2/contacts/{contact_id}", action_type="view_contact")
        if isinstance(response, list):
            response = response[0] if response else {}
        return self._contact_summary(response)

    def contacts_by_company(self, company_id: int | str) -> list[dict[str, Any]]:
        contacts = self.request(
            "GET", "/api/v2/contacts", action_type="search_contacts", params={"company_id": company_id}
        )
        return [self._contact_summary(contact) for contact in contacts]

    def search_agents(self, query: str) -> list[dict[str, Any]]:
        response = self.request(
            "GET", "/api/v2/agents/autocomplete", action_type="search_agents", params={"term": query}
        )
        return response.get("agents", response) if isinstance(response, dict) else response

    def search_companies(self, query: str) -> list[dict[str, Any]]:
        response = self.request(
            "GET", "/api/v2/companies/autocomplete", action_type="search_companies", params={"name": query}
        )
        companies = response.get("companies", response) if isinstance(response, dict) else response
        return [{key: company.get(key) for key in ("id", "name", "domains")} for company in companies]

    def _hydrate_contact(self, contact: dict[str, Any]) -> dict[str, Any]:
        contact_id = contact.get("id")
        if contact_id in (None, ""):
            return self._contact_summary(contact, partial=True)
        try:
            return self.view_contact(contact_id)
        except HTTPException as exc:
            if exc.status_code in (403, 404):
                return self._contact_summary(contact, partial=True)
            raise

    @staticmethod
    def _contact_summary(contact: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
        keys = ("id", "name", "email", "company_id", "other_companies")
        summary = {key: contact.get(key) for key in keys if key in contact}
        company = contact.get("company") or {}
        if company:
            summary["company_name"] = company.get("name")
        if partial:
            summary["partial"] = True
        return summary

    def create_ticket(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/api/v2/tickets", action_type="ticket_create", json=payload)

    def update_ticket(self, ticket_id: str | int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("PUT", f"/api/v2/tickets/{ticket_id}", action_type="ticket_update", json=payload)

    def list_tickets(self, **params: Any) -> list[dict[str, Any]]:
        return self.request("GET", "/api/v2/tickets", action_type="list_related_tickets", params=params)

    def search_tickets(self, query: str) -> list[dict[str, Any]]:
        return self.request(
            "GET", "/api/v2/search/tickets", action_type="search_related_tickets", params={"query": query}
        ).get("results", [])
