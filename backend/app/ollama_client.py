"""Compatibility import for older integrations using the Ollama-specific module name."""

from .local_llm_client import LocalLLMClient

OllamaClient = LocalLLMClient

__all__ = ["OllamaClient"]
