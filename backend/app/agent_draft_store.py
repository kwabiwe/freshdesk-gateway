from __future__ import annotations

import json
import re
import uuid
from html import escape
from typing import Any

from fastapi import HTTPException

from .audit import AuditLog, utc_now
from .database import Database
from .freshdesk_client import FreshdeskClient
from .freshdesk_payload_builder import FreshdeskPayloadBuilder
from .models import AgentDraftEnvelope, AgentDraftPatch, AgentFeedbackRequest
from .schema_cache import SchemaCache
from .ticket_defaults import TicketDefaultsService
from .validators import TicketValidator


DEFAULT_FIELD_VALUES = {
    "product": "A24 Support",
    "contact": "",
    "agent": "Kwabiwe Sibanda",
    "group": "L3 Engineer",
    "business_impact": "Minor",
}
FIELD_LABELS = {
    "product": "Product",
    "contact": "Contact",
    "subject": "Subject",
    "form": "Form",
    "background_for_the_change": "Background for the Change",
    "change_type": "Change Type",
    "requested_by": "Requested By",
    "change_owner": "Change owner",
    "change_category": "Change Category",
    "chg_business_impact": "CHG Business Impact",
    "change_state": "Change State",
    "approval_state": "Approval State",
    "ticket_type": "Ticket Type",
    "status": "Status",
    "business_impact": "Business Impact",
    "group": "Group",
    "agent": "Agent",
    "priority": "Priority",
    "customer": "Customer",
    "reminder_date": "Reminder Date",
    "tags": "Tags",
}
REVIEW_REQUIRED_KEYS = {"contact", "subject", "change_owner", "change_state", "status", "priority", "customer"}
BUILTIN_REVIEW_KEYS = {"contact", "subject", "status", "group", "agent", "priority", "tags"}
BASE_FIELD_ORDER = ["contact", "subject", "form"]
COMMON_FIELD_ORDER = ["status", "business_impact", "group", "agent", "priority"]
SCHEMA_FIELD_KEY_ALIASES = {
    "product": "product",
    "requester": "contact",
    "subject": "subject",
    "cf_form2": "form",
    "cf_background_for_the_change": "background_for_the_change",
    "cf_change_type": "change_type",
    "cf_requested_by": "requested_by",
    "cf_change_owner": "change_owner",
    "cf_change_catergory": "change_category",
    "cf_change_category": "change_category",
    "cf_chg_business_impact": "chg_business_impact",
    "cf_change_state": "change_state",
    "cf_approval_state": "approval_state",
    "cf_type": "ticket_type",
    "cf_ticket_type": "ticket_type",
    "cf_customer967575": "customer",
    "cf_customer": "customer",
    "cf_business_impact723800": "business_impact",
    "cf_business_impact": "business_impact",
    "cf_reminder_date": "reminder_date",
    "status": "status",
    "group": "group",
    "agent": "agent",
    "priority": "priority",
}
FIELD_SCHEMA_PREFERENCES = {
    "product": ("product",),
    "contact": ("requester",),
    "subject": ("subject",),
    "form": ("cf_form2",),
    "background_for_the_change": ("cf_background_for_the_change",),
    "change_type": ("cf_change_type",),
    "requested_by": ("cf_requested_by",),
    "change_owner": ("cf_change_owner",),
    "change_category": ("cf_change_catergory", "cf_change_category"),
    "chg_business_impact": ("cf_chg_business_impact",),
    "change_state": ("cf_change_state",),
    "approval_state": ("cf_approval_state",),
    "ticket_type": ("cf_type", "cf_ticket_type"),
    "customer": ("cf_customer967575", "cf_customer"),
    "status": ("status",),
    "business_impact": ("cf_business_impact723800", "cf_business_impact"),
    "group": ("group",),
    "agent": ("agent",),
    "priority": ("priority",),
    "reminder_date": ("cf_reminder_date",),
}
CHANGE_REQUEST_REVIEW_ORDER = [
    "product",
    "contact",
    "subject",
    "form",
    "background_for_the_change",
    "change_type",
    "requested_by",
    "change_owner",
    "change_category",
    "chg_business_impact",
    "change_state",
    "approval_state",
    "ticket_type",
    "status",
    "business_impact",
    "group",
    "agent",
    "priority",
    "customer",
    "reminder_date",
    "tags",
]
CHANGE_REQUEST_FIELD_NAMES = [
    "product",
    "cf_background_for_the_change",
    "cf_change_type",
    "cf_requested_by",
    "cf_change_owner",
    "cf_change_catergory",
    "cf_chg_business_impact",
    "cf_change_state",
    "cf_approval_state",
    "cf_type",
    "cf_customer967575",
    "status",
    "cf_business_impact723800",
    "group",
    "agent",
    "priority",
]
INCIDENT_REQUEST_FIELD_NAMES = [
    "cf_type",
    "cf_rack",
    "cf_customer967575",
    "status",
    "cf_business_impact723800",
    "group",
    "agent",
    "priority",
]
PROFESSIONAL_SERVICES_FIELD_NAMES = [
    "cf_customer967575",
    "cf_requested_by",
    "cf_reminder_date",
    "status",
    "group",
    "agent",
    "priority",
]
FORM_FIELD_PROFILES = {
    "changerequest": CHANGE_REQUEST_FIELD_NAMES,
    "a24incident": INCIDENT_REQUEST_FIELD_NAMES,
    "customerincident": INCIDENT_REQUEST_FIELD_NAMES,
    "a24request": INCIDENT_REQUEST_FIELD_NAMES,
    "customerrequest": INCIDENT_REQUEST_FIELD_NAMES,
    "professionalservices": PROFESSIONAL_SERVICES_FIELD_NAMES,
    "scheduledprofessionalservicesengagement": PROFESSIONAL_SERVICES_FIELD_NAMES,
}
REQUIRED_SECTIONS_BY_PROFILE = {
    "change": {"scope", "implementation", "rollback", "verification", "config_items"},
    "standard": set(),
}
APPROVAL_CONFIRMATIONS = {
    "create": "CREATE",
    "update": "UPDATE",
    "bulk_create": "CREATE BULK",
}
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
        self.payload_builder = FreshdeskPayloadBuilder(schema, defaults)

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
            "freshdesk_form_profiles": self._form_profiles(),
            "last_sync": overview["last_sync"],
            "freshdesk_form_binding": {
                "status": "custom_field_bound",
                "field_name": "cf_form2",
                "message": "A24's visible Form dropdown is the custom cf_form2 field. The review ledger expands fields from that selected form profile before approval.",
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
        return self._row_response(row)

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_drafts ORDER BY created_at DESC, updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_response(row) for row in rows]

    def _row_response(self, row) -> dict[str, Any]:
        envelope = json.loads(row["envelope"])
        response = {
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
        response["payload_preview"] = self._payload_preview(envelope)
        return response

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

    def delete(self, draft_id: str) -> dict[str, Any]:
        current = self.get(draft_id)
        if current["approval_status"] == "submitted":
            raise HTTPException(status_code=409, detail="Submitted AI agent drafts cannot be removed from the review inbox.")
        with self.db.connect() as conn:
            conn.execute("DELETE FROM agent_drafts WHERE draft_id = ?", (draft_id,))
        self.audit.record("agent_draft_deleted", "local", draft_id=draft_id)
        return {"draft_id": draft_id, "deleted": True}

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

    def payload_preview(self, draft_id: str) -> dict[str, Any]:
        current = self.validate(draft_id)
        return current["payload_preview"]

    def approve_and_submit(self, draft_id: str, confirmation: str) -> dict[str, Any]:
        current = self.validate(draft_id)
        if current["approval_status"] == "submitted":
            raise HTTPException(status_code=409, detail="This AI agent draft has already been submitted.")
        mode = current["envelope"].get("mode", "create")
        expected_confirmation = APPROVAL_CONFIRMATIONS.get(mode, "CREATE")
        if confirmation != expected_confirmation:
            raise HTTPException(status_code=400, detail=f'Type "{expected_confirmation}" to approve this exact AI agent draft.')
        validation = current["validation_result"]
        if not validation.get("valid"):
            raise HTTPException(status_code=422, detail={"message": "AI agent draft validation failed.", **validation})
        envelope = current["envelope"]
        if mode == "bulk_create":
            payloads = self._bulk_payloads(envelope)
            self.freshdesk.limiter.ensure_available("write", "ticket_create", amount=len(payloads))
            results = [self.freshdesk.create_ticket(payload) for payload in payloads]
            ticket_id = ",".join(str(result.get("id", "")) for result in results)
            payload: dict[str, Any] = {"bulk_payloads": payloads}
            api_result = {"ids": [result.get("id") for result in results], "status": "created"}
        else:
            payload = self._ticket_payload(envelope)
            ticket_validation = self.validator.validate(payload, require_requester=mode != "update")
            if not ticket_validation["valid"]:
                raise HTTPException(status_code=422, detail={"message": "Freshdesk payload validation failed.", **ticket_validation})
            if mode == "update":
                target = envelope.get("target_ticket_id")
                if target in (None, ""):
                    raise HTTPException(status_code=422, detail="Update mode requires target_ticket_id.")
                result = self.freshdesk.update_ticket(target, payload)
                ticket_id = str(result.get("id") or target)
                api_result = {"id": ticket_id, "status": "updated"}
            else:
                result = self.freshdesk.create_ticket(payload)
                ticket_id = str(result.get("id", ""))
                api_result = {"id": ticket_id, "status": "created"}
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
            api_result=api_result,
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
        envelope.ticket_fields = self._normalised_fields(envelope.ticket_fields, envelope.ticket_profile)
        envelope.rendered_description = self._render_description(envelope.description_sections)
        if envelope.mode == "bulk_create":
            envelope.bulk_items = self._normalised_bulk_items(envelope)
        envelope.validation = self._validate(envelope)
        envelope.status = "ready_for_review" if envelope.validation.valid else "ready_with_gaps"
        return envelope

    def _normalised_fields(self, ticket_fields, ticket_profile: str = "change") -> list[Any]:
        existing = {}
        for field in ticket_fields:
            canonical_key = self._review_key_for_schema_name(field.key)
            if canonical_key != field.key:
                field.schema_field_name = field.schema_field_name or field.key
                field.key = canonical_key
            existing[field.key] = field
        form_value = self._field_value(existing.get("form"))
        ordered_keys = self._field_order_for_form(form_value, ticket_profile)
        ordered_keys.extend(key for key in existing if key not in ordered_keys)
        fields = []
        for key in ordered_keys:
            field = existing.get(key)
            schema_field = self._schema_field_for_key(key)
            if field is None:
                field = self._default_field(key, schema_field=schema_field, ticket_profile=ticket_profile)
            elif schema_field and not field.schema_field_name:
                field.schema_field_name = str(schema_field.get("name") or "")
            fields.append(self._resolved_field(field))
        return fields

    def _field_order_for_form(self, form_value: Any, ticket_profile: str) -> list[str]:
        if ticket_profile == "change" or _normalise(form_value) == "changerequest":
            return self._change_request_field_order(form_value)
        keys = list(BASE_FIELD_ORDER)
        keys.extend(self._review_key_for_schema_name(name) for name in self._profile_field_names(form_value, ticket_profile))
        keys.extend(COMMON_FIELD_ORDER)
        return list(dict.fromkeys(keys))

    def _change_request_field_order(self, form_value: Any) -> list[str]:
        ticket_form_fields = self._ticket_form_field_names(form_value)
        if ticket_form_fields:
            dynamic = [self._review_key_for_schema_name(name) for name in ticket_form_fields]
            preferred = [key for key in CHANGE_REQUEST_REVIEW_ORDER if key in dynamic or self._review_key_available(key)]
            return list(dict.fromkeys([*preferred, *dynamic]))
        return [key for key in CHANGE_REQUEST_REVIEW_ORDER if self._review_key_available(key)]

    def _review_key_available(self, key: str) -> bool:
        if key in BUILTIN_REVIEW_KEYS:
            return True
        return self._schema_field_for_key(key) is not None

    def _profile_field_names(self, form_value: Any, ticket_profile: str) -> list[str]:
        ticket_form_fields = self._ticket_form_field_names(form_value)
        if ticket_form_fields:
            return self._existing_schema_names(ticket_form_fields)
        profile = FORM_FIELD_PROFILES.get(_normalise(form_value))
        if profile is not None:
            return self._existing_schema_names(profile)
        if ticket_profile == "change":
            return self._existing_schema_names(CHANGE_REQUEST_FIELD_NAMES)
        return self._existing_schema_names(INCIDENT_REQUEST_FIELD_NAMES)

    def _ticket_form_field_names(self, form_value: Any) -> list[str]:
        if _missing(form_value):
            return []
        wanted = _normalise(form_value)
        for form in self.schema.get("ticket_forms", []):
            names = [form.get("name"), form.get("title"), form.get("label")]
            if not any(_normalise(name) == wanted for name in names if name):
                continue
            raw_fields = form.get("fields") or form.get("ticket_fields") or form.get("field_names") or []
            names_out: list[str] = []
            for item in raw_fields:
                if isinstance(item, str):
                    names_out.append(item)
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("field_name")
                    if name:
                        names_out.append(str(name))
            return names_out
        return []

    def _form_profiles(self) -> list[dict[str, Any]]:
        profiles = []
        for form in self._choice_values_for_schema_name("cf_form2"):
            field_names = self._profile_field_names(form, "change" if _normalise(form) == "changerequest" else "standard")
            profiles.append(
                {
                    "form": form,
                    "field_names": field_names,
                    "fields": [self._compact_schema_field(field) for field in self._schema_fields_by_names(field_names)],
                }
            )
        return profiles

    @staticmethod
    def _field_value(field: Any) -> Any:
        if field is None:
            return ""
        return field.display_value or field.value or ""

    def _existing_schema_names(self, names: list[str]) -> list[str]:
        available = {str(field.get("name")) for field in self.schema.ticket_fields()}
        return [name for name in names if name in available]

    def _schema_fields_by_names(self, names: list[str]) -> list[dict[str, Any]]:
        fields = {str(field.get("name")): field for field in self.schema.ticket_fields()}
        return [fields[name] for name in names if name in fields]

    def _review_key_for_schema_name(self, name: str) -> str:
        return SCHEMA_FIELD_KEY_ALIASES.get(name, name)

    def _choice_values_for_schema_name(self, name: str) -> list[str]:
        field = next((item for item in self.schema.ticket_fields() if item.get("name") == name), None)
        return _choice_values((field or {}).get("choices"))

    @staticmethod
    def _compact_schema_field(field: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": field.get("name"),
            "label": field.get("label") or field.get("label_for_customers") or field.get("name"),
            "type": field.get("type"),
            "required_for_agents": bool(field.get("required_for_agents")),
            "choices": _choice_values(field.get("choices")),
        }

    @staticmethod
    def _field_kind(schema_field: dict[str, Any] | None, key: str) -> str:
        if schema_field and schema_field.get("choices"):
            return "enum"
        field_type = str((schema_field or {}).get("type") or "")
        if "text" in field_type and "custom" in field_type:
            return "short_text"
        if key in {
            "form",
            "ticket_type",
            "status",
            "business_impact",
            "priority",
            "change_type",
            "change_category",
            "chg_business_impact",
            "change_state",
            "approval_state",
            "customer",
        }:
            return "enum"
        if key in {"group", "agent", "contact", "product"}:
            return "entity_ref"
        if key in {"background_for_the_change"}:
            return "long_text"
        return "short_text"

    def _normalised_bulk_items(self, envelope: AgentDraftEnvelope):
        from .models import AgentBulkItem

        items: list[AgentBulkItem] = []
        template_fields = {field.key: field for field in envelope.ticket_fields}
        template_sections = {section.key: section for section in envelope.description_sections}
        for index, item in enumerate(envelope.bulk_items, start=1):
            item.row_id = item.row_id or f"row_{index:03d}"
            item.ticket_profile = item.ticket_profile or envelope.ticket_profile
            fields_by_key = {**template_fields, **{field.key: field for field in item.ticket_fields}}
            item.ticket_fields = self._normalised_fields(list(fields_by_key.values()), item.ticket_profile or envelope.ticket_profile)
            sections_by_key = {**template_sections, **{section.key: section for section in item.description_sections}}
            item.description_sections = list(sections_by_key.values())
            item.rendered_description = self._render_description(item.description_sections)
            item.validation = self._validate_parts(
                item.ticket_fields,
                item.description_sections,
                item.missing_information,
                item.ticket_profile or envelope.ticket_profile,
                include_form_warning=False,
            )
            items.append(item)
        return items

    def _default_field(self, key: str, schema_field: dict[str, Any] | None = None, ticket_profile: str = "change"):
        from .models import AgentTicketField

        schema_name = str((schema_field or {}).get("name") or "")
        default_values = self.defaults.defaults(ticket_profile)
        if key == "contact":
            requester_email = default_values.get("requester_email") or ""
            requester_name = default_values.get("requester_name") or ""
            value = f"{requester_name} <{requester_email}>".strip() if requester_name and requester_email else requester_email or requester_name
        else:
            value = (default_values.get("custom_fields") or {}).get(schema_name, DEFAULT_FIELD_VALUES.get(key, ""))
        required = bool((schema_field or {}).get("required_for_agents")) or key in REVIEW_REQUIRED_KEYS
        return AgentTicketField(
            key=key,
            label=(schema_field or {}).get("label") or (schema_field or {}).get("label_for_customers") or FIELD_LABELS.get(key, key.replace("_", " ").title()),
            kind=self._field_kind(schema_field, key),
            schema_field_name=schema_name,
            payload_path=self.payload_builder.payload_path(key, schema_name),
            value=value,
            display_value=value,
            required=required,
            choices=_choice_values((schema_field or {}).get("choices")),
            status="confirmed" if value else "missing",
            confidence=1.0 if value else None,
            why_this_value="A24 gateway default from synced Freshdesk schema." if value else "",
            source="default",
        )

    def _resolved_field(self, field):
        schema_field = self._schema_field_for_field(field)
        if schema_field:
            field.schema_field_name = str(schema_field.get("name") or "")
            field.label = schema_field.get("label") or schema_field.get("label_for_customers") or field.label
            field.kind = self._field_kind(schema_field, field.key)
            field.required = bool(schema_field.get("required_for_agents")) or field.required
            field.choices = _choice_values(schema_field.get("choices"))
        field.label = field.label or FIELD_LABELS.get(field.key, field.key.replace("_", " ").title())
        field.payload_path = self.payload_builder.payload_path(field.key, field.schema_field_name)
        if field.key in DEFAULT_FIELD_VALUES and field.key != "contact" and _missing(field.value) and _missing(field.display_value):
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
            return self._resolve_schema_choice(field)
        if field.key == "status":
            return self._resolve_fixed_choice(field, STATUS_CHOICES)
        if field.key == "priority":
            return self._resolve_fixed_choice(field, PRIORITY_CHOICES)
        if schema_field and schema_field.get("choices"):
            return self._resolve_schema_choice(field)
        if field.key in {"business_impact", "product", "ticket_type", "customer", "change_type", "change_category", "chg_business_impact", "change_state", "approval_state"}:
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
        schema_field = self._schema_field_for_field(field)
        raw_choices = (schema_field or {}).get("choices")
        choices = _choice_values(raw_choices)
        if not choices:
            field.display_value = value
            return field
        match = next((choice for choice in choices if _normalise(choice) == _normalise(value)), None)
        if match:
            field.value = match
            field.display_value = match
            if isinstance(raw_choices, dict) and match in raw_choices and not isinstance(raw_choices[match], (list, dict)):
                field.resolved_id = raw_choices[match]
            field.status = "confirmed"
        elif field.required:
            field.status = "needs_human_choice"
            field.missing_reason = field.missing_reason or f"Choose an allowed value for {field.label}."
        return field

    def _schema_field_for_field(self, field) -> dict[str, Any] | None:
        if field.schema_field_name:
            match = next((item for item in self.schema.ticket_fields() if item.get("name") == field.schema_field_name), None)
            if match:
                return match
        return self._schema_field_for_key(field.key)

    def _schema_field_for_key(self, key: str) -> dict[str, Any] | None:
        if key.startswith("cf_"):
            return next((field for field in self.schema.ticket_fields() if field.get("name") == key), None)
        for name in FIELD_SCHEMA_PREFERENCES.get(key, ()):
            match = next((field for field in self.schema.ticket_fields() if field.get("name") == name), None)
            if match:
                return match
        return self._field_for_key(key)

    def _field_for_key(self, key: str) -> dict[str, Any] | None:
        terms = {
            "business_impact": {"business", "impact"},
            "form": {"form"},
            "product": {"product"},
            "ticket_type": {"ticket", "type"},
            "customer": {"customer"},
            "background_for_the_change": {"background", "change"},
            "change_type": {"change", "type"},
            "requested_by": {"requested", "by"},
            "change_owner": {"change", "owner"},
            "change_category": {"change", "category"},
            "chg_business_impact": {"chg", "business", "impact"},
            "change_state": {"change", "state"},
            "approval_state": {"approval", "state"},
            "reminder_date": {"reminder", "date"},
        }.get(key, {key})
        for field in self.schema.ticket_fields():
            text = f"{field.get('name', '')} {field.get('label', '')}".lower().replace("_", " ")
            if key == "business_impact" and ("chg" in text or "change" in text):
                continue
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
    def _section_html(title: str, content: str) -> str:
        lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
        if len(lines) > 1:
            body = "<ol>" + "".join(f"<li>{escape(line)}</li>" for line in lines) + "</ol>"
        else:
            body = f"<p>{escape(lines[0] if lines else 'TBD')}</p>"
        return f"<h2>{escape(title)}</h2>{body}"

    @classmethod
    def _render_description(cls, sections) -> str:
        blocks = []
        for section in sections:
            if section.key in {"assumptions_missing"}:
                continue
            title = section.title or section.key.replace("_", " ").title()
            content = section.content.strip() or "TBD"
            blocks.append(cls._section_html(title, content))
        return "".join(blocks)

    @staticmethod
    def _validate_parts(ticket_fields, description_sections, missing_information, ticket_profile: str, *, include_form_warning: bool = True):
        from .models import AgentValidation

        blocking: list[str] = []
        warnings: list[str] = []
        for field in ticket_fields:
            value = field.display_value or field.value
            if field.required and _missing(value):
                blocking.append(f"{field.label} is required.")
            if field.key != "form" and field.required and field.status in {"missing", "conflict", "needs_human_choice"}:
                blocking.append(field.missing_reason or f"{field.label} needs review.")
            if include_form_warning and field.key == "form" and not field.schema_field_name:
                warnings.append("Confirm A24 Freshdesk form binding before using form selection for real API submission.")
        sections = {section.key: section for section in description_sections}
        for key in REQUIRED_SECTIONS_BY_PROFILE.get(ticket_profile, set()):
            section = sections.get(key)
            label = (section.title if section else key.replace("_", " ").title())
            if not section or _missing(section.content):
                blocking.append(f"{label} is required for change-style tickets.")
        if ticket_profile == "standard" and not any(not _missing(section.content) for section in description_sections):
            blocking.append("Description is required.")
        for item in missing_information:
            warnings.append(f"{item.field}: {item.reason}")
        blocking = list(dict.fromkeys(blocking))
        warnings = list(dict.fromkeys(warnings))
        return AgentValidation(warnings=warnings, blocking=blocking, valid=not blocking)

    def _validate(self, envelope: AgentDraftEnvelope):
        from .models import AgentValidation

        if envelope.mode == "update" and envelope.target_ticket_id in (None, ""):
            return AgentValidation(warnings=[], blocking=["Update mode requires target_ticket_id."], valid=False)
        if envelope.mode == "bulk_create":
            blocking: list[str] = []
            warnings: list[str] = []
            if not envelope.bulk_items:
                blocking.append("Bulk create mode requires at least one bulk item.")
            for item in envelope.bulk_items:
                validation = item.validation
                prefix = item.title or item.row_id
                blocking.extend(f"{prefix}: {message}" for message in validation.blocking)
                warnings.extend(f"{prefix}: {message}" for message in validation.warnings)
            return AgentValidation(warnings=list(dict.fromkeys(warnings)), blocking=list(dict.fromkeys(blocking)), valid=not blocking)
        result = self._validate_parts(
            envelope.ticket_fields,
            envelope.description_sections,
            envelope.missing_information,
            envelope.ticket_profile,
        )
        payload = self._ticket_payload(envelope.model_dump())
        payload_validation = self.validator.validate(
            payload,
            require_requester=envelope.mode != "update",
        )
        result.blocking = list(dict.fromkeys([*result.blocking, *self._payload_validation_blocking(payload_validation, payload)]))
        result.warnings = list(dict.fromkeys([*envelope.validation.warnings, *result.warnings]))
        result.valid = not result.blocking
        return result

    @staticmethod
    def _payload_validation_blocking(payload_validation: dict[str, Any], payload: dict[str, Any] | None = None) -> list[str]:
        payload = payload or {}
        blocking: list[str] = []
        for field in payload_validation.get("missing_fields", []):
            if field.get("name") == "company" and (payload.get("email") or payload.get("requester_id")):
                blocking.append(
                    "Company is required, but the gateway could not verify that the selected Contact belongs to a Freshdesk company. "
                    "Use a Contact email that matches a synced company domain or select a resolved Contact/company before approval."
                )
            else:
                blocking.append(f"Freshdesk payload is missing {field.get('label') or field.get('name')}.")
        invalid_fields = payload_validation.get("invalid_fields") or []
        if invalid_fields:
            blocking.append(f"Freshdesk payload has unsupported top-level field(s): {', '.join(invalid_fields)}.")
        invalid_custom = payload_validation.get("invalid_custom_fields") or []
        if invalid_custom:
            blocking.append(f"Freshdesk payload has unsupported custom field(s): {', '.join(invalid_custom)}.")
        for item in payload_validation.get("invalid_custom_field_values") or []:
            allowed = ", ".join(str(value) for value in item.get("allowed_values", []))
            blocking.append(f"{item.get('label') or item.get('name')} must be one of: {allowed}.")
        for item in payload_validation.get("invalid_company_association") or []:
            blocking.append(
                f"Requester {item.get('requester_email')} does not belong to company {item.get('company_name') or item.get('company_id')}."
            )
        if payload_validation.get("invalid_tags"):
            blocking.append("Freshdesk payload tags must be an array of non-empty strings.")
        return blocking

    def _ticket_payload(self, envelope: dict[str, Any], bulk_item: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.payload_builder.build(envelope, bulk_item).payload

    def _payload_preview(self, envelope: dict[str, Any]) -> dict[str, Any]:
        if envelope.get("mode") == "bulk_create":
            payloads = [self._ticket_payload(envelope, item) for item in envelope.get("bulk_items", [])]
            validations = [self.validator.validate(payload) for payload in payloads]
            return {
                "payload": {"bulk_payloads": payloads},
                "validation": {"valid": all(item.get("valid") for item in validations), "rows": validations},
                "mapping_notes": [],
            }
        built = self.payload_builder.build(envelope)
        return {
            "payload": built.payload,
            "validation": self.validator.validate(built.payload, require_requester=envelope.get("mode") != "update"),
            "mapping_notes": built.mapping_notes,
        }

    def _bulk_payloads(self, envelope: dict[str, Any]) -> list[dict[str, Any]]:
        payloads = [self._ticket_payload(envelope, item) for item in envelope.get("bulk_items", [])]
        failures = []
        for index, payload in enumerate(payloads, start=1):
            validation = self.validator.validate(payload)
            if not validation["valid"]:
                failures.append({"row": index, **validation})
        if failures:
            raise HTTPException(status_code=422, detail={"message": "Freshdesk payload validation failed for one or more bulk rows.", "rows": failures})
        return payloads

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
