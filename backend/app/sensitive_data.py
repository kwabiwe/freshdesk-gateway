from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SecretFinding:
    kind: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.I)),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.I)),
    ("password_assignment", re.compile(r"\b(?:password|passwd|pwd)\s*[:=]\s*[^\s,;]{4,}", re.I)),
    ("api_key_assignment", re.compile(r"\b(?:api[_ -]?key|secret|token)\s*[:=]\s*[A-Za-z0-9._~+/=-]{12,}", re.I)),
    ("oauth_token", re.compile(r"\b(?:ya29\.[A-Za-z0-9_-]+|xox[baprs]-[A-Za-z0-9-]{10,})\b")),
    ("connection_string_password", re.compile(r"://[^/\s:@]+:[^/\s@]+@", re.I)),
    ("recovery_code", re.compile(r"\b(?:recovery|backup)\s+code\s*[:=]\s*[A-Za-z0-9-]{6,}", re.I)),
    ("long_random_token", re.compile(r"\b(?=[A-Za-z0-9_-]{32,}\b)(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_-]+\b")),
)


def detect_secrets(text: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for kind, pattern in PATTERNS:
        if pattern.search(text or ""):
            findings.append(
                SecretFinding(
                    kind=kind,
                    message=f"Potential {kind.replace('_', ' ')} detected. Remove or redact it before creating the ticket.",
                )
            )
    return findings


def redact_text(text: str, max_length: int = 240) -> str:
    cleaned = text or ""
    for _, pattern in PATTERNS:
        cleaned = pattern.sub("[REDACTED]", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_length]
