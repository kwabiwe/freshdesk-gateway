from __future__ import annotations

import calendar
import json
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException

from .change_models import ChangeDocument
from .change_renderer import render_change_html
from .change_skill import ChangeSkill
from .local_llm_client import LocalLLMClient
from .schema_cache import SchemaCache
from .ticket_defaults import TicketDefaultsService


def _normalise(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


class ChangeService:
    def __init__(
        self,
        local_llm: LocalLLMClient,
        schema: SchemaCache,
        defaults: TicketDefaultsService,
        skill: ChangeSkill | None = None,
        now_provider=None,
    ):
        self.local_llm = local_llm
        self.schema = schema
        self.defaults = defaults
        self.skill = skill or ChangeSkill()
        self.now_provider = now_provider or (lambda: datetime.now().astimezone())

    @staticmethod
    def _choice_values(choices: Any) -> list[str]:
        if isinstance(choices, list):
            return [str(value) for value in choices]
        if isinstance(choices, dict):
            return [str(value) for value in choices]
        return []

    def _field(self, name: str) -> dict[str, Any] | None:
        return next((field for field in self.schema.ticket_fields() if field.get("name") == name), None)

    def _allowed(self, name: str, preferred: Any) -> str | None:
        if preferred in (None, ""):
            return None
        field = self._field(name)
        if not field:
            return None
        return next(
            (choice for choice in self._choice_values(field.get("choices")) if choice.lower() == str(preferred).lower()),
            None,
        )

    def _schema_prompt(self) -> str:
        useful_fields = {
            "cf_background_for_the_change",
            "cf_form2",
            "cf_type",
            "cf_change_type",
            "cf_change_state",
            "cf_approval_state",
            "cf_change_owner",
            "cf_requested_by",
            "cf_customer967575",
            "cf_business_impact723800",
            "cf_chg_business_impact",
            "cf_change_catergory",
        }
        fields = [
            {
                "name": field.get("name"),
                "label": field.get("label") or field.get("label_for_customers"),
                "choices": self._choice_values(field.get("choices"))[:80],
            }
            for field in self.schema.ticket_fields()
            if field.get("name") in useful_fields
        ]
        return json.dumps(
            {
                "groups": [{"id": item.get("id"), "name": item.get("name")} for item in self.schema.get("groups", [])],
                "companies": [{"id": item.get("id"), "name": item.get("name")} for item in self.schema.get("companies", [])],
                "fields": fields,
            },
            separators=(",", ":"),
        )

    def _prompt(self, notes: str) -> str:
        now = self.now_provider()
        contract = {
            "title": "string",
            "planned_change_date": "string",
            "customer": "string",
            "environment": "string",
            "configuration_items": [{"name": "string", "site_location": "string", "purpose": "string"}],
            "background": "string",
            "change_description": "string",
            "implementation_steps": ["string"],
            "rollback_branches": [{"scenario": "string", "steps": ["string"]}],
            "verification": {"pre_change": ["string"], "in_change": ["string"], "post_change": ["string"]},
            "risk_and_impact": "string",
            "expected_outcome": "string",
            "success_criteria": ["string"],
            "dependencies": ["string"],
            "assumptions": ["string"],
            "freshdesk_fields": {"cf_change_catergory": "exact discovered dropdown value or omit"},
        }
        return (
            f"{self.skill.instructions()}\n\n{self.skill.template()}\n\n"
            "Return a JSON object with exactly this compact shape:\n"
            f"{json.dumps(contract, separators=(',', ':'))}\n\n"
            f"LOCAL DATE AND TIMEZONE: {now.strftime('%A %d %B %Y %Z')}\n"
            f"CONFIGURED REQUESTER: {json.dumps(self.defaults.defaults('change')['identity'], separators=(',', ':'))}\n"
            f"FRESHDESK SCHEMA: {self._schema_prompt()}\n\nSOURCE NOTES:\n{notes}"
        )

    def _fallback_document(self, notes: str, assumptions: list[str] | None = None) -> ChangeDocument:
        return ChangeDocument(
            title="Change request",
            background=notes.strip() or "TBD",
            change_description=notes.strip() or "TBD",
            assumptions=assumptions or ["The local model response was incomplete. Review and complete the generated sections."],
        )

    def _document(self, raw: Any, notes: str) -> ChangeDocument:
        if not isinstance(raw, dict):
            return self._fallback_document(notes)
        try:
            document = ChangeDocument.model_validate(raw)
        except Exception:
            return self._fallback_document(notes)
        if document.background.strip().lower() in {"null", "tbd"}:
            document.background = notes.strip() or "TBD"
        if document.change_description.strip().lower() in {"null", "tbd"}:
            document.change_description = notes.strip() or "TBD"
        return document

    def _resolve_relative_date(self, notes: str, document: ChangeDocument) -> None:
        match = re.search(r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", notes, re.I)
        if not match:
            return
        now = self.now_provider()
        target = list(calendar.day_name).index(match.group(1).title())
        days = (target - now.weekday()) % 7 or 7
        resolved = now + timedelta(days=days)
        value = f"{resolved.strftime('%A')} {resolved.day} {resolved.strftime('%B %Y')}"
        document.planned_change_date = value
        assumption = f'Interpreted "{match.group(0)}" as {value} using the local timezone.'
        if assumption not in document.assumptions:
            document.assumptions.append(assumption)

    def _customer_choice(self, notes: str, document: ChangeDocument) -> str | None:
        field = self._field("cf_customer967575")
        if not field:
            return None
        choices = self._choice_values(field.get("choices"))
        text = f"{notes} {document.customer}"
        for choice in choices:
            words = re.sub(r"[_-]+", " ", choice)
            if re.search(rf"\b{re.escape(words)}\b", text, re.I):
                return choice
        return next((choice for choice in choices if _normalise(choice) == _normalise(document.customer)), None)

    def _explicit_change_type(self, notes: str) -> str:
        for signal, value in (("emergency", "Emmergency"), ("emmergency", "Emmergency"), ("standard", "Standard")):
            if re.search(rf"\b{signal}\b", notes, re.I):
                return value
        return "Normal"

    def _explicit_change_state(self, notes: str) -> str:
        field = self._field("cf_change_state")
        for choice in self._choice_values(field.get("choices") if field else []):
            if re.search(rf"\b{re.escape(choice)}\b", notes, re.I):
                return choice
        return "Pending approval"

    def _impact(self, notes: str) -> str | None:
        if re.search(r"\b(low|minimal|minor)\b", notes, re.I):
            return "Minor"
        if re.search(r"\b(significant|high|major)\b", notes, re.I):
            return "Significant"
        return None

    def _suggestions(self, notes: str, document: ChangeDocument) -> tuple[dict[str, Any], list[str]]:
        defaults = self.defaults.defaults("change")
        custom_fields = dict(defaults.get("custom_fields", {}))
        assumptions = list(document.assumptions)
        custom_fields["cf_background_for_the_change"] = document.background

        change_type = self._allowed("cf_change_type", self._explicit_change_type(notes))
        if change_type:
            custom_fields["cf_change_type"] = change_type
        change_state = self._allowed("cf_change_state", self._explicit_change_state(notes))
        if change_state:
            custom_fields["cf_change_state"] = change_state

        impact = self._impact(notes)
        if impact:
            for name in ("cf_business_impact723800", "cf_chg_business_impact"):
                allowed = self._allowed(name, impact)
                if allowed:
                    custom_fields[name] = allowed
            assumptions.append(f"Business impact defaults to {impact} based on the supplied notes.")

        customer = self._customer_choice(notes, document)
        if customer:
            custom_fields["cf_customer967575"] = customer
            if document.customer == "TBD":
                document.customer = customer.replace("_", " ")
            assumptions.append(f"Customer mapped to the discovered Freshdesk value {customer}.")

        for name in ("cf_change_catergory",):
            allowed = self._allowed(name, document.freshdesk_fields.get(name))
            if allowed:
                custom_fields[name] = allowed

        unique_assumptions = list(dict.fromkeys(item for item in assumptions if item.strip()))
        return (
            {
                "subject": document.title,
                "description": render_change_html(document),
                "group_id": defaults.get("group_id"),
                "company_id": defaults.get("company_id"),
                "custom_fields": custom_fields,
            },
            unique_assumptions,
        )

    def suggest(self, notes: str) -> dict[str, Any]:
        try:
            raw = self.local_llm.generate_json(self._prompt(notes), notes, max_tokens=4800)
        except HTTPException as exc:
            if exc.status_code != 502:
                raise
            raw = {}
            fallback = self._fallback_document(
                notes,
                [
                    "The selected local model did not return a complete structured document. Review and complete the generated sections.",
                    "Consider selecting a non-reasoning instruction model in Settings for faster structured drafting.",
                ],
            )
            self._resolve_relative_date(notes, fallback)
            suggestions, assumptions = self._suggestions(notes, fallback)
            return {
                "change_document": fallback.model_dump(),
                "rendered_description": suggestions["description"],
                "suggestions": suggestions,
                "assumptions": assumptions,
                "skill_version": self.skill.VERSION,
            }
        document = self._document(raw, notes)
        self._resolve_relative_date(notes, document)
        suggestions, assumptions = self._suggestions(notes, document)
        return {
            "change_document": document.model_dump(),
            "rendered_description": suggestions["description"],
            "suggestions": suggestions,
            "assumptions": assumptions,
            "skill_version": self.skill.VERSION,
        }

    def render(self, document: ChangeDocument) -> dict[str, Any]:
        return {"rendered_description": render_change_html(document), "skill_version": self.skill.VERSION}

    def prepare_draft(self, values: dict[str, Any]) -> tuple[dict[str, Any], str]:
        document_value = values.get("change_document")
        if not document_value:
            return values, ""
        document = ChangeDocument.model_validate(document_value)
        values = {**values, "description": render_change_html(document)}
        custom_fields = dict(values.get("custom_fields") or {})
        custom_fields["cf_background_for_the_change"] = document.background
        values["custom_fields"] = custom_fields
        stored = {
            "change_document": document.model_dump(),
            "assumptions": values.get("assumptions", []),
            "skill_version": values.get("skill_version") or self.skill.VERSION,
        }
        return values, json.dumps(stored)
