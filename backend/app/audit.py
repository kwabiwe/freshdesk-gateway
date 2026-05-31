from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .database import Database
from .sensitive_data import redact_text


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditLog:
    def __init__(self, db: Database):
        self.db = db

    def record(
        self,
        action_type: str,
        action_mode: str = "local",
        *,
        draft_id: str | None = None,
        ticket_id: str | int | None = None,
        ticket_subject: str | None = None,
        request_summary: str | None = None,
        validation_result: Any = None,
        approval_result: str | None = None,
        api_result: Any = None,
        error: str | None = None,
    ) -> None:
        def safe_json(value: Any) -> str | None:
            if value is None:
                return None
            return redact_text(json.dumps(value, default=str), max_length=500)

        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_log(
                    created_at, action_type, action_mode, draft_id, ticket_id,
                    ticket_subject, request_summary, validation_result,
                    approval_result, api_result, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    action_type,
                    action_mode,
                    draft_id,
                    str(ticket_id) if ticket_id is not None else None,
                    redact_text(ticket_subject or "", 160) or None,
                    redact_text(request_summary or "", 240) or None,
                    safe_json(validation_result),
                    redact_text(approval_result or "", 120) or None,
                    safe_json(api_result),
                    redact_text(error or "", 300) or None,
                ),
            )

    def list(self, limit: int = 100, action_mode: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM audit_log"
        params: list[Any] = []
        if action_mode:
            query += " WHERE action_mode = ?"
            params.append(action_mode)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(min(max(limit, 1), 500))
        with self.db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
