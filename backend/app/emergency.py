from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from .audit import AuditLog


class EmergencyStop:
    def __init__(self, stop_file: Path, audit: AuditLog):
        self.stop_file = stop_file
        self.audit = audit

    def is_active(self) -> bool:
        return self.stop_file.exists()

    def status(self) -> dict[str, object]:
        return {"active": self.is_active(), "stop_file": str(self.stop_file)}

    def require_clear(self) -> None:
        if self.is_active():
            self.audit.record("emergency_stop_block", "local", error="Freshdesk access blocked by emergency stop")
            raise HTTPException(status_code=423, detail="Emergency stop is active. Freshdesk access is blocked.")

    def activate(self, confirmation: str) -> dict[str, object]:
        if confirmation != "STOP":
            raise HTTPException(status_code=400, detail='Type "STOP" to confirm.')
        self.stop_file.parent.mkdir(parents=True, exist_ok=True)
        self.stop_file.write_text("Freshdesk Gateway emergency stop active\n", encoding="utf-8")
        self.audit.record("emergency_stop_activated", "local")
        return self.status()

    def resume(self, confirmation: str) -> dict[str, object]:
        if confirmation != "RESUME":
            raise HTTPException(status_code=400, detail='Type "RESUME" to confirm.')
        self.stop_file.unlink(missing_ok=True)
        self.audit.record("emergency_stop_resumed", "local")
        return self.status()
