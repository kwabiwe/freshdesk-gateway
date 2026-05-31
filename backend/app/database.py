from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    action_type TEXT NOT NULL,
    action_mode TEXT NOT NULL,
    draft_id TEXT,
    ticket_id TEXT,
    ticket_subject TEXT,
    request_summary TEXT,
    validation_result TEXT,
    approval_result TEXT,
    api_result TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS rate_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    action_mode TEXT NOT NULL,
    action_type TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rate_events_created_at ON rate_events(created_at);
CREATE TABLE IF NOT EXISTS schema_cache (
    cache_key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT
);
CREATE TABLE IF NOT EXISTS drafts (
    draft_id TEXT PRIMARY KEY,
    batch_id TEXT,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    source_input TEXT,
    generated_output TEXT,
    validation_status TEXT NOT NULL,
    validation_result TEXT NOT NULL,
    approval_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ticket_id TEXT,
    api_result TEXT
);
CREATE INDEX IF NOT EXISTS idx_drafts_batch_id ON drafts(batch_id);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get_overrides(self) -> dict[str, str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def set_overrides(self, values: dict[str, object]) -> None:
        with self.connect() as conn:
            for key, value in values.items():
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, str(value)),
                )
