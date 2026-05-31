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

    def ticket_forms(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/v2/ticket-forms", action_type="schema_ticket_forms")

    def search_contacts(self, query: str) -> list[dict[str, Any]]:
        if "@" in query:
            return self.find_contacts_by_email(query)
        return self.request(
            "GET", "/api/v2/contacts/autocomplete", action_type="search_contacts", params={"term": query}
        )

    def find_contacts_by_email(self, email: str) -> list[dict[str, Any]]:
        return self.request(
            "GET", "/api/v2/contacts", action_type="search_contacts", params={"email": email}
        )

    def search_companies(self, query: str) -> list[dict[str, Any]]:
        return self.request(
            "GET", "/api/v2/companies/autocomplete", action_type="search_companies", params={"name": query}
        ).get("companies", [])

    def create_ticket(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/api/v2/tickets", action_type="ticket_create", json=payload)

    def list_tickets(self, **params: Any) -> list[dict[str, Any]]:
        return self.request("GET", "/api/v2/tickets", action_type="list_related_tickets", params=params)

    def search_tickets(self, query: str) -> list[dict[str, Any]]:
        return self.request(
            "GET", "/api/v2/search/tickets", action_type="search_related_tickets", params={"query": query}
        ).get("results", [])
