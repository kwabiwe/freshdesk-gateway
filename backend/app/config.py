from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv


def _as_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


@dataclass(frozen=True)
class Settings:
    freshdesk_domain: str
    freshdesk_api_key: str
    ollama_url: str
    ollama_model: str
    local_llm_provider: str
    ollama_generation_timeout_seconds: int
    max_writes_per_hour: int
    max_reads_per_hour: int
    max_ticket_creations_per_hour: int
    my_name: str
    my_email: str
    app_host: str
    app_port: int
    draft_expiry_minutes: int
    database_path: Path
    stop_file: Path
    agent_api_token: str = ""
    change_drafting_skill: str = "change_management_drafting"

    @property
    def freshdesk_base_url(self) -> str:
        domain = self.freshdesk_domain.strip()
        if not domain:
            return ""
        if domain.startswith(("http://", "https://")):
            return domain.rstrip("/")
        if domain.endswith(".freshdesk.com"):
            return f"https://{domain}"
        return f"https://{domain}.freshdesk.com"

    @property
    def freshdesk_configured(self) -> bool:
        return bool(self.freshdesk_domain and self.freshdesk_api_key)

    def safe_dict(self) -> dict[str, object]:
        return {
            "freshdesk_domain": self.freshdesk_domain,
            "freshdesk_configured": self.freshdesk_configured,
            "local_llm_url": self.ollama_url,
            "local_llm_model": self.ollama_model,
            "local_llm_provider": self.local_llm_provider,
            "local_llm_generation_timeout_seconds": self.ollama_generation_timeout_seconds,
            "max_writes_per_hour": self.max_writes_per_hour,
            "max_reads_per_hour": self.max_reads_per_hour,
            "max_ticket_creations_per_hour": self.max_ticket_creations_per_hour,
            "my_name": self.my_name,
            "my_email": self.my_email,
            "app_host": self.app_host,
            "app_port": self.app_port,
            "draft_expiry_minutes": self.draft_expiry_minutes,
            "database_path": str(self.database_path),
            "stop_file": str(self.stop_file),
            "agent_api_auth_required": bool(self.agent_api_token),
            "change_drafting_skill": self.change_drafting_skill,
            "cloud_ai_enabled": False,
        }

    def with_overrides(self, overrides: dict[str, str]) -> "Settings":
        numeric = {
            "max_writes_per_hour",
            "max_reads_per_hour",
            "max_ticket_creations_per_hour",
            "draft_expiry_minutes",
            "ollama_generation_timeout_seconds",
        }
        aliases = {
            "local_llm_url": "ollama_url",
            "local_llm_model": "ollama_model",
            "local_llm_generation_timeout_seconds": "ollama_generation_timeout_seconds",
        }
        allowed = numeric | {"ollama_model", "ollama_url", "local_llm_provider"}
        updates: dict[str, object] = {}
        for key, value in overrides.items():
            key = aliases.get(key, key)
            if key not in allowed:
                continue
            updates[key] = int(value) if key in numeric else value
        return replace(self, **updates)


def load_settings(env_file: str | Path | None = None) -> Settings:
    root = Path(__file__).resolve().parents[2]
    load_dotenv(env_file or root / ".env", override=False)

    def project_path(name: str, default: str) -> Path:
        value = Path(os.getenv(name, default)).expanduser()
        return value if value.is_absolute() else (root / value).resolve()

    return Settings(
        freshdesk_domain=os.getenv("FRESHDESK_DOMAIN", "").strip(),
        freshdesk_api_key=os.getenv("FRESHDESK_API_KEY", "").strip(),
        ollama_url=os.getenv("LOCAL_LLM_URL", os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/"),
        ollama_model=os.getenv("LOCAL_LLM_MODEL", os.getenv("OLLAMA_MODEL", "llama3.1")).strip(),
        local_llm_provider=os.getenv("LOCAL_LLM_PROVIDER", "auto").strip().lower(),
        ollama_generation_timeout_seconds=_as_int(
            "LOCAL_LLM_GENERATION_TIMEOUT_SECONDS",
            _as_int("OLLAMA_GENERATION_TIMEOUT_SECONDS", 300),
        ),
        max_writes_per_hour=_as_int("MAX_WRITES_PER_HOUR", 5),
        max_reads_per_hour=_as_int("MAX_READS_PER_HOUR", 60),
        max_ticket_creations_per_hour=_as_int("MAX_TICKET_CREATIONS_PER_HOUR", 5),
        my_name=os.getenv("MY_NAME", "").strip(),
        my_email=os.getenv("MY_EMAIL", "").strip(),
        app_host=os.getenv("APP_HOST", "127.0.0.1").strip(),
        app_port=_as_int("APP_PORT", 8787),
        draft_expiry_minutes=_as_int("DRAFT_EXPIRY_MINUTES", 30),
        database_path=project_path("DATABASE_PATH", "./data/freshdesk_gateway.db"),
        stop_file=project_path("STOP_FILE", "./STOP"),
        agent_api_token=os.getenv("AGENT_API_TOKEN", "").strip(),
        change_drafting_skill=os.getenv("CHANGE_DRAFTING_SKILL", "change_management_drafting").strip(),
    )
