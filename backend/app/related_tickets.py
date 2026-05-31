from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .audit import AuditLog
from .config import Settings
from .freshdesk_client import FreshdeskClient
from .schema_cache import SchemaCache


class RelatedTicketsService:
    def __init__(
        self,
        freshdesk: FreshdeskClient,
        schema: SchemaCache,
        settings_provider,
        audit: AuditLog,
    ):
        self.freshdesk = freshdesk
        self.schema = schema
        self.settings_provider = settings_provider
        self.audit = audit

    @staticmethod
    def _compact(ticket: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
        return {
            "id": ticket.get("id"),
            "subject": ticket.get("subject", ""),
            "description": ticket.get("description_text") or ticket.get("description") or "",
            "status": ticket.get("status"),
            "priority": ticket.get("priority"),
            "requester_id": ticket.get("requester_id"),
            "responder_id": ticket.get("responder_id"),
            "updated_at": ticket.get("updated_at"),
            "related_because": reasons,
        }

    def list(self) -> list[dict[str, Any]]:
        settings: Settings = self.settings_provider()
        if not settings.my_email and not settings.my_name:
            raise HTTPException(status_code=422, detail="Set MY_NAME or MY_EMAIL before searching related tickets.")

        tickets: dict[str, dict[str, Any]] = {}

        def add(items: list[dict[str, Any]], reason: str) -> None:
            for item in items:
                key = str(item.get("id"))
                if not key:
                    continue
                if key not in tickets:
                    tickets[key] = self._compact(item, [reason])
                elif reason not in tickets[key]["related_because"]:
                    tickets[key]["related_because"].append(reason)

        if settings.my_email:
            try:
                contacts = self.freshdesk.find_contacts_by_email(settings.my_email)
                for contact in contacts:
                    if (contact.get("email") or "").lower() == settings.my_email.lower():
                        add(self.freshdesk.list_tickets(requester_id=contact.get("id")), "requester email")
            except HTTPException as exc:
                if exc.status_code == 423:
                    raise

        agents = self.schema.get("agents", [])
        for agent in agents:
            contact = agent.get("contact") or {}
            if settings.my_email and (contact.get("email") or "").lower() == settings.my_email.lower():
                try:
                    add(self.freshdesk.list_tickets(responder_id=agent.get("id")), "assigned agent")
                except HTTPException as exc:
                    if exc.status_code == 423:
                        raise

        terms = [term for term in (settings.my_email, settings.my_name) if term]
        for term in terms:
            escaped = term.replace("'", "\\'")
            try:
                add(self.freshdesk.search_tickets(f"'{escaped}'"), f"mentions {term}")
            except HTTPException as exc:
                if exc.status_code == 423:
                    raise

        result = sorted(tickets.values(), key=lambda item: item.get("updated_at") or "", reverse=True)
        self.audit.record("related_tickets_view", "read", request_summary=f"{len(result)} matching tickets")
        return result
