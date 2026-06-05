from __future__ import annotations

import json
import re
import uuid
from typing import Any

from fastapi import HTTPException

from .audit import AuditLog, utc_now
from .database import Database
from .freshdesk_client import FreshdeskClient
from .models import AgentDraftEnvelope, AgentDraftPatch, AgentFeedbackRequest
from .schema_cache import SchemaCache
from .ticket_defaults import TicketDefaultsService
from .validators import TicketValidator


DEFAULT_FIELD_VALUES = {
    "product": "A24 Support",
    "contact": "Kwabiwe Sibanda",
    "agent": "Kwabiwe Sibanda",
    "group": "L3 Engineer",
    "business_impact": "Minor",
}
FIELD_LABELS = {
    "product": "Product",
    "contact": "Contact",
    "subject": "Subject",
    "form": "Form",
    "ticket_type": "Ticket Type",
    "status": "Status",
    "business_impact": "Business Impact",
    "group": "Group",
    "agent": "Agent",
    "priority": "Priority",
}
REQUIRED_SECTIONS = {"scope", "implementation", "rollback", "verification", "config_items"}
STATUS_CHOICES = {"open": 2, "pending": 3, "resolved": 4, "closed": 5}
PRIORITY_CHOICES = {"low": 1, "medium": 2, "high": 3, "urgent": 4}


