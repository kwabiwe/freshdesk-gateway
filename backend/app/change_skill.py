from __future__ import annotations

from pathlib import Path
from typing import Any


class ChangeSkill:
    VERSION = "1.0.0"
    SUMMARY = "Full operational Freshdesk change document from sparse technical notes and pasted evidence."
    SECTIONS = [
        "Title",
        "Planned change date",
        "Customer / environment",
        "Configuration items",
        "Background",
        "Change description",
        "Implementation steps",
        "Rollback plan",
        "Verification plan",
        "Risk and impact",
        "Expected outcome",
        "Success criteria",
        "Dependencies",
        "Assumptions requiring review",
    ]

    def __init__(self, root: Path | None = None):
        self.root = root or Path(__file__).resolve().parents[2] / "change_skill"

    def instructions(self) -> str:
        return (self.root / "SKILL.md").read_text(encoding="utf-8")

    def template(self) -> str:
        return (self.root / "TEMPLATE.md").read_text(encoding="utf-8")

    def overview(self) -> dict[str, Any]:
        return {
            "version": self.VERSION,
            "summary": self.SUMMARY,
            "sections": self.SECTIONS,
            "instructions": self.instructions(),
            "template": self.template(),
        }
