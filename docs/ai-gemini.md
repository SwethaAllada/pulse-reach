# PulseReach — AI assistance with the native Google Gemini provider

Code: `backend/app/services/ai/provider.py` (`GeminiProvider`, `build_provider`),
`backend/app/services/ai/service.py` (`AIService`), configuration in `backend/app/core/config.py`.
Deployment: `docs/deployment-gcp.md` §3a. Security status: `docs/deployment-security-checklist.md` §7.

AI is **off by default**. It is used only when `LLM_ENABLED=true` and `LLM_PROVIDER=gemini` are
both set explicitly; there is no automatic or silent switching between providers. When AI is
disabled, misconfigured, failing or its output is rejected, every feature returns the
deterministic template — AI never breaks or blocks a core feature.

## 1. Architecture

```
Google AI Studio API key
  -> Secret Manager secret `pulsereach-gemini-api-key`          (Cloud Run)  | untracked backend/.env (local)
  -> backend env var GEMINI_API_KEY (`--set-secrets=GEMINI_API_KEY=pulsereach-gemini-api-key:latest`)
  -> Settings.gemini_api_key (SecretStr)
  -> GeminiProvider: POST {GEMINI_BASE_URL}/models/{model}:generateContent, header x-goog-api-key
  -> AIService: guardrail validation, deterministic fallback, AI audit record
```

- The key lives only in the backend process. It is sent only in the `x-goog-api-key` header
  (never in the URL), and is never logged, returned, stored in the audit or included in errors.
- The frontend never calls Gemini and never receives the key or any AI setting; nothing AI-related
  belongs in `NEXT_PUBLIC_*`, Docker images, build args or committed files. `.env` and
  `backend/.env` are git-ignored; only the `.env.example` files (empty key) are tracked.
- No service-account keys or JSON downloads: on Cloud Run the runtime service account reads the
  secret (`roles/secretmanager.secretAccessor` on that secret only).
- System instructions travel in `systemInstruction`, separate from the user content; requests use
  `temperature: 0` and `candidateCount: 1`. Thought parts are discarded.

Other providers (`openai_compatible`, `anthropic`) remain available and use `LLM_API_KEY`,
`LLM_BASE_URL` and `LLM_MODEL`; `GEMINI_API_KEY` is used only by `LLM_PROVIDER=gemini`.

## 2. Configuration

| Variable | Default | Notes |
|---|---|---|
| `LLM_ENABLED` | `false` | must be `true` to call any provider |
| `LLM_PROVIDER` | `openai_compatible` | set `gemini` for the native provider |
| `GEMINI_API_KEY` | unset | **secret**; Secret Manager on Cloud Run, `backend/.env` locally. Unset/blank → `misconfigured` |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | model id (`[A-Za-z0-9][A-Za-z0-9._-]*`, no `models/` prefix); invalid → `misconfigured` |
| `LLM_MODEL` | unset | if set, **overrides** `GEMINI_MODEL` — leave unset for Gemini |
| `GEMINI_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta` | change only for testing |
| `GEMINI_THINKING_LEVEL` | `""` (model default) | `minimal` \| `low` \| `medium` \| `high` → `thinkingConfig.thinkingLevel`; the model must support it, else HTTP 400 → `bad_request` |
| `LLM_MAX_OUTPUT_TOKENS` | `400` (64–8192) | **use `1024` for Gemini**: thinking tokens count against it; `MAX_TOKENS` → `truncated` → fallback |
| `LLM_TIMEOUT_SECONDS` | `20` (≤ 120) | per attempt |
| `LLM_MAX_RETRIES` | `2` (0–5) | transient failures only |
| `LLM_TOTAL_TIMEOUT_SECONDS` | `45` (≤ 300) | all attempts plus backoff; keep below the Cloud Run request timeout (60 s) |
| `LLM_BASE_URL`, `LLM_API_KEY` | unset | not used by `gemini` |

Configuration is read once per process (`get_ai_service` is cached); restart the backend / roll a
new Cloud Run revision after changing it.

## 3. Retries, timeouts and fallback

- At most `1 + LLM_MAX_RETRIES` attempts, each bounded by `LLM_TIMEOUT_SECONDS`.
- Retried: timeouts, network errors, HTTP 429 and 500/502/503/504. Backoff is exponential
  (0.5 s, 1 s, 2 s …, capped at 4 s) with ±20 % jitter; `Retry-After` is honoured up to the cap.
- A retry is skipped when it could not finish within `LLM_TOTAL_TIMEOUT_SECONDS` (elapsed + delay +
  one more attempt); the last error is then returned.
- Not retried (fail immediately): authentication, other 4xx, blocked prompts/candidates,
  truncated output, malformed or empty responses.
- Any failure → the caller gets the deterministic template with `fallback_reason=provider_error`;
  a generated text that fails the guardrails → `fallback_reason=output_rejected`.
  Other fallback reasons: `llm_disabled`, `llm_misconfigured`, `blocked:<gate reason>` (outreach
  gate refused before any provider call).

## 4. Error kinds

Stable values recorded in the AI audit (`extra.provider_error_kind`) and reported by `/ai/status`
(`last_provider_error`). They never contain provider response text, prompts or keys.

