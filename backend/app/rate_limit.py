from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from .audit import AuditLog, utc_now
from .config import Settings
from .database import Database


class RateLimiter:
    def __init__(self, db: Database, settings_provider, audit: AuditLog):
        self.db = db
        self.settings_provider = settings_provider
        self.audit = audit

    def _counts(self) -> dict[str, int]:
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT action_mode, action_type, COUNT(*) AS count "
                "FROM rate_events WHERE created_at >= ? GROUP BY action_mode, action_type",
                (since,),
            ).fetchall()
        counts = {"reads": 0, "writes": 0, "ticket_creations": 0}
        for row in rows:
            if row["action_mode"] == "read":
                counts["reads"] += row["count"]
            elif row["action_mode"] == "write":
                counts["writes"] += row["count"]
            if row["action_type"] == "ticket_create":
                counts["ticket_creations"] += row["count"]
        return counts

    def status(self) -> dict[str, int]:
        settings: Settings = self.settings_provider()
        counts = self._counts()
        return {
            **counts,
            "reads_limit": settings.max_reads_per_hour,
            "writes_limit": settings.max_writes_per_hour,
            "ticket_creations_limit": settings.max_ticket_creations_per_hour,
            "reads_remaining": max(settings.max_reads_per_hour - counts["reads"], 0),
            "writes_remaining": max(settings.max_writes_per_hour - counts["writes"], 0),
            "ticket_creations_remaining": max(
                settings.max_ticket_creations_per_hour - counts["ticket_creations"], 0
            ),
        }

    def ensure_available(self, mode: str, action_type: str, amount: int = 1) -> None:
        status = self.status()
        if mode == "read":
            available = status["reads_remaining"]
        elif action_type == "ticket_create":
            available = min(status["writes_remaining"], status["ticket_creations_remaining"])
        else:
            available = status["writes_remaining"]
        if amount > available:
            message = f"Rate limit blocks {amount} {action_type} action(s). {available} remain in the current hour."
            self.audit.record("rate_limit_block", mode, request_summary=message)
            raise HTTPException(status_code=429, detail=message)

    def record(self, mode: str, action_type: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO rate_events(created_at, action_mode, action_type) VALUES (?, ?, ?)",
                (utc_now(), mode, action_type),
            )
        self.audit.record(action_type, mode)
