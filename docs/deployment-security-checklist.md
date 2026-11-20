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
- [ ] Behind Cloud Run set `TRUSTED_PROXY_HOPS=1` so per-IP rate limits use the address Cloud Run
  appends to `X-Forwarded-For`. Do **not** use uvicorn `--forwarded-allow-ips='*'`: it trusts the
  leftmost, client-chosen entry, letting a caller rotate rate-limit buckets.
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
  is the optional LLM provider (`app/services/ai/provider.py`, e.g. the Gemini API), off by default.
- [x] Outreach is simulated: approval records `outcome_status = "simulated_not_sent"`; DB `CHECK`s
  reject `sent`/`delivered` statuses; responses carry `sendable: false`, `delivered: false`.
- [x] Consent and eligibility are checked before any provider call and re-checked at approval.
- [x] The LLM never decides eligibility, due dates or care gaps; outputs are validated, with a
  deterministic fallback. Provider prompts carry no patient identifiers or contact details.

## 4. Secrets

- [x] No secrets in code or images: `DATABASE_URL`, `LLM_API_KEY` and `GEMINI_API_KEY` are
  `SecretStr` from the environment; `.dockerignore` excludes `.env*` (except `.env.example`), `.venv`, tests and `.git`.
- [x] Errors never return SQL, parameters or tracebacks; the API key is never logged or returned
  (`/ai/status` reports configuration only). The AI audit stores SHA-256 fingerprints, not texts.
- [ ] In GCP, put `DATABASE_URL` and `GEMINI_API_KEY` in Secret Manager (`pulsereach-database-url`,
  `pulsereach-gemini-api-key`; `--set-secrets`), never in `--set-env-vars`, build args, images or
  `NEXT_PUBLIC_*`, and use a strong generated database password. Create the Gemini secret from
  stdin (`read -s` + `--data-file=-`), grant only `roles/secretmanager.secretAccessor` on that
  secret to the Cloud Run runtime service account, and never create service-account keys
  (`docs/deployment-gcp.md` §3a, `docs/ai-gemini.md`).
- [ ] Restrict the Gemini API key to `generativelanguage.googleapis.com`, create it in the
  hackathon project (budget alert applies) and revoke it after judging.
- [x] Passwords, tokens, invitation/reset codes are never logged or returned after issuance; audit
  `details` hold identifiers only.

## 5. CORS, rate limiting, database access

- **CORS:** `CORS_ORIGINS` defaults to `http://localhost:3000`; set it to the deployed frontend
  origin(s) only. Never `*`. Credentials are not allowed cross-origin (bearer tokens only).
- **Request size:** bodies above `MAX_REQUEST_BODY_BYTES` (default 1 MiB, declared
  `Content-Length`) are refused with `413`; Cloud Run caps HTTP/1 requests at 32 MiB.
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
- **Population intelligence (BE-33):** migration `0012` adds `synthetic.condition_record` and the
  `population` schema (aggregates and alerts only). Keep `POPULATION_MIN_CELL_SIZE` at its default
  (5) or higher — it is the small-cell privacy threshold and is not organization-configurable.
  Optional: schedule `python -m app.services.population refresh` (Cloud Scheduler → Cloud Run job)
  every few minutes; otherwise snapshots refresh on first use and when stale
  (`POPULATION_FRESHNESS_CHECK_SECONDS`, `POPULATION_MAX_SNAPSHOT_AGE_SECONDS`,
  `POPULATION_REFRESH_TIMEOUT_SECONDS`, `POPULATION_RUNS_RETAINED`). Do not describe hotspots as
  outbreaks or the synthetic rates as Abu Dhabi prevalence.
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

## 7. Phase 6 readiness status (2026-11-20)

PASS = verified at runtime · FAIL = issue found and open · NOT RUN = not validated ·
ACCEPTED LIMITATION = known, accepted for the hackathon. Runbook: `docs/deployment-gcp.md`.

