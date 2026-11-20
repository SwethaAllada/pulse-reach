# PulseReach — Hackathon Deployment Security Checklist

Scope: 10-day live hackathon demo of the MVP backend. **Not production-ready and not clinically
validated.** All patient data is synthetic.

## 1. Access control — shared write key (no user accounts)

- There are **no user accounts or OAuth**. Reads are public; state-changing requests need a shared
  demo access code in the `X-PulseReach-Write-Key` header, compared in constant time with
  `WRITE_API_KEY` (`app/core/write_auth.py`). Missing or wrong key → `401`
  (`error.code = "unauthorized"`), before the request body is processed.
- **Fails closed:** if `WRITE_API_KEY` is unset or empty, every protected request is refused with
  `503` and the API logs `Write protection: WRITE_API_KEY not set`. Only
  `ALLOW_UNPROTECTED_WRITES=true` (local development, tests) disables the check — never set it in
  a public deployment. Startup logs the mode (`enforced` / `DISABLED` / not set), never the key.
- The key is a shared demo code, not identity: `recorded_by` / `reviewed_by` / `reviewer` remain
  client-supplied attribution. Anyone holding the code can write.

### Protected (every non-GET `/api/v1` route except the three below)

| Endpoint | Effect |
|---|---|
| `POST /api/v1/care-gaps/{gap_id}/follow-ups` | Appends follow-up events; can close a gap (`completion_documented`) |
| `POST /api/v1/care-gaps/{gap_id}/reviews` | Appends clinical-review decisions |
| `POST /api/v1/appointments`, `PATCH /api/v1/appointments/{id}` | Creates/changes appointments + history |
| `POST /api/v1/referrals`, `PATCH /api/v1/referrals/{id}` | Creates/changes referrals + history |
| `POST /api/v1/outreach/draft` | Appends AI audit; may call the LLM provider when enabled |
| `POST /api/v1/outreach/draft/review` | Records the review; approval appends a simulated follow-up |

New non-GET routes are protected by default (router-level dependency); a test fails if a route is
neither protected nor explicitly exempt.

### Public

- All `GET` endpoints. Note: `GET /api/v1/insights/population` appends one AI-audit record.
- Read-oriented POSTs (verified in code): `POST /api/v1/evaluations` and
  `POST /api/v1/outreach/preview` store nothing; `POST /api/v1/explanations` changes no workflow
  state but appends one AI-audit record and calls the LLM only when `LLM_ENABLED=true`. Keep
  `LLM_ENABLED=false`, or cap provider spend, while these remain public.

### Configuration

```bash
# Create the shared demo access code in Secret Manager (never in --set-env-vars, the image,
# the repository or a NEXT_PUBLIC_* frontend variable)
openssl rand -hex 16 | gcloud secrets create pulsereach-write-key --replication-policy=automatic --data-file=-
gcloud secrets add-iam-policy-binding pulsereach-write-key \
  --member=serviceAccount:pulsereach-run@pulsereach-hackathon-2026.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
# Mount it into the API (the init job does not need it)
gcloud run deploy pulsereach-api ... \
  --set-secrets=DATABASE_URL=pulsereach-database-url:latest,WRITE_API_KEY=pulsereach-write-key:latest \
  --allow-unauthenticated
# Share the code with judges out of band; read it once with:
gcloud secrets versions access latest --secret=pulsereach-write-key
# Rotate: add a new version, redeploy (or deploy a new revision) to pick it up
openssl rand -hex 16 | gcloud secrets versions add pulsereach-write-key --data-file=-
```

- Frontend: ask the judge for the code, keep it only in `sessionStorage`, and send it as
  `X-PulseReach-Write-Key` on protected requests only. The CORS configuration already allows
  custom request headers.
- Local Compose: set `WRITE_API_KEY` in the (untracked) env file, or
  `ALLOW_UNPROTECTED_WRITES=true` for local-only use.

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
- **Database:** reach Cloud SQL only through the Cloud Run Cloud SQL connector (Unix socket
  `/cloudsql/<connection-name>`). The connector needs either a public IP with **no authorized
  networks** (simplest; only IAM-authorised connector traffic is accepted) or a private IP with VPC
  egress. Use a dedicated user, a generated URL-safe password and automated backups. The Compose file publishes PostgreSQL on host port 5432 — for local
  use only; do not expose it on a shared host.
- **Migrations:** run `python -m app.db.init --seed` as a one-off job (idempotent; never reseeds a
  seeded DB). Destructive downgrades are refused unless `-x allow_data_loss=true`.
- **Reseed** (`python -m app.services.synthetic_generator.seed`) deletes all follow-up, workflow
  and AI audit history of the run — never run it against the live demo by accident.

## 6. Claims

- Do not claim production readiness, clinical validation, or clinically reviewed rules
  (`clinical_review_status = not_reviewed`).
- Do not present programme eligibility or rule-level review flags as individual clinical need.
