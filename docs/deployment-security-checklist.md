# PulseReach — Hackathon Deployment Security Checklist

Scope: 10-day live hackathon demo of the MVP backend. **Not production-ready and not clinically
validated.** All patient data is synthetic.

## 1. Authentication — not implemented (known limitation)

- There is **no authentication or authorisation**. Any client that can reach the API can read every
  synthetic record and the AI audit, and can call every write endpoint.
- `recorded_by` / `reviewed_by` / `reviewer` are client-supplied strings. They are attribution, not
  authenticated identity, and must not be presented as such.

### Endpoints that mutate data

| Endpoint | Effect |
|---|---|
| `POST /api/v1/care-gaps/{gap_id}/follow-ups` | Appends follow-up events; can close a gap (`completion_documented`) |
| `POST /api/v1/care-gaps/{gap_id}/reviews` | Appends clinical-review decisions |
| `POST /api/v1/appointments`, `PATCH /api/v1/appointments/{id}` | Creates/changes appointments + history |
| `POST /api/v1/referrals`, `PATCH /api/v1/referrals/{id}` | Creates/changes referrals + history |
| `POST /api/v1/outreach/draft/review` | Records review audit; approval appends a simulated follow-up |
| `POST /api/v1/outreach/draft`, `POST /api/v1/explanations` | Append AI audit records (and may call the LLM provider when enabled, which costs money) |
| `GET /api/v1/insights/population` | Appends an AI audit record (and may call the provider) |

Read-only: all other `GET` endpoints, `POST /api/v1/evaluations` (stores nothing),
`POST /api/v1/outreach/preview` (stores nothing).

### Minimum protection before public judging (recommended, smallest option first)

1. **Platform-level access control, no code change (preferred):** deploy Cloud Run with
   `--no-allow-unauthenticated` and grant `roles/run.invoker` only to the judges' / team's Google
   accounts (or front it with IAP). The frontend then needs an identity token or IAP session.
2. **If the API must be publicly reachable for the frontend:** a single shared write key —
   a small middleware rejecting `POST`/`PATCH` without `X-PulseReach-Key` equal to a secret from
   Secret Manager (~15 lines; not implemented yet). Reads stay public (synthetic data only). This
   prevents anonymous vandalism of the demo data and LLM cost abuse; it is not user identity.
3. Keep `LLM_ENABLED=false` unless provider spend is capped at the provider.

Do not build a user/role system for the hackathon.

## 2. Data

- [x] Only synthetic data: every patient row has `is_synthetic = true` (DB `CHECK`), ids are
  `SYNTH-*`, Emirates ids `SYNTH-EID-*`; the explanation/outreach privacy guard rejects real-looking
  Emirates ids, phone numbers and e-mail addresses.
- [x] Official data is the public Abu Dhabi SDI facility register and SCAD aggregates only.
- [ ] Do not load any real patient data into the deployed database.

## 3. No outbound messages

- [x] No SMS/e-mail/push/telephony integration exists in the codebase. The only outbound HTTP call
  is the optional LLM provider (`app/services/ai/provider.py`), off by default.
- [x] Outreach is simulated: approval records `outcome_status = "simulated_not_sent"`; DB `CHECK`s
  reject `sent`/`delivered` statuses; responses carry `sendable: false`, `delivered: false`.
- [x] Consent and eligibility are checked before any provider call and re-checked at approval.
- [x] The LLM never decides eligibility, due dates or care gaps; outputs are validated, with a
  deterministic fallback. Provider prompts carry no patient identifiers or contact details.

## 4. Secrets

- [x] No secrets in code or images: `DATABASE_URL` and `LLM_API_KEY` are `SecretStr` from the
  environment; `.dockerignore` excludes `.env*` (except `.env.example`), `.venv`, tests and `.git`.
- [x] Errors never return SQL, parameters or tracebacks; the API key is never logged or returned
  (`/ai/status` reports configuration only). The AI audit stores SHA-256 fingerprints, not texts.
- [ ] In GCP, put `DATABASE_URL` and `LLM_API_KEY` in Secret Manager (`--set-secrets`), never in
  `--set-env-vars`, and use a strong generated database password.

## 5. CORS, rate limiting, database access

- **CORS:** `CORS_ORIGINS` defaults to `http://localhost:3000`; set it to the deployed frontend
  origin(s) only. Never `*` (credentials are allowed).
- **Rate limiting:** none in the app. Use Cloud Run `--max-instances` (cost ceiling) and
  `--concurrency`, and Cloud Armor or the API gateway if the URL is public. LLM-backed endpoints are
  the main cost risk.
- **Database:** use Cloud SQL with no public IP (Cloud SQL connector / private IP), a dedicated
  user, automated backups on. The Compose file publishes PostgreSQL on host port 5432 — for local
  use only; do not expose it on a shared host.
- **Migrations:** run `python -m app.db.init --seed` as a one-off job (idempotent; never reseeds a
  seeded DB). Destructive downgrades are refused unless `-x allow_data_loss=true`.
- **Reseed** (`python -m app.services.synthetic_generator.seed`) deletes all follow-up, workflow
  and AI audit history of the run — never run it against the live demo by accident.

## 6. Claims

- Do not claim production readiness, clinical validation, or clinically reviewed rules
  (`clinical_review_status = not_reviewed`).
- Do not present programme eligibility or rule-level review flags as individual clinical need.
