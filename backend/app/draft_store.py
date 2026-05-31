from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from .audit import AuditLog, utc_now
from .database import Database
from .ticket_templates import clean_ticket_payload, render_change_description
from .validators import TicketValidator


class DraftStore:
    def __init__(self, db: Database, settings_provider, validator: TicketValidator, audit: AuditLog):
        self.db = db
        self.settings_provider = settings_provider
        self.validator = validator
        self.audit = audit

    def _expiry(self) -> str:
        minutes = self.settings_provider().draft_expiry_minutes
        return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()

    def _row(self, row) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = json.loads(item["payload"])
        item["validation_result"] = json.loads(item["validation_result"])
        item["api_result"] = json.loads(item["api_result"]) if item["api_result"] else None
        if item["generated_output"]:
            try:
                item["generated_output"] = json.loads(item["generated_output"])
            except json.JSONDecodeError:
                pass
        item["expired"] = datetime.fromisoformat(item["expires_at"]) <= datetime.now(timezone.utc)
        return item

    def create(
        self,
        values: dict[str, Any],
        *,
        kind: str = "generic",
        batch_id: str | None = None,
        generated_output: str = "",
    ) -> dict[str, Any]:
        if kind == "change" and not values.get("description"):
            values["description"] = render_change_description(values)
        if not values.get("description"):
            values["description"] = values.get("rough_notes", "")
        payload = clean_ticket_payload(values)
        validation = self.validator.validate(payload)
        draft_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO drafts(
                    draft_id, batch_id, kind, payload, source_input, generated_output,
                    validation_status, validation_result, approval_status, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_id,
                    batch_id,
                    kind,
                    json.dumps(payload),
                    values.get("rough_notes", ""),
                    generated_output,
                    "valid" if validation["valid"] else "invalid",
                    json.dumps(validation),
                    "awaiting_approval",
                    utc_now(),
                    self._expiry(),
                ),
            )
        self.audit.record(
            "draft_created",
            "local",
            draft_id=draft_id,
            ticket_subject=payload.get("subject"),
            validation_result=validation,
        )
        return self.get(draft_id)

    def get(self, draft_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM drafts WHERE draft_id = ?", (draft_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Draft not found.")
        return self._row(row)

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM drafts ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(row) for row in rows]

    def update(self, draft_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        draft = self.get(draft_id)
        if draft["approval_status"] == "created":
            raise HTTPException(status_code=409, detail="Created drafts cannot be edited.")
        payload = {**draft["payload"]}
        mapping = {"requester_email": "email", "requester_name": "name"}
        for key, value in updates.items():
            if value is None:
                continue
            payload[mapping.get(key, key)] = value
        validation = self.validator.validate(payload)
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE drafts SET payload = ?, validation_status = ?, validation_result = ?,
                    approval_status = 'awaiting_approval'
                WHERE draft_id = ?
                """,
                (json.dumps(payload), "valid" if validation["valid"] else "invalid", json.dumps(validation), draft_id),
            )
        self.audit.record("draft_updated", "local", draft_id=draft_id, validation_result=validation)
        return self.get(draft_id)

    def delete(self, draft_id: str) -> None:
        draft = self.get(draft_id)
        if draft["approval_status"] == "created":
            raise HTTPException(status_code=409, detail="Created drafts cannot be deleted.")
        with self.db.connect() as conn:
            conn.execute("DELETE FROM drafts WHERE draft_id = ?", (draft_id,))
        self.audit.record("draft_deleted", "local", draft_id=draft_id)

    def validate(self, draft_id: str) -> dict[str, Any]:
        draft = self.get(draft_id)
        validation = self.validator.validate(draft["payload"])
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE drafts SET validation_status = ?, validation_result = ? WHERE draft_id = ?",
                ("valid" if validation["valid"] else "invalid", json.dumps(validation), draft_id),
            )
        self.audit.record("draft_validated", "local", draft_id=draft_id, validation_result=validation)
        return self.get(draft_id)

    def mark_created(self, draft_id: str, api_result: dict[str, Any]) -> dict[str, Any]:
        summary = {"id": api_result.get("id"), "status": "created"}
        with self.db.connect() as conn:
            conn.execute(
                """
                UPDATE drafts SET approval_status = 'created', ticket_id = ?, api_result = ?
                WHERE draft_id = ?
                """,
                (str(api_result.get("id", "")), json.dumps(summary), draft_id),
            )
        return self.get(draft_id)

    @staticmethod
    def parse_rows(text: str) -> list[dict[str, str]]:
        stripped = text.strip()
        if stripped.startswith("["):
            rows = json.loads(stripped)
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise HTTPException(status_code=422, detail="JSON batch input must be an array of objects.")
            return [{str(k): str(v) for k, v in row.items()} for row in rows]
        try:
            dialect = csv.Sniffer().sniff(stripped[:2048], delimiters=",\t;|")
        except csv.Error:
            dialect = csv.excel_tab if "\t" in stripped else csv.excel
        rows = list(csv.DictReader(io.StringIO(stripped), dialect=dialect))
        if not rows or not rows[0]:
            raise HTTPException(status_code=422, detail="Batch input needs a header row and at least one data row.")
        return [{str(k).strip(): (v or "").strip() for k, v in row.items() if k} for row in rows]

    def create_batch(self, request: dict[str, Any]) -> dict[str, Any]:
        rows = self.parse_rows(request["text"])
        batch_id = str(uuid.uuid4())
        drafts: list[dict[str, Any]] = []
        for row in rows:
            lowered = {key.lower().replace(" ", "_"): value for key, value in row.items()}
            name = lowered.get("name") or lowered.get("full_name") or ""
            subject_suffix = f" - {name}" if name else ""
            details = "\n".join(f"{key.replace('_', ' ').title()}: {value}" for key, value in lowered.items() if value)
            values = {
                **request,
                "subject": f"{request['base_subject']}{subject_suffix}",
                "description": f"{request['base_description']}\n\n{details}".strip(),
                "requester_name": name,
                "requester_email": lowered.get("email") or request.get("requester_email", ""),
                "rough_notes": details,
            }
            drafts.append(self.create(values, kind="batch", batch_id=batch_id))
        self.audit.record("batch_drafted", "local", request_summary=f"{len(drafts)} drafts", approval_result="awaiting_approval")
        return {"batch_id": batch_id, "drafts": drafts}