| Kind | Cause | Retried |
|---|---|---|
| `timeout` | attempt exceeded `LLM_TIMEOUT_SECONDS` | yes |
| `network` | connection/DNS/TLS error | yes |
| `rate_limited` | HTTP 429 (quota or rate limit) | yes |
| `server_error` | HTTP 5xx | yes |
| `auth` | HTTP 401/403, or 400 with reason `API_KEY_INVALID` (wrong, revoked or restricted key) | no |
| `bad_request` | other 4xx (unknown model, unsupported thinking level, …) | no |
| `blocked` | `promptFeedback.blockReason`, or a non-`STOP` finish reason (e.g. `SAFETY`) | no |
| `truncated` | finish reason `MAX_TOKENS` — raise `LLM_MAX_OUTPUT_TOKENS` | no |
| `invalid_response` | non-JSON body, no candidates/parts, empty text | no |
| `adapter_error` | unexpected exception in the adapter (logged with a stack trace, no secrets) | no |

## 5. Status and audit endpoints

- `GET /api/v1/ai/status` (permission `platform.status`): configuration plus the outcome of the
  most recent provider call; it makes **no** provider call. Fields: `llm_enabled`, `status`
  (`enabled`, `disabled` or `misconfigured: <reason>`), `availability`, `configured_provider`,
  `provider`, `model`, `last_provider_call_at`, `last_provider_outcome`, `last_provider_error`,
  `prompt_versions`. `availability`:
  - `disabled` — `LLM_ENABLED=false`;
  - `misconfigured` — enabled but key or model missing/invalid (deterministic templates in use);
  - `configured_unverified` — configured, no provider call recorded yet;
  - `last_call_succeeded` — the last call returned text (even if the guardrails then rejected it);
  - `last_call_failed` — the last call failed; see `last_provider_error`.
- `GET /api/v1/ai/audit?feature=…&limit=…` (permission `audit_logs.read`, organization-scoped):
  per-generation records with provider, model, generation mode, fallback reason, guardrail
  violations, latency, SHA-256 fingerprints of input/output (not the texts) and diagnostics
  (`provider_error_kind`, `provider_attempts` when > 1). `durable=true` in `DATA_SOURCE=db`.

## 6. Safety boundaries

- The AI only **restates deterministic results**. Eligibility, status, due dates, care gaps,
  reasons and rule citations are decided by the rules engine; the model never changes them.
- Only de-identified facts are sent: no names, Emirates ids, contact details or free-text notes
  (`provider_facts()`, portal facts for the patient assistant). Patient data is synthetic.
- Every output is validated (`guardrails.py`: no identifiers, links, clinical or risk claims,
  eligibility/due/overdue/approval/completion claims beyond the facts, invented numbers or dates,
  wrong language or format); a violation discards the output and returns the template.
- Outreach stays a **simulated draft**: consent, channel, language and next-step checks run before
  any provider call (`outreach/drafting.py`); a human must review it (`/outreach/draft/review`);
  approval records `simulated_not_sent`. There is **no automatic sending** — no SMS, e-mail,
  push or telephony integration exists.
- Wording changes in a prompt template require bumping its version in `prompts.py`.

## 7. Operating it

- Enable: `LLM_ENABLED=true`, `LLM_PROVIDER=gemini`, `GEMINI_API_KEY` (secret),
  `LLM_MAX_OUTPUT_TOKENS=1024`; optionally `GEMINI_MODEL`, `GEMINI_THINKING_LEVEL=low`.
- Disable: `LLM_ENABLED=false` (Cloud Run: `--update-env-vars=LLM_ENABLED=false`). Takes effect
  for new processes/revisions; deterministic templates are used immediately after.
- Rotate / revoke / clean up: `docs/deployment-gcp.md` §3a steps 6–8 and §8.
- Local development: copy `backend/.env.example` to `backend/.env` (git-ignored; check with
  `git check-ignore -v backend/.env`) and put the key there. Never paste a key into a tracked
  file, a shell command line, a ticket or a chat.

## 8. Real smoke test (one small, non-sensitive request)

Run only with approval, with a real key, and never print the key. The request contains **no
patient data** — a fixed connectivity prompt only.

1. Put the settings in the untracked `backend/.env` (edit with an editor; do not `echo` the key):
   `LLM_ENABLED=true`, `LLM_PROVIDER=gemini`, `GEMINI_API_KEY=<key>`, `LLM_MAX_OUTPUT_TOKENS=1024`.
2. From `backend/`, one direct provider call (prints status, model, attempts and the first
   characters of the reply, or the error kind — never the key or a response body):

   ```bash
   .venv/bin/python - <<'PY'
   from app.core.config import Settings
   from app.services.ai.provider import LLMProviderError, build_provider
   provider, status = build_provider(Settings())
   print("status:", status)
   if provider is not None:
       try:
           c = provider.complete(system="Connectivity check. Reply with the single word OK.",
                                 user="ping", max_tokens=1024)
           print("provider:", c.provider, "model:", c.model, "attempts:", c.attempts,
                 "reply:", c.text.strip()[:20])
       except LLMProviderError as exc:
           print("error kind:", exc.kind, "http status:", exc.status_code)
   PY
   ```

   Expected: `status: enabled`, `provider: gemini`, a reply such as `OK`. `auth` → wrong or
   restricted key; `bad_request` → model id or thinking level; `truncated` → raise the budget.
3. Optional, through the API (synthetic aggregates only): start a disposable memory-mode backend
   (`DATA_SOURCE=memory DEMO_IDENTITY_SEED=true DEMO_IDENTITY_PASSWORD=<passphrase>`), sign in as
   `manager.a@demo.pulsereach.invalid`, then `GET /api/v1/ai/status` (`configured_unverified`),
   `GET /api/v1/insights/population` once, and `GET /api/v1/ai/status` again
   (`last_call_succeeded`, or `last_call_failed` with `last_provider_error`).
4. Afterwards remove the key from `backend/.env` (or set `LLM_ENABLED=false`) if it is not needed,
   and record the result (date, model, outcome — no key, no output text) in the checklist.