def _normalise(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _missing(value: Any) -> bool:
    if value is None or value == "" or value == []:
        return True
    return isinstance(value, str) and value.strip().lower() in {"tbd", "unknown", "not provided"}


def _choice_values(choices: Any) -> list[str]:
    if isinstance(choices, list):
        return [str(value) for value in choices]
    if isinstance(choices, dict):
        values: list[str] = []
        for key, nested in choices.items():
            values.append(str(key))
            if isinstance(nested, (list, dict)):
                values.extend(_choice_values(nested))
        return values
    return []


class AgentDraftStore:
    def __init__(
        self,
        db: Database,
        schema: SchemaCache,
        audit: AuditLog,
        freshdesk: FreshdeskClient,
        validator: TicketValidator,
        defaults: TicketDefaultsService,
    ):
        self.db = db
        self.schema = schema
        self.audit = audit
        self.freshdesk = freshdesk
        self.validator = validator
        self.defaults = defaults

    def metadata(self) -> dict[str, Any]:
        overview = self.schema.overview()
        return {
            "schema_version": "a24.freshdesk_draft.v1",
            "defaults": DEFAULT_FIELD_VALUES,
            "ticket_fields": self.schema.ticket_fields(),
            "groups": self.schema.get("groups", []),
            "agents": self.schema.get("agents", []),
            "companies": self.schema.get("companies", []),
            "ticket_forms": self.schema.get("ticket_forms", []),
            "last_sync": overview["last_sync"],
            "freshdesk_form_binding": {
                "status": "tenant_verification_needed",
                "message": "Forms are synced for review and validation. Confirm how A24's Freshdesk tenant binds a selected form during API ticket creation before hard-coding submission.",
            },
        }

    def create(self, envelope: AgentDraftEnvelope) -> dict[str, Any]:
        draft_id = envelope.draft_id or f"agd_{uuid.uuid4().hex[:12]}"
        envelope.draft_id = draft_id
        envelope = self._normalised(envelope)
        now = utc_now()
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_drafts(
                    draft_id, envelope, validation_result, revision_events,
                    approval_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    json.dumps(envelope.model_dump()),
                    json.dumps(envelope.validation.model_dump()),
                    json.dumps(envelope.revision.events),
                    "awaiting_approval",
                    now,
                    now,
                ),
            )
        self.audit.record(
            "agent_draft_created",
            "local",
            draft_id=draft_id,
            validation_result=envelope.validation.model_dump(),
        )
        return self.get(draft_id)

    def get(self, draft_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM agent_drafts WHERE draft_id = ?", (draft_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="AI agent draft not found.")
        envelope = json.loads(row["envelope"])
        return {
            "draft_id": row["draft_id"],
            "envelope": envelope,
            "validation_result": json.loads(row["validation_result"]),
            "revision_events": json.loads(row["revision_events"]),
            "approval_status": row["approval_status"],
            "ticket_id": row["ticket_id"],
            "feedback_payload": json.loads(row["feedback_payload"]) if row["feedback_payload"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def update(self, draft_id: str, patch: AgentDraftPatch) -> dict[str, Any]:
        current = self.get(draft_id)
        if current["approval_status"] == "submitted":
            raise HTTPException(status_code=409, detail="Submitted AI agent drafts cannot be edited.")
        envelope = AgentDraftEnvelope.model_validate(current["envelope"])
        events = list(current["revision_events"])
        event_time = utc_now()

        if patch.ticket_fields is not None:
            fields_by_key = {field.key: field for field in envelope.ticket_fields}
            for incoming in patch.ticket_fields:
                existing = fields_by_key.get(incoming.key)
                old_value = _display(existing.display_value or existing.value) if existing else ""
                new_value = _display(incoming.display_value or incoming.value)
                incoming.source = "user_edit"
                incoming.status = "confirmed" if not _missing(incoming.value or incoming.display_value) else "missing"
                fields_by_key[incoming.key] = incoming
                if old_value != new_value:
                    events.append(self._event(incoming.key, old_value, new_value, patch.edited_by, event_time, patch.reason))
            envelope.ticket_fields = list(fields_by_key.values())

        if patch.description_sections is not None:
            sections_by_key = {section.key: section for section in envelope.description_sections}
            for incoming in patch.description_sections:
                existing = sections_by_key.get(incoming.key)
                old_value = existing.content if existing else ""
                incoming.status = "confirmed" if not _missing(incoming.content) else "missing"
                sections_by_key[incoming.key] = incoming
                if old_value != incoming.content:
                    events.append(self._event(incoming.key, old_value, incoming.content, patch.edited_by, event_time, patch.reason))
            envelope.description_sections = list(sections_by_key.values())

        envelope.revision.number += 1
        envelope.revision.events = events
        envelope = self._normalised(envelope)
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE agent_drafts
                SET envelope = ?, validation_result = ?, revision_events = ?,
                    approval_status = 'awaiting_approval', updated_at = ?
                WHERE draft_id = ?
                """,
                (
                    json.dumps(envelope.model_dump()),
                    json.dumps(envelope.validation.model_dump()),
                    json.dumps(events),
                    utc_now(),
                    draft_id,
                ),
            )
        self.audit.record(
            "agent_draft_updated",
            "local",
            draft_id=draft_id,
            validation_result=envelope.validation.model_dump(),
        )
        return self.get(draft_id)

    def validate(self, draft_id: str) -> dict[str, Any]:
        current = self.get(draft_id)
        envelope = self._normalised(AgentDraftEnvelope.model_validate(current["envelope"]))
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE agent_drafts SET envelope = ?, validation_result = ?, updated_at = ? WHERE draft_id = ?",
                (json.dumps(envelope.model_dump()), json.dumps(envelope.validation.model_dump()), utc_now(), draft_id),
            )
        self.audit.record("agent_draft_validated", "local", draft_id=draft_id, validation_result=envelope.validation.model_dump())
        return self.get(draft_id)

    def approve_and_submit(self, draft_id: str) -> dict[str, Any]:
        current = self.validate(draft_id)
        if current["approval_status"] == "submitted":
            raise HTTPException(status_code=409, detail="This AI agent draft has already been submitted.")
        validation = current["validation_result"]
        if not validation.get("valid"):
            raise HTTPException(status_code=422, detail={"message": "AI agent draft validation failed.", **validation})
        payload = self._ticket_payload(current["envelope"])
        ticket_validation = self.validator.validate(payload)
        if not ticket_validation["valid"]:
            raise HTTPException(status_code=422, detail={"message": "Freshdesk payload validation failed.", **ticket_validation})
        result = self.freshdesk.create_ticket(payload)
        ticket_id = str(result.get("id", ""))
        feedback = self._feedback_payload(current, ticket_id, payload)
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE agent_drafts
                SET approval_status = 'submitted', ticket_id = ?, feedback_payload = ?, updated_at = ?
                WHERE draft_id = ?
                """,
                (str(ticket_id), json.dumps(feedback), utc_now(), draft_id),
            )
        self.audit.record(
            "agent_draft_submitted",
            "write",
            draft_id=draft_id,
            ticket_id=ticket_id,
            validation_result=validation,
            approval_result="approved",
            api_result={"id": ticket_id, "status": "created"},
        )
        return self.get(draft_id)

    def record_feedback(self, feedback: AgentFeedbackRequest) -> dict[str, Any]:
        payload = feedback.model_dump()
        with self.db.connect() as conn:
            row = conn.execute("SELECT draft_id FROM agent_drafts WHERE draft_id = ?", (feedback.draft_id,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE agent_drafts SET feedback_payload = ?, updated_at = ? WHERE draft_id = ?",
                    (json.dumps(payload), utc_now(), feedback.draft_id),
                )
        self.audit.record(
            "agent_feedback_recorded",
            "local",
            draft_id=feedback.draft_id,
            ticket_id=feedback.ticket_id,
            api_result=payload,
        )
        return {"accepted": True, "feedback": payload}

    @staticmethod
    def _event(field_key: str, old_value: str, new_value: str, edited_by: str, timestamp: str, reason: str) -> dict[str, Any]:
        return {
            "field_key": field_key,
            "old_value": old_value,
            "new_value": new_value,
            "edited_by": edited_by,
            "timestamp": timestamp,
            "reason": reason,
        }

    def _normalised(self, envelope: AgentDraftEnvelope) -> AgentDraftEnvelope:
        existing = {field.key: field for field in envelope.ticket_fields}
        fields = []
        for key in FIELD_LABELS:
            field = existing.get(key)
            if field is None:
                field = self._default_field(key)
            fields.append(self._resolved_field(field))
        envelope.ticket_fields = fields
        envelope.rendered_description = self._render_description(envelope.description_sections)
        envelope.validation = self._validate(envelope)
        envelope.status = "ready_for_review" if envelope.validation.valid else "ready_with_gaps"
        return envelope

    def _default_field(self, key: str):
        from .models import AgentTicketField

        value = DEFAULT_FIELD_VALUES.get(key, "")
        return AgentTicketField(
            key=key,
            label=FIELD_LABELS[key],
            kind="enum" if key in {"form", "ticket_type", "status", "business_impact", "priority"} else "short_text",
            value=value,
            display_value=value,
            required=key in FIELD_LABELS,
            status="confirmed" if value else "missing",
            confidence=1.0 if value else None,
            why_this_value="Configured A24 gateway default." if value else "",
            source="default",
        )

    def _resolved_field(self, field):
        field.label = field.label or FIELD_LABELS.get(field.key, field.key.replace("_", " ").title())
        if field.key in DEFAULT_FIELD_VALUES and _missing(field.value) and _missing(field.display_value):
            field.value = DEFAULT_FIELD_VALUES[field.key]
            field.display_value = DEFAULT_FIELD_VALUES[field.key]
            field.source = "default"
            field.status = "confirmed"
        value = field.display_value or _display(field.value)

        if field.key == "group":
            return self._resolve_entity(field, self.schema.get("groups", []), "Group")
        if field.key == "agent":
            return self._resolve_agent(field)
        if field.key == "form":
            field = self._resolve_entity(field, self.schema.get("ticket_forms", []), "Form", name_keys=("title", "name"))
            return field
        if field.key == "status":
            return self._resolve_fixed_choice(field, STATUS_CHOICES)
        if field.key == "priority":
            return self._resolve_fixed_choice(field, PRIORITY_CHOICES)
        if field.key in {"business_impact", "ticket_type"}:
            return self._resolve_schema_choice(field)

        if field.required and _missing(value):
            field.status = "missing"
            field.missing_reason = field.missing_reason or f"{field.label} is required."
        elif field.status == "missing":
            field.status = "confirmed"
        field.display_value = value
        return field

    def _resolve_entity(self, field, records: list[dict[str, Any]], label: str, *, name_keys: tuple[str, ...] = ("name",)):
        value = field.display_value or _display(field.value)
        match = self._record_match(records, value, name_keys)
        if match:
            field.resolved_id = match.get("id")
            field.display_value = next((_display(match.get(key)) for key in name_keys if match.get(key)), value)
            field.status = "confirmed" if field.status not in {"approved", "user_edit"} else field.status
        elif field.required and _missing(value):
            field.status = "missing"
            field.missing_reason = field.missing_reason or f"{label} is required."
        elif records:
            field.status = "needs_human_choice"
            field.missing_reason = field.missing_reason or f"Choose a {label.lower()} from synced Freshdesk metadata."
        return field

    def _resolve_agent(self, field):
        value = field.display_value or _display(field.value)
        records = self.schema.get("agents", [])
        match = None
        for agent in records:
            names = [agent.get("name"), (agent.get("contact") or {}).get("name"), (agent.get("contact") or {}).get("email")]
            if any(self._loose_match(value, item) for item in names if item):
                match = agent
                break
        if match:
            field.resolved_id = match.get("id")
            field.display_value = (match.get("contact") or {}).get("name") or match.get("name") or value
            field.status = "confirmed"
        elif records:
            field.status = "needs_human_choice"
            field.missing_reason = field.missing_reason or "Choose an agent from synced Freshdesk metadata."
        return field

    def _resolve_fixed_choice(self, field, choices: dict[str, int]):
        value = field.display_value or _display(field.value)
        if isinstance(field.value, int) and field.value in choices.values():
            field.display_value = next(key.title() for key, item in choices.items() if item == field.value)
            field.status = "confirmed"
            return field
        key = str(value).lower()
        if key in choices:
            field.value = choices[key]
            field.display_value = key.title()
            field.status = "confirmed"
        elif field.required:
            field.status = "needs_human_choice"
            field.missing_reason = field.missing_reason or f"Choose one of: {', '.join(item.title() for item in choices)}."
        return field

    def _resolve_schema_choice(self, field):
        value = field.display_value or _display(field.value)
        schema_field = self._field_for_key(field.key)
        choices = _choice_values((schema_field or {}).get("choices"))
        if not choices:
            field.display_value = value
            return field
        match = next((choice for choice in choices if _normalise(choice) == _normalise(value)), None)
        if match:
            field.value = match
            field.display_value = match
            field.status = "confirmed"
        elif field.required:
            field.status = "needs_human_choice"
            field.missing_reason = field.missing_reason or f"Choose an allowed value for {field.label}."
        return field

    def _field_for_key(self, key: str) -> dict[str, Any] | None:
        terms = {
            "business_impact": {"business", "impact"},
            "form": {"form"},
            "product": {"product"},
            "ticket_type": {"ticket", "type"},
        }.get(key, {key})
        for field in self.schema.ticket_fields():
            text = f"{field.get('name', '')} {field.get('label', '')}".lower().replace("_", " ")
            if all(term in text for term in terms):
                return field
        return None

    @staticmethod
    def _loose_match(left: Any, right: Any) -> bool:
        a = _normalise(left)
        b = _normalise(right)
        return bool(a and b and (a == b or a in b or b in a))

    def _record_match(self, records: list[dict[str, Any]], value: Any, name_keys: tuple[str, ...]) -> dict[str, Any] | None:
        if _missing(value):
            return None
        return next(
            (
                item
                for item in records
                if str(item.get("id")) == str(value) or any(self._loose_match(value, item.get(key)) for key in name_keys)
            ),
            None,
        )

    @staticmethod
    def _render_description(sections) -> str:
        blocks = []
        for section in sections:
            title = section.title or section.key.replace("_", " ").title()
            content = section.content.strip() or "TBD"
            blocks.append(f"{title}\n{content}")
        return "\n\n".join(blocks)

    @staticmethod
    def _validate(envelope: AgentDraftEnvelope):
        from .models import AgentValidation

        blocking: list[str] = []
        warnings: list[str] = []
        for field in envelope.ticket_fields:
            value = field.display_value or field.value
            if field.required and _missing(value):
                blocking.append(f"{field.label} is required.")
            if field.key != "form" and field.required and field.status in {"missing", "conflict", "needs_human_choice"}:
                blocking.append(field.missing_reason or f"{field.label} needs review.")
            if field.key == "form":
                warnings.append("Confirm A24 Freshdesk form binding before using form selection for real API submission.")
        sections = {section.key: section for section in envelope.description_sections}
        for key in REQUIRED_SECTIONS:
            section = sections.get(key)
            label = (section.title if section else key.replace("_", " ").title())
            if not section or _missing(section.content):
                blocking.append(f"{label} is required for change-style tickets.")
        for item in envelope.missing_information:
            warnings.append(f"{item.field}: {item.reason}")
        blocking = list(dict.fromkeys(blocking))
        warnings = list(dict.fromkeys([*envelope.validation.warnings, *warnings]))
        return AgentValidation(warnings=warnings, blocking=blocking, valid=not blocking)

    def _ticket_payload(self, envelope: dict[str, Any]) -> dict[str, Any]:
        fields = {field["key"]: field for field in envelope.get("ticket_fields", [])}

        def value(key: str) -> Any:
            field = fields.get(key) or {}
            return field.get("display_value") or field.get("value")

        defaults = self.defaults.defaults("change")
        payload: dict[str, Any] = {
            "subject": _display(value("subject")).strip(),
            "description": envelope.get("rendered_description", "").strip(),
            "email": defaults.get("requester_email", ""),
            "name": _display(value("contact") or defaults.get("requester_name")).strip(),
            "priority": fields.get("priority", {}).get("value") or 1,
            "status": fields.get("status", {}).get("value") or 2,
            "source": 2,
        }
        group_id = fields.get("group", {}).get("resolved_id")
        if group_id not in (None, ""):
            payload["group_id"] = int(group_id)
        agent_id = fields.get("agent", {}).get("resolved_id")
        if agent_id not in (None, ""):
            payload["responder_id"] = int(agent_id)
        ticket_type = value("ticket_type")
        if ticket_type not in (None, ""):
            payload["type"] = _display(ticket_type)

        custom_fields = dict(defaults.get("custom_fields", {}))
        for key in ("business_impact", "product"):
            field = self._field_for_key(key)
            field_value = value(key)
            if field and field.get("name") and str(field.get("name")).startswith("cf_") and field_value not in (None, ""):
                custom_fields[str(field["name"])] = field_value
        if custom_fields:
            payload["custom_fields"] = custom_fields
        return payload

    def _feedback_payload(self, current: dict[str, Any], ticket_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        envelope = current["envelope"]
        fields = {
            field["key"]: field.get("display_value") or field.get("value")
            for field in envelope.get("ticket_fields", [])
        }
        sections = {
            section["key"]: section.get("content", "")
            for section in envelope.get("description_sections", [])
        }
        changed = [
            event
            for event in current["revision_events"]
            if event.get("edited_by") != "ai_agent" and event.get("old_value") != event.get("new_value")
        ]
        return {
            "schema_version": "a24.freshdesk_feedback.v1",
            "draft_id": current["draft_id"],
            "ticket_id": ticket_id,
            "final_fields": fields,
            "freshdesk_payload": payload,
            "final_description_sections": sections,
            "changed_fields": changed,
            "final_selected": {
                "form": fields.get("form"),
                "group": fields.get("group"),
                "ticket_type": fields.get("ticket_type"),
                "status": fields.get("status"),
            },
        }