| Area | Status | Evidence / note |
|---|---|---|
| Authentication (login, expiry, refresh rotation, reuse detection, logout, password change/reset) | PASS | `test_auth.py` (offline + live PG `test_identity_live_pg.py`) |
| Frontend holds data requests until a staff session exists | PASS (unit) | `lib/api/client.test.ts`, `components/auth`; browser check NOT RUN |
| RBAC, five roles, permitted + forbidden operations | PASS | `test_rbac.py` matrix (every route declares a permission; 401 without token) |
| Organisation isolation (ids, list filters, task mutations, mixed-ownership writes, assignees, portal) | PASS | `test_tenant_isolation.py`, `test_cross_org_probes.py` (new) |
| Patient privacy: aggregate small-cell suppression | PASS | k=5; primary, cohort-complement, complementary suppression |
| Differencing (parent − visible children with small hidden total) | PASS after fix | was FAIL: Abu Dhabi district diabetes 12-month new cases revealed a hidden area as 1–2; fixed in `population/privacy.py`, swept by `test_parent_minus_visible_children_never_reveals_a_small_cell` |
| Differencing across nested time windows / trend direction of suppressed cells | ACCEPTED LIMITATION | documented in `geospatial-population-intelligence.md` §10 |
| Programme summary suppression vs. exact member lists | ACCEPTED LIMITATION (by design) | summaries cover only the caller's own patient scope, which the caller may already list individually |
| AI safety (no status changes, human approval, simulated outreach, guardrails, fallback) | PASS (mocked provider) | `test_ai_*.py`; native Gemini provider (`LLM_PROVIDER=gemini`) covered with mocked `httpx.post` only |
| Live Gemini API call (real smoke test, `docs/ai-gemini.md` §8) | NOT RUN | no key created; AI stays disabled (`LLM_ENABLED=false`) until it is |
| Gemini API key created in AI Studio and restricted to the Generative Language API | NOT RUN | `docs/deployment-gcp.md` §3a step 1 |
| Secrets server-side, never logged | PASS | `test_auth.py::test_secrets_never_logged`, `test_ai_service.py` |
| Secret Manager in GCP (`pulsereach-database-url`, `pulsereach-gemini-api-key`, accessor on the runtime SA only) | NOT RUN | no GCP resources exist yet; commands in `docs/deployment-gcp.md` §3/§3a |
| Gemini key rotation / revocation | NOT RUN | documented in `docs/deployment-gcp.md` §3a steps 6–8 |
| Database migrations 0001→0013 on a fresh DB; idempotent init + seed | PASS | disposable PG 17: `app.db.init --seed` twice, `alembic current` = 0013, startup validation OK |
| Live PostgreSQL regression | PASS | full suite inside the Podman VM (see final report) |
| Database backups / restore | NOT RUN | Cloud SQL automated backups configured by the runbook; restore drill not performed |
| HTTPS | ACCEPTED LIMITATION | provided by Cloud Run `run.app`; no HSTS header added by the app |
| CORS | PASS | explicit origins, no credentials (`test_edge_hardening.py`) |
| Rate limiting | PASS (in-process) / ACCEPTED LIMITATION (per instance) | `TRUSTED_PROXY_HOPS` spoof-resistant client address (`test_edge_hardening.py`); no distributed limiter |
| Request size limit | PASS | 413 above 1 MiB |
| Logging (structured JSON, request ids, PII redaction) | PASS | `test_observability.py` |
| Monitoring / alerting | NOT RUN | use Cloud Run metrics + a billing budget alert |
| Error handling (no stack traces/SQL in responses) | PASS | `app/core/errors.py`, tests |
| Synthetic data only | PASS | DB `CHECK is_synthetic`, `SYNTH-*` ids |
| Demo accounts | ACCEPTED LIMITATION | shared accounts can be locked for 15 min by 5 wrong passwords |
| Public `/docs`, `/openapi.json` | ACCEPTED LIMITATION | schema only; every data route needs a token |
| Rollback | NOT RUN | revision traffic switch documented |
| Resource cleanup | NOT RUN | commands documented in the runbook |
| Manual browser QA (themes, responsive, a11y, end-to-end demo) | NOT RUN | checklist in the Phase 6 report |
