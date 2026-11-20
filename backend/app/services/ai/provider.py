"""LLM provider adapters (OpenAI-compatible chat completions, Anthropic messages, Google Gemini).

Keys are read from settings (`LLM_API_KEY` / `GEMINI_API_KEY`, `SecretStr`) and are only ever placed
in the request header; they are never logged, returned or included in error messages. Error
messages carry the provider name, an error kind and an HTTP status at most - never response bodies,
prompts or keys.

Retries: only transient failures (timeouts, network errors, HTTP 429 and 5xx) are retried, at most
`max_retries` times with capped exponential backoff and jitter (`Retry-After` honoured up to the cap).
Authentication failures, invalid requests, blocked or malformed responses fail immediately.
"""

from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import Settings

_DEFAULT_BASE_URLS = {
    "openai_compatible": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_BACKOFF_BASE_SECONDS = 0.5
_BACKOFF_CAP_SECONDS = 4.0
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$")

# Error kinds (stable values recorded in the AI audit and reported by `/ai/status`).
TIMEOUT, NETWORK, RATE_LIMITED, SERVER_ERROR = "timeout", "network", "rate_limited", "server_error"
AUTH, BAD_REQUEST, INVALID_RESPONSE, BLOCKED, TRUNCATED, QUOTA_EXHAUSTED = (
    "auth", "bad_request", "invalid_response", "blocked", "truncated", "quota_exhausted")
GEMINI_MIN_OUTPUT_TOKENS = 1024  # thinking tokens count against maxOutputTokens
RETRYABLE_KINDS = frozenset({TIMEOUT, NETWORK, RATE_LIMITED, SERVER_ERROR})

_sleep = time.sleep  # patched in tests


class LLMProviderError(RuntimeError):
    """The provider call failed (network, timeout, HTTP error, blocked or malformed response)."""

    def __init__(self, message: str, *, kind: str = INVALID_RESPONSE, status_code: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE_KINDS


@dataclass(frozen=True)
class LLMCompletion:
    text: str
    provider: str
    model: str
    attempts: int = 1


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(self, *, system: str, user: str, max_tokens: int) -> LLMCompletion: ...


def _status_kind(status: int) -> str:
    if status in (401, 403):
        return AUTH
    if status == 429:
        return RATE_LIMITED
    if status >= 500:
        return SERVER_ERROR
    return BAD_REQUEST


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return max(0.0, float(resp.headers.get("retry-after", "")))
    except ValueError:
        return None


class _HttpProvider:
    name = "base"

    def __init__(
        self, *, api_key: str, model: str, base_url: str, timeout: float, max_retries: int = 0,
        total_timeout: float | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max(0, max_retries)
        self._total_timeout = total_timeout if total_timeout is not None else timeout * (1 + self._max_retries) + 10
        self._local = threading.local()  # attempts of the current thread's call (audit only)

    def _classify(self, resp: httpx.Response) -> str:
        return _status_kind(resp.status_code)

    def _post_once(self, path: str, headers: dict[str, str], payload: dict) -> dict:
        try:
            resp = httpx.post(
                f"{self._base_url}{path}", headers=headers, json=payload, timeout=self._timeout
            )
        except httpx.TimeoutException:
            raise LLMProviderError(f"{self.name} request timed out", kind=TIMEOUT) from None
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"{self.name} request failed: {type(exc).__name__}", kind=NETWORK) from None
        if resp.status_code != 200:
            err = LLMProviderError(f"{self.name} returned HTTP {resp.status_code}",
                                   kind=self._classify(resp), status_code=resp.status_code)
            err.retry_after = _retry_after(resp)  # type: ignore[attr-defined]
            raise err
        try:
            body = resp.json()
        except ValueError:
            raise LLMProviderError(f"{self.name} returned a non-JSON body", kind=INVALID_RESPONSE) from None
        if not isinstance(body, dict):
            raise LLMProviderError(f"{self.name} returned an unexpected body", kind=INVALID_RESPONSE)
        return body

    def _post(self, path: str, headers: dict[str, str], payload: dict) -> dict:
        """Bounded: at most `1 + max_retries` attempts and never past `total_timeout` overall."""
        attempt, start = 0, time.monotonic()
        while True:
            attempt += 1
            self._local.attempts = attempt
            try:
                return self._post_once(path, headers, payload)
            except LLMProviderError as exc:
                if not exc.retryable or attempt > self._max_retries:
                    raise
                delay = min(_BACKOFF_CAP_SECONDS,
                            _BACKOFF_BASE_SECONDS * 2 ** (attempt - 1) * (0.8 + 0.4 * random.random()))
                hinted = getattr(exc, "retry_after", None)
                if hinted is not None:
                    delay = min(_BACKOFF_CAP_SECONDS, max(delay, hinted))
                if time.monotonic() - start + delay + self._timeout > self._total_timeout:
                    raise
                _sleep(delay)

    def _completion(self, text: str, model: Any) -> LLMCompletion:
        return LLMCompletion(text=text, provider=self.name, model=str(model or self.model), attempts=getattr(self._local, "attempts", 1))


class OpenAICompatibleProvider(_HttpProvider):
    name = "openai_compatible"

    def complete(self, *, system: str, user: str, max_tokens: int, json_mode: bool = False) -> LLMCompletion:
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
        return self._completion(text, body.get("model"))


class AnthropicProvider(_HttpProvider):
    name = "anthropic"

    def complete(self, *, system: str, user: str, max_tokens: int, json_mode: bool = False) -> LLMCompletion:
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
        return self._completion(text, body.get("model"))


_GEMINI_OK_FINISH = frozenset({None, "", "STOP", "FINISH_REASON_UNSPECIFIED"})


class GeminiProvider(_HttpProvider):
    """Google Gemini API `models/{model}:generateContent` (REST, `x-goog-api-key` header).

    System instructions travel in `systemInstruction`, separate from the user content. Blocked
    prompts/candidates, truncated output (`MAX_TOKENS`) and empty text are errors, so the caller
    falls back instead of showing a partial answer. Thought parts are never returned.
    """

    name = "gemini"

    def __init__(self, *, thinking_level: str | None = None, **kw: Any) -> None:
        super().__init__(**kw)
        self._thinking_level = thinking_level.upper() if thinking_level else None

    def _classify(self, resp: httpx.Response) -> str:
        # An invalid key answers 400 INVALID_ARGUMENT with reason API_KEY_INVALID.
        if resp.status_code == 400:
            try:
                details = (resp.json().get("error") or {}).get("details") or []
                if any(isinstance(d, dict) and d.get("reason") == "API_KEY_INVALID" for d in details):
                    return AUTH
            except (ValueError, AttributeError):
                pass
        # A daily quota does not recover within the retry budget: fail fast instead of retrying.
        if resp.status_code == 429 and "PerDay" in resp.text:
            return QUOTA_EXHAUSTED
        return super()._classify(resp)

    def complete(self, *, system: str, user: str, max_tokens: int, json_mode: bool = False) -> LLMCompletion:
        config: dict[str, Any] = {"temperature": 0, "maxOutputTokens": max(max_tokens, GEMINI_MIN_OUTPUT_TOKENS),
                                  "candidateCount": 1}
        if json_mode:
            config["responseMimeType"] = "application/json"
        if self._thinking_level:
            config["thinkingConfig"] = {"thinkingLevel": self._thinking_level}
        body = self._post(
            f"/models/{self.model}:generateContent",
            {"x-goog-api-key": self._api_key},
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": config,
            },
        )
        feedback = body.get("promptFeedback")
        if isinstance(feedback, dict) and feedback.get("blockReason"):
            raise LLMProviderError("gemini blocked the prompt", kind=BLOCKED)
        candidates = body.get("candidates")
        if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
            raise LLMProviderError("gemini response has no candidates")
        cand = candidates[0]
        finish = cand.get("finishReason")
        if finish == "MAX_TOKENS":
            raise LLMProviderError("gemini output was truncated", kind=TRUNCATED)
        if finish not in _GEMINI_OK_FINISH:
            raise LLMProviderError("gemini stopped the candidate", kind=BLOCKED)
        parts = (cand.get("content") or {}).get("parts") if isinstance(cand.get("content"), dict) else None
        if not isinstance(parts, list):
            raise LLMProviderError("gemini response has no content parts")
        text = "".join(
            p["text"] for p in parts
            if isinstance(p, dict) and isinstance(p.get("text"), str) and not p.get("thought")
        )
        if not text.strip():
            raise LLMProviderError("gemini response has no text")
        return self._completion(text, body.get("modelVersion"))


def build_provider(cfg: Settings) -> tuple[LLMProvider | None, str]:
    """Return `(provider, status)`; `provider` is None unless enabled and fully configured.

    The provider is exactly the configured `LLM_PROVIDER`; there is no silent switching.
    """
    if not cfg.llm_enabled:
        return None, "disabled"
    if cfg.llm_provider == "gemini":
        key = cfg.gemini_api_key.get_secret_value() if cfg.gemini_api_key is not None else ""
        if not key.strip():
            return None, "misconfigured: GEMINI_API_KEY is not set"
        model, source = (cfg.llm_model, "LLM_MODEL") if cfg.llm_model else (cfg.gemini_model, "GEMINI_MODEL")
        if not model or not _MODEL_ID_RE.match(model):
            return None, f"misconfigured: {source} is not a valid model id"
        return (
            GeminiProvider(
                api_key=key.strip(), model=model, base_url=cfg.gemini_base_url,
                timeout=cfg.llm_timeout_seconds, max_retries=cfg.llm_max_retries,
                total_timeout=cfg.llm_total_timeout_seconds, thinking_level=cfg.gemini_thinking_level,
            ),
            "enabled",
        )
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
            max_retries=cfg.llm_max_retries,
            total_timeout=cfg.llm_total_timeout_seconds,
        ),
        "enabled",
    )
