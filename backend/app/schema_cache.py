from __future__ import annotations

import json
from typing import Any

from .audit import AuditLog, utc_now
from .database import Database


class SchemaCache:
    SCHEMA_KEYS = {"ticket_fields", "groups", "agents", "companies", "ticket_forms"}

    def __init__(self, db: Database, audit: AuditLog):
        self.db = db
        self.audit = audit

    def put(self, key: str, payload: Any, status: str = "ok", error: str | None = None) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO schema_cache(cache_key, payload, updated_at, status, error)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at,
                    status = excluded.status,
                    error = excluded.error
                """,
                (key, json.dumps(payload), utc_now(), status, error),
            )

    def get(self, key: str, default: Any = None) -> Any:
        with self.db.connect() as conn:
            row = conn.execute("SELECT payload FROM schema_cache WHERE cache_key = ?", (key,)).fetchone()
        return json.loads(row["payload"]) if row else default

    def overview(self) -> dict[str, Any]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT cache_key, payload, updated_at, status, error FROM schema_cache ORDER BY cache_key"
            ).fetchall()
        resources: dict[str, Any] = {}
        last_sync: str | None = None
        for row in rows:
            resources[row["cache_key"]] = {
                "data": json.loads(row["payload"]),
                "updated_at": row["updated_at"],
                "status": row["status"],
                "error": row["error"],
            }
            if row["cache_key"] in self.SCHEMA_KEYS and (not last_sync or row["updated_at"] > last_sync):
                last_sync = row["updated_at"]
        return {"last_sync": last_sync, "resources": resources}

    def ticket_fields(self) -> list[dict[str, Any]]:
        return self.get("ticket_fields", [])

    def required_ticket_fields(self) -> list[dict[str, Any]]:
        return [
            field
            for field in self.ticket_fields()
            if field.get("required_for_agents") or field.get("required_for_customers")
        ]
