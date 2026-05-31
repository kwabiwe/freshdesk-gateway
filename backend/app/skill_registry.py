from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SKILL_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class LocalSkill:
    skill_id: str
    name: str
    version: str
    summary: str
    sections: list[str]
    root: Path
    instruction_file: str = "SKILL.md"
    template_file: str = "TEMPLATE.md"

    def _read(self, filename: str) -> str:
        root = self.root.resolve()
        path = (root / filename).resolve()
        if path.parent != root:
            raise ValueError(f"Skill file must remain inside {root}.")
        return path.read_text(encoding="utf-8")

    def instructions(self) -> str:
        return self._read(self.instruction_file)

    def template(self) -> str:
        return self._read(self.template_file)

    def overview(self, *, include_content: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.skill_id,
            "name": self.name,
            "version": self.version,
            "summary": self.summary,
            "sections": self.sections,
        }
        if include_content:
            result["instructions"] = self.instructions()
            result["template"] = self.template()
        return result


class SkillRegistry:
    """Discover versioned local instruction folders without binding workflows to one global skill."""

    def __init__(self, root: Path | None = None):
        self.root = root or Path(__file__).resolve().parents[2] / "skills"

    def _load(self, manifest_path: Path) -> LocalSkill:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        skill_id = str(data.get("id", ""))
        if not SKILL_ID.fullmatch(skill_id) or manifest_path.parent.name != skill_id:
            raise ValueError(f"Invalid local skill id in {manifest_path}.")
        return LocalSkill(
            skill_id=skill_id,
            name=str(data["name"]),
            version=str(data["version"]),
            summary=str(data["summary"]),
            sections=[str(section) for section in data.get("sections", [])],
            root=manifest_path.parent,
            instruction_file=str(data.get("instruction_file", "SKILL.md")),
            template_file=str(data.get("template_file", "TEMPLATE.md")),
        )

    def list(self) -> list[dict[str, Any]]:
        return [self._load(path).overview(include_content=False) for path in sorted(self.root.glob("*/skill.json"))]

    def get(self, skill_id: str) -> LocalSkill:
        if not SKILL_ID.fullmatch(skill_id):
            raise ValueError("Invalid local skill id.")
        manifest = self.root / skill_id / "skill.json"
        if not manifest.is_file():
            raise ValueError(f"Local skill not found: {skill_id}")
        return self._load(manifest)
