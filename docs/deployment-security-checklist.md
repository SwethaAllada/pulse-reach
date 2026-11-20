# PulseReach — Hackathon Deployment Security Checklist

Scope: 10-day live hackathon demo of the MVP backend. **Not production-ready and not clinically
validated.** All patient data is synthetic.

## 1. Access control — user accounts, RBAC and organization isolation

Design: `docs/authentication-and-rbac.md`. Audit and gap analysis:
`docs/security-and-access-control-audit.md`.

- [ ] `AUTH_MODE=users` (the default). Every `/api/v1` route then needs a bearer access token,
  enforces a permission and limits patient data to the caller's organization / assignments / own
  record. `AUTH_MODE=legacy` (public reads + shared write key) exists only for frontend migration;
  startup logs a warning when it is active. Never run legacy mode with real accounts.
- [ ] Create the first administrator with `python -m app.services.identity create-admin` (password
  prompted, or `PULSEREACH_ADMIN_PASSWORD` from Secret Manager for that single command). Never
  commit or bake passwords into images or env files.
- [ ] Do **not** run `seed-demo` or set `DEMO_IDENTITY_SEED=true` in a deployment that will hold
  real accounts; demo users exist for judging/testing only and use the reserved `.invalid` domain.
- [x] Opaque access/refresh tokens, only SHA-256 digests stored; refresh rotation with reuse
  detection; server-side revocation (logout, password change/reset, deactivation). No signing
  secret to manage.
- [x] scrypt password hashing (N=2^17); per-account lockout; per-IP/identifier rate limits on
  authentication endpoints (per worker — add Cloud Armor / gateway limits for public URLs).
- [x] Actor attribution is server-derived; client `recorded_by` / `reviewed_by` / `reviewer` are
  ignored. Append-only `identity.audit_event` (triggers block UPDATE/DELETE/TRUNCATE).
- [x] Patient accounts are linked to records only through staff-issued one-time codes plus date of
  birth; e-mail is never treated as proof of identity.
- [ ] Behind a proxy (Cloud Run), run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy>`
  so per-IP rate limits see the client address rather than the proxy.
- [ ] Frontend: send `Authorization: Bearer <access_token>`; keep the refresh token out of
  `localStorage` where possible (memory / httpOnly cookie via a BFF); never put tokens in URLs.
- [ ] No e-mail/SMS integration exists: activation, reset and invitation codes are shown once to
  an authorized staff member and must be handed over through an approved channel.

### Legacy shared write key (`AUTH_MODE=legacy` only)

State-changing requests need `X-PulseReach-Write-Key` = `WRITE_API_KEY` (constant-time compare,
fails closed with `503` when unset unless `ALLOW_UNPROTECTED_WRITES=true`). Reads are public and
the actor is client-supplied. Store the key in Secret Manager (`--set-secrets
WRITE_API_KEY=pulsereach-write-key:latest`) and share it out of band.

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
- [x] Passwords, tokens, invitation/reset codes are never logged or returned after issuance; audit
  `details` hold identifiers only.

## 5. CORS, rate limiting, database access

- **CORS:** `CORS_ORIGINS` defaults to `http://localhost:3000`; set it to the deployed frontend
  origin(s) only. Never `*` (credentials are allowed).
- **Rate limiting:** authentication, registration, reset and portal-linking endpoints are limited
  in-process (per worker) and accounts lock after repeated failures. Use Cloud Run
  `--max-instances` (cost ceiling) and `--concurrency`, and Cloud Armor or the API gateway for
  distributed limits. LLM-backed endpoints (`/explanations`, `/outreach/draft`,
  `/insights/population`) now require authentication but remain the main cost risk.
- **Database:** reach Cloud SQL only through the Cloud Run Cloud SQL connector (Unix socket
  `/cloudsql/<connection-name>`). The connector needs either a public IP with **no authorized
  networks** (simplest; only IAM-authorised connector traffic is accepted) or a private IP with VPC
  egress. Use a dedicated user, a generated URL-safe password and automated backups. The Compose file publishes PostgreSQL on host port 5432 — for local
  use only; do not expose it on a shared host.
- **Migrations:** run `python -m app.db.init --seed` as a one-off job (idempotent; never reseeds a
  seeded DB; applies `0011` identity/engagement schemas). Destructive downgrades are refused unless
  `-x allow_data_loss=true`.
- **Tenant isolation** is application-level (no PostgreSQL RLS); keep the database reachable only
  by the API and init job.
- **Reseed** (`python -m app.services.synthetic_generator.seed`) deletes all follow-up, workflow
  and AI audit history of the run — never run it against the live demo by accident.

## 6. Claims

- Do not claim production readiness, security certification or regulatory compliance; the
  identity layer has had no independent security review.
- Do not claim production readiness, clinical validation, or clinically reviewed rules
  (`clinical_review_status = not_reviewed`).
- Do not present programme eligibility or rule-level review flags as individual clinical need.
