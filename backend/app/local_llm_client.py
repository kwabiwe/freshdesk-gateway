from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from .audit import AuditLog
from .config import Settings
from .sensitive_data import detect_secrets, redact_text


class LocalLLMClient:
    PROVIDERS = {"auto", "ollama", "openai-compatible"}

    def __init__(self, settings_provider, audit: AuditLog, transport: httpx.BaseTransport | None = None):
        self.settings_provider = settings_provider
        self.audit = audit
        self.transport = transport
        self._detected: tuple[str, str, str] | None = None

    @staticmethod
    def _base_url(settings: Settings) -> str:
        url = settings.ollama_url.rstrip("/")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise HTTPException(status_code=422, detail="Local model URL must use localhost or a loopback address.")
        return url

    @staticmethod
    def _openai_base(url: str) -> str:
        return url if url.endswith("/v1") else f"{url}/v1"

    def _discover(self) -> dict[str, Any]:
        settings: Settings = self.settings_provider()
        base_url = self._base_url(settings)
        provider = settings.local_llm_provider
        if provider not in self.PROVIDERS:
            raise HTTPException(status_code=422, detail="Local model provider must be auto, ollama, or openai-compatible.")

        errors: list[str] = []
        with httpx.Client(timeout=5.0, transport=self.transport) as client:
            if provider in {"auto", "ollama"}:
                try:
                    response = client.get(f"{base_url}/api/tags")
                    response.raise_for_status()
                    models = [item.get("name") for item in response.json().get("models", []) if item.get("name")]
                    self._detected = (base_url, provider, "ollama")
                    return {"connected": True, "provider": "ollama", "models": models}
                except httpx.HTTPError as exc:
                    errors.append(str(exc))
                    if provider == "ollama":
                        raise
            if provider in {"auto", "openai-compatible"}:
                try:
                    response = client.get(f"{self._openai_base(base_url)}/models")
                    response.raise_for_status()
                    models = [item.get("id") for item in response.json().get("data", []) if item.get("id")]
                    self._detected = (base_url, provider, "openai-compatible")
                    return {"connected": True, "provider": "openai-compatible", "models": models}
                except httpx.HTTPError as exc:
                    errors.append(str(exc))
                    raise
        raise httpx.ConnectError("; ".join(errors))

    def test_connection(self) -> dict[str, Any]:
        settings: Settings = self.settings_provider()
        try:
            result = self._discover()
            return {
                "connected": True,
                "provider": result["provider"],
                "model": settings.ollama_model,
                "available_models": result["models"],
            }
        except (HTTPException, httpx.HTTPError) as exc:
            self.audit.record("local_llm_connection_error", "local", error=str(exc))
            return {"connected": False, "model": settings.ollama_model, "error": redact_text(str(exc), 240)}

    def list_models(self) -> dict[str, Any]:
        result = self.test_connection()
        return {
            "connected": result["connected"],
            "provider": result.get("provider"),
            "selected_model": result.get("model"),
            "models": result.get("available_models", []),
            "error": result.get("error"),
        }

    def _provider(self, base_url: str) -> str:
        configured = self.settings_provider().local_llm_provider
        if self._detected and self._detected[:2] == (base_url, configured):
            return self._detected[2]
        return self._discover()["provider"]

    def generate(self, prompt: str, source_text: str, *, max_tokens: int = 900, json_output: bool = False) -> str:
        findings = detect_secrets(source_text)
        if findings:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Potential secret detected. Redact it before using the local model.",
                    "findings": [finding.to_dict() for finding in findings],
                },
            )
        settings: Settings = self.settings_provider()
        base_url = self._base_url(settings)
        try:
            provider = self._provider(base_url)
            timeout = httpx.Timeout(
                connect=5.0,
                read=float(settings.ollama_generation_timeout_seconds),
                write=15.0,
                pool=5.0,
            )
            with httpx.Client(timeout=timeout, transport=self.transport) as client:
                if provider == "ollama":
                    payload: dict[str, Any] = {
                        "model": settings.ollama_model,
                        "prompt": prompt,
                        "stream": False,
                        "keep_alive": "15m",
                        "options": {"num_predict": max_tokens, "temperature": 0.2},
                    }
                    if json_output:
                        payload["format"] = "json"
                    response = client.post(f"{base_url}/api/generate", json=payload)
                    response.raise_for_status()
                    return response.json().get("response", "").strip()

                payload = {
                    "model": settings.ollama_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": max_tokens,
                    "stream": False,
                }
                if json_output:
                    payload["response_format"] = {"type": "json_object"}
                response = client.post(f"{self._openai_base(base_url)}/chat/completions", json=payload)
                if json_output and response.status_code in {400, 422}:
                    payload.pop("response_format", None)
                    response = client.post(f"{self._openai_base(base_url)}/chat/completions", json=payload)
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"].strip()
        except httpx.TimeoutException as exc:
            detail = (
                f"Local model generation exceeded {settings.ollama_generation_timeout_seconds} seconds. "
                "The model may still be loading or generating. Try again, choose a smaller model, "
                "or increase the local generation timeout in Settings."
            )
            self.audit.record("local_llm_generate_timeout", "local", error=detail)
            raise HTTPException(status_code=504, detail=detail) from exc
        except (KeyError, IndexError, TypeError, httpx.HTTPError) as exc:
            self.audit.record("local_llm_generate_error", "local", error=str(exc))
            raise HTTPException(
                status_code=503,
                detail="The local model server is unavailable. You can continue with a manual draft.",
            ) from exc

    @staticmethod
    def _parse_json_object(response: str) -> dict[str, Any]:
        start, end = response.index("{"), response.rindex("}") + 1
        parsed = json.loads(response[start:end])
        if not isinstance(parsed, dict):
            raise ValueError("Expected an object")
        return parsed

    def generate_json(self, prompt: str, source_text: str, *, max_tokens: int = 1400) -> dict[str, Any]:
        response = self.generate(prompt, source_text, max_tokens=max_tokens, json_output=True)
        try:
            return self._parse_json_object(response)
        except (ValueError, json.JSONDecodeError) as exc:
            self.audit.record("local_llm_invalid_json", "local", error=str(exc))
            repair_prompt = (
                "Repair the malformed local-model response below into one valid JSON object. "
                "Preserve the supplied values. Return JSON only, with no markdown fences or explanation.\n\n"
                f"MALFORMED RESPONSE:\n{response[:12000]}"
            )
            repaired = self.generate(repair_prompt, source_text, max_tokens=max_tokens, json_output=True)
            try:
                return self._parse_json_object(repaired)
            except (ValueError, json.JSONDecodeError) as repair_exc:
                self.audit.record("local_llm_json_repair_failed", "local", error=str(repair_exc))
                raise HTTPException(
                    status_code=502,
                    detail="The local model returned an invalid structured draft. Try again or edit manually.",
                ) from repair_exc

    def rewrite(self, text: str) -> str:
        prompt = (
            "Rewrite the ticket notes below into a concise, professional Freshdesk ticket description. "
            "Preserve facts exactly. Do not invent details. Do not mention AI, automation, or this instruction.\n\n"
            f"NOTES:\n{text}"
        )
        return self.generate(prompt, text, max_tokens=900)

    def structure_change(self, text: str) -> str:
        prompt = (
            "Structure the notes below as a Freshdesk change-request-style ticket description. "
            "Use exactly these headings: Reason for change, Scope, Technical plan, Implementation steps, "
            "Risk, Impact, Rollback plan, Validation plan, Proposed date/time, Affected users/sites/services, "
            "Communications required, Dependencies, Notes. Preserve facts. Make conservative assumptions only "
            "where the notes support them. If a section is unknown, write 'Not provided'. Do not mention AI, "
            f"automation, or this instruction.\n\nNOTES:\n{text}"
        )
        return self.generate(prompt, text, max_tokens=1400)

    def summarise(self, text: str) -> str:
        prompt = (
            "Summarise this Freshdesk ticket locally in at most five bullets. Preserve facts and highlight "
            f"open actions. Do not mention AI or automation.\n\nTICKET:\n{text}"
        )
        return self.generate(prompt, text, max_tokens=600)
