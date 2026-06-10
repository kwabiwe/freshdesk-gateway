from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException

from .audit import AuditLog
from .freshdesk_client import FreshdeskClient
from .schema_cache import SchemaCache


class SchemaService:
    def __init__(self, freshdesk: FreshdeskClient, cache: SchemaCache, audit: AuditLog):
        self.freshdesk = freshdesk
        self.cache = cache
        self.audit = audit

    def sync(self) -> dict[str, Any]:
        resources: tuple[tuple[str, Callable[[], Any]], ...] = (
            ("ticket_fields", self.freshdesk.ticket_fields),
            ("groups", self.freshdesk.groups),
            ("agents", self.freshdesk.agents),
            ("companies", self.freshdesk.companies),
            ("products", getattr(self.freshdesk, "products", lambda: [])),
            ("ticket_forms", self.freshdesk.ticket_forms),
        )
        results: dict[str, Any] = {}
        for key, loader in resources:
            try:
                data = loader()
                self.cache.put(key, data, status="ok")
                results[key] = {"status": "ok", "count": len(data) if isinstance(data, list) else 1}
            except HTTPException as exc:
                if exc.status_code in (423, 429):
                    raise
                error = self._friendly_error(key, exc)
                self.cache.put(key, [], status="inaccessible", error=error)
                results[key] = {"status": "inaccessible", "error": error}
        self._apply_ticket_field_fallbacks(results)
        self.audit.record("schema_sync", "read", api_result=results)
        return {**self.cache.overview(), "sync_results": results}

    @staticmethod
    def _friendly_error(key: str, exc: HTTPException) -> str:
        if exc.status_code == 403 and key in {"groups", "agents"}:
            return "Your Freshdesk agent role cannot list this resource. Using values exposed by ticket fields where available."
        if exc.status_code == 403 and key == "ticket_forms":
            return "Your Freshdesk agent role cannot view ticket forms. Ticket-field validation remains available."
        if exc.status_code == 403 and key == "products":
            return "Your Freshdesk agent role cannot list products. Product IDs can still be resolved from ticket-field choices when Freshdesk exposes them."
        if exc.status_code == 404 and key == "ticket_forms":
            return "Ticket forms are not exposed for this Freshdesk account. Ticket-field validation remains available."
        return str(exc.detail)

    def _apply_ticket_field_fallbacks(self, results: dict[str, Any]) -> None:
        fields = self.cache.ticket_fields()
        fallbacks = {
            "groups": ("group", self._choice_records),
            "agents": ("agent", self._agent_choice_records),
        }
        for resource, (field_name, converter) in fallbacks.items():
            cached = self.cache.get(resource, [])
            if cached:
                continue
            field = next((item for item in fields if item.get("name") == field_name), {})
            records = converter(field.get("choices"))
            if not records:
                continue
            message = "Loaded from ticket-field choices because your Freshdesk agent role cannot list this resource directly."
            self.cache.put(resource, records, status="fallback", error=message)
            results[resource] = {"status": "fallback", "count": len(records), "error": message}

    @staticmethod
    def _choice_records(choices: Any) -> list[dict[str, Any]]:
        if not isinstance(choices, dict):
            return []
        return [{"id": value, "name": name, "source": "ticket_fields"} for name, value in choices.items()]

    @staticmethod
    def _agent_choice_records(choices: Any) -> list[dict[str, Any]]:
        if not isinstance(choices, dict):
            return []
        return [
            {"id": value, "name": name, "contact": {"name": name}, "source": "ticket_fields"}
            for name, value in choices.items()
        ]
