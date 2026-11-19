"""LLM provider adapters (OpenAI-compatible chat completions, Anthropic messages).

Keys are read from settings (`LLM_API_KEY`, a `SecretStr`) and are only ever placed in the
request header; they are never logged, returned or included in error messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import Settings

_DEFAULT_BASE_URLS = {
    "openai_compatible": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}


class LLMProviderError(RuntimeError):
    """The provider call failed (network, timeout, HTTP error or malformed response)."""


@dataclass(frozen=True)
class LLMCompletion:
    text: str
    provider: str
    model: str


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(self, *, system: str, user: str, max_tokens: int) -> LLMCompletion: ...


class _HttpProvider:
    name = "base"

    def __init__(self, *, api_key: str, model: str, base_url: str, timeout: float) -> None:
        self._api_key = api_key
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _post(self, path: str, headers: dict[str, str], payload: dict) -> dict:
        try:
            resp = httpx.post(
                f"{self._base_url}{path}", headers=headers, json=payload, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"{self.name} request failed: {type(exc).__name__}") from None
        if resp.status_code != 200:
            raise LLMProviderError(f"{self.name} returned HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError:
            raise LLMProviderError(f"{self.name} returned a non-JSON body") from None


class OpenAICompatibleProvider(_HttpProvider):
    name = "openai_compatible"

    def complete(self, *, system: str, user: str, max_tokens: int) -> LLMCompletion:
        body = self._post(
            "/chat/completions",
            {"Authorization": f"Bearer {self._api_key}"},
            {
                "model": self.model,
                "temperature": 0,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMProviderError("openai_compatible response has no message content") from None
        if not isinstance(text, str):
            raise LLMProviderError("openai_compatible response content is not text")
        return LLMCompletion(text=text, provider=self.name, model=str(body.get("model") or self.model))


class AnthropicProvider(_HttpProvider):
    name = "anthropic"

    def complete(self, *, system: str, user: str, max_tokens: int) -> LLMCompletion:
        body = self._post(
            "/v1/messages",
            {"x-api-key": self._api_key, "anthropic-version": "2023-06-01"},
            {
                "model": self.model,
                "temperature": 0,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        try:
            text = "".join(b["text"] for b in body["content"] if b.get("type") == "text")
        except (KeyError, TypeError):
            raise LLMProviderError("anthropic response has no text content") from None
        return LLMCompletion(text=text, provider=self.name, model=str(body.get("model") or self.model))


def build_provider(cfg: Settings) -> tuple[LLMProvider | None, str]:
    """Return `(provider, status)`; `provider` is None unless enabled and fully configured."""
    if not cfg.llm_enabled:
        return None, "disabled"
    key = cfg.llm_api_key.get_secret_value() if cfg.llm_api_key is not None else ""
    if not key.strip():
        return None, "misconfigured: LLM_API_KEY is not set"
    if not cfg.llm_model:
        return None, "misconfigured: LLM_MODEL is not set"
    cls = AnthropicProvider if cfg.llm_provider == "anthropic" else OpenAICompatibleProvider
    return (
        cls(
            api_key=key,
            model=cfg.llm_model,
            base_url=cfg.llm_base_url or _DEFAULT_BASE_URLS[cfg.llm_provider],
            timeout=cfg.llm_timeout_seconds,
        ),
        "enabled",
    )
