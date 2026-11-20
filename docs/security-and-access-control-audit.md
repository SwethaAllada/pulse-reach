# PulseReach — Security and Access-Control Audit

Status: audit performed on the repository at commit `c71b10c` ("Security integrated") before any
identity / access-control work, then updated after implementation (section 12). All data in
PulseReach is synthetic. This document is an engineering review, **not** a security certification
or a compliance statement.

---

## 1. Existing implementation (before this change)

| Area | Location | Notes |
|---|---|---|
| App entry, middleware | `backend/app/main.py` | Request-ID middleware (`X-Request-ID`, validated), JSON access log, CORS (`CORS_ORIGINS`, credentials allowed, `GET/POST/PATCH/OPTIONS`). |
| Settings | `backend/app/core/config.py` | `pydantic-settings`; secrets as `SecretStr` (`DATABASE_URL`, `WRITE_API_KEY`, `LLM_API_KEY`). |
| Errors | `backend/app/core/errors.py` | Stable `{detail, error:{status, code, message, request_id}}`; no SQL / tracebacks. |
| Logging | `backend/app/core/logging.py` | JSON logs, PII redaction (Emirates ID, e-mail, UAE phone). |
| Startup validation | `backend/app/core/startup.py` | Refuses to start without the rule bundle (and seeded DB in `db` mode). |
| Write protection | `backend/app/core/write_auth.py` | Shared demo key `X-PulseReach-Write-Key` on non-GET routes (constant-time compare, fails closed). **Not identity.** |
| API | `backend/app/api/v1.py` (single router, 36 routes), `backend/app/api/health.py` | |
| Data access | `backend/app/repositories/read_repo.py`, `followup_repo.py` | Two interchangeable back ends: `DATA_SOURCE=memory` (default, deterministic in-process dataset) and `DATA_SOURCE=db` (PostgreSQL). |
| Models | `backend/app/models/{official,clinical,synthetic}.py` | Three PostgreSQL schemas; synthetic tables carry `run_id`, `is_synthetic CHECK`, `SYNTH-*` id checks, composite RESTRICT FKs, append-only triggers on history tables. |
| Migrations | `backend/migrations/versions/0001…0010` | Frozen static DDL; destructive downgrades refused unless `-x allow_data_loss=true`. |
| AI | `backend/app/services/ai/*` | Provider adapters, guardrails, prompts (versioned), audit log (memory deque or `synthetic.ai_audit_record`). LLM off by default. |
| Outreach | `backend/app/services/outreach/*` | Consent/authority gate; simulated only (`simulated_not_sent`). English templates only. |
| Follow-up | `backend/app/services/followup/*` | Completion requires validated evidence + deterministic re-evaluation. |
| Tests | `backend/tests/*` (31 files) | 459 passed / 112 skipped offline (PostgreSQL tests need `TEST_DATABASE_URL`). |
| Deployment | `backend/Dockerfile`, `infrastructure/docker-compose.yml`, `docs/deployment-security-checklist.md` | |

Repository-wide searches for `user_id`, `tenant_id`, `organization_id`, `created_by`,
`updated_by`, `permission`, `role`, `locale` in `backend/app` returned **no matches**. `token`
and `auth` only matched the write key and LLM `max_tokens`. `recorded_by`, `reviewed_by` and
`reviewer` exist as free-text, client-supplied columns.

## 2. Existing database models and relationships

- `official.*` (9 tables): SDI facility register, regions, SCAD aggregates — public reference data.
- `clinical.*`: rule loads, rules, rule items, open questions — global, versioned, hash-guarded.
- `synthetic.*` (18 + 2 tables): `generation_run`, `evaluation_run`, `facility_service_profile`,
  `patient` (has `preferred_language` `ar|en`, `preferred_channel`), `guardian`, `consent`,
  `history_availability`, `eligibility_evaluation`, `evaluation_reason`, `appointment`,
  `ifhas_screening`, `well_child_visit`, `component_result`, `assessment`, `referral`,
  `care_gap`, `care_gap_review`, `outreach_event`, `care_gap_follow_up_event`,
  `workflow_status_event`, `ai_audit_record`.
- All patient-owned rows are keyed by `(run_id, patient_id)`. **Reseeding deletes and recreates the
  whole run** (`synthetic_generator/load.py`), so any hard FK from new tables into `synthetic.*`
  would block reseeding.
- No organization, user, role, membership, session, or patient-account tables existed.

## 3. Existing API endpoints and their access requirements (before)

| Endpoint group | Access before |
|---|---|
| `GET /health`, `/health/db` | Public |
| All `GET /api/v1/*` (dashboard, patients + history/consents/evaluations/activity, care gaps, rules, facilities, open questions, appointments, referrals, histories, insights, AI status, **AI audit**) | **Public, unauthenticated** |
| `POST /evaluations`, `/outreach/preview`, `/explanations` | **Public** (explanations may call the LLM) |
| Other non-GET (`follow-ups`, `reviews`, `appointments`, `referrals`, `outreach/draft`, `outreach/draft/review`) | Shared write key only |

## 4. Authentication and authorization mechanisms (before)

- No user authentication, sessions, tokens, roles, permissions, or organizations.
- A single shared write key, held by anyone with the demo code; attribution fields
  (`recorded_by`, `reviewed_by`, `reviewer`) are whatever the client sends.
- CORS was the only cross-origin control; no rate limiting.

## 5. Patient-specific functionality (before)

- Staff-oriented patient views (summary, history, consents, evaluations, activity).
- No patient login, no account-to-record link, no patient-facing endpoints, no appointment
  requests, no assistance requests, no patient responses to follow-ups.

## 6. English / Arabic localization (before)

- `patient.preferred_language` / `guardian.preferred_language` (`ar|en`) stored as data.
- `official.facility.facility_name_ar` exposed in facility detail.
- Outreach preview and draft are **English-only**; Arabic is blocked (`template_unavailable` /
  `language_unsupported`) — deliberately, to avoid mislabelled English text.
- No locale negotiation, no localized messages, no RTL metadata, no user language preference.

## 7. Audit attribution (before)

- Follow-up, workflow-status and review rows are append-only (DB triggers) with `recorded_at`,
  but the actor is client text.
- AI audit records (`synthetic.ai_audit_record`) have request ID, feature, subject, fingerprints;
  `reviewed_by` is client text; no initiating user or organization.
- No general security/audit log of who read or changed what.

## 8. Security vulnerabilities and missing protections

| # | Finding | Severity (demo context) |
|---|---|---|
| V1 | All patient-level reads (incl. names, synthetic Emirates IDs, contact status, consents, clinical history) are public. | High |
| V2 | Actor identity is client-supplied (`recorded_by`, `reviewed_by`, `reviewer`) — spoofable audit trail. | High |
| V3 | Shared write key = no individual accountability, no revocation per person. | High |
| V4 | `GET /ai/audit` is public and exposes subject ids and review metadata. | Medium |
| V5 | `POST /explanations` is public and can trigger paid LLM calls when enabled (cost abuse). | Medium |
| V6 | No organization isolation; every caller sees all patients. | High |
| V7 | No rate limiting anywhere (brute-force against the write key possible). | Medium |
| V8 | No patient-facing access path at all (patients cannot see their own data). | Functional gap |

## 9. Feature-by-feature gap analysis (before → planned)

| Feature | Status before | Plan |
|---|---|---|
| Email/password login, logout | NOT IMPLEMENTED | Implement (opaque tokens, server-side sessions). |
| Access token generation/validation | NOT IMPLEMENTED | Opaque random tokens, SHA-256 stored, 15 min TTL. |
| Refresh tokens with rotation/revocation/reuse detection | NOT IMPLEMENTED | Implement per session family. |
| Password hashing (modern KDF) | NOT IMPLEMENTED | `hashlib.scrypt` (stdlib, memory-hard, OWASP-listed); versioned hash format; no new dependency. |
| Password reset (expiring single-use tokens) | NOT IMPLEMENTED | Implement; token delivery is simulated (no e-mail integration). |
| Account activation/deactivation | NOT IMPLEMENTED | Implement; deactivation revokes sessions immediately. |
| Failed-login protection, rate limiting | NOT IMPLEMENTED | Per-account lockout + per-IP/per-identifier sliding window. |
| User profile + language preference | NOT IMPLEMENTED | `/me`, `/me/preferences`. |
| Registration | NOT IMPLEMENTED | Patient self-registration (configurable) + admin-created staff. |
| Central permission model / RBAC | NOT IMPLEMENTED | `app/core/permissions.py` matrix + reusable dependencies. |
| Organizations, memberships, role per org | NOT IMPLEMENTED | `identity.organization`, `identity.membership`. |
| Patient ↔ organization association | NOT IMPLEMENTED | `identity.patient_organization` (patient-anchored tenancy). |
| Staff ↔ patient assignment | NOT IMPLEMENTED | `identity.patient_assignment`. |
| Patient account ↔ record link with verification | NOT IMPLEMENTED | Staff-issued one-time invitation code + date-of-birth check. |
| Scoped list/detail/write endpoints | NOT IMPLEMENTED | Filters applied before pagination/counts; 404 concealment. |
| Patient portal APIs | NOT IMPLEMENTED | `/api/v1/portal/*`. |
| Patient-facing follow-ups, requests, responses | NOT IMPLEMENTED | `engagement.*` tables + staff handling endpoints. |
| Simulated outreach (`simulated_not_sent`) | IMPLEMENTED | Preserve; approval restricted to `outreach.review`. |
| Deterministic evaluation engine | IMPLEMENTED | Untouched; language-independent. |
| Completion requires evidence | IMPLEMENTED | Preserve; patients can only *report*, never complete. |
| Append-only workflow history | IMPLEMENTED | Preserve; actor now server-derived. |
| AI audit | PARTIALLY IMPLEMENTED | Add initiating user, role and organization. |
| Security audit log | NOT IMPLEMENTED | `identity.audit_event`, append-only (trigger), filtered retrieval. |
| Request correlation ID | IMPLEMENTED | Reused in audit events. |
| Localization en/ar | PARTIALLY IMPLEMENTED (data only) | Message catalog, negotiation, RTL metadata, Arabic templates. |
| Arabic outreach drafts | NOT IMPLEMENTED (blocked by design) | Arabic deterministic template + Arabic guardrails, same review policy. |
| Startup / secret hygiene | IMPLEMENTED | Preserve. |
| PostgreSQL RLS | NOT IMPLEMENTED | Not introduced (see §10). |

## 10. Recommended implementation changes (chosen design)

1. **Identity store** in two new PostgreSQL schemas, `identity` and `engagement`, created by
   migration `0011`. The ORM models use a separate `MetaData` (`app/models/identity.py`) so the
   existing three-schema design and its tests are unchanged. In `DATA_SOURCE=memory` the same
   models run on an in-process SQLite database (schema names translated away), so the demo mode
   and the offline test suite exercise the exact same service code.
2. **Opaque bearer tokens** (`secrets.token_urlsafe`), stored only as SHA-256 hashes and checked
   against the server-side session on every request — no JWT library, no signing secret, instant
   revocation, disabled users rejected on their next request. Extensible to OIDC: the
   `Principal` abstraction is independent of how the credential was validated.
3. **Centralized permissions** (`app/core/permissions.py`) and dependencies
   (`app/core/auth.py`): `require(permission)` returns a `Principal` with organization and
   patient scope; routers never compare role names.
4. **Patient-anchored tenancy.** Every clinical/workflow row is owned by a patient. A patient
   belongs to exactly one organization (`identity.patient_organization`); appointments,
   referrals, care gaps, follow-ups, evaluations and AI audit subjects inherit the patient's
   organization. This avoids adding `organization_id` to the reseedable, constraint-heavy
   synthetic tables and to global reference data (rules, facilities). New tables
   (`engagement.*`, `identity.audit_event`) carry `organization_id` explicitly.
5. **Scope enforcement** in the API layer: list endpoints pass the allowed patient-id set into the
   repositories (filter before `count`/`limit`/`offset`); id-addressed endpoints resolve the
   owning patient first and answer `404` (same message as a missing record) when out of scope.
6. **Server-derived actor**: in user-auth mode `recorded_by` / `reviewed_by` / `reviewer` are
   overwritten with the authenticated user id; client values are ignored.
7. **RLS** is not introduced: the synthetic tables have no organization column and memory mode has
   no database, so RLS could not be applied consistently. Application-level enforcement is
   mandatory and tested; RLS remains a recommended hardening step for a production design.
8. **Backward compatibility**: `AUTH_MODE=users` (default) enforces the new model.
   `AUTH_MODE=legacy` keeps the previous behaviour (public reads + shared write key) for the
   existing frontend during migration; it is logged as a warning at startup and must not be
   used for a public deployment with real users.

## 11. Migration and backward-compatibility risks

| Risk | Mitigation |
|---|---|
| Existing frontend calls without credentials get `401` in `AUTH_MODE=users`. | `AUTH_MODE=legacy` transitional switch; documented frontend changes (send `Authorization: Bearer`). |
| `recorded_by`/`reviewed_by`/`reviewer` were required. | Still accepted (now optional); ignored and replaced in `users` mode; still required in `legacy` mode. |
| Reseed deletes synthetic patients. | No FKs from `identity`/`engagement` into `synthetic`; links keyed by `patient_id` text and validated at link time; orphaned links simply resolve to "not found". |
| Downgrade of `0011` would drop accounts and audit history. | Refused while data exists unless `-x allow_data_loss=true` (same pattern as `0009`/`0010`). |
| Dashboard numbers differ per caller. | Intended: aggregates are computed only over the caller's authorized patients (`n_adults`/`n_children` recomputed from date of birth when scoped). |
| Arabic outreach was intentionally blocked. | Now enabled only with Arabic templates and Arabic guardrails; the previous test asserting Arabic is blocked was updated. Other unsupported languages still block. |
| Audit events are written in a separate transaction from the business write. | Documented limitation; failures are logged loudly. |

---

## 12. Post-implementation status

See `docs/authentication-and-rbac.md`, `docs/patient-portal-api.md` and
`docs/localization-and-language-support.md` for the detailed design. Feature matrix after the
change:

| Feature | Before | After |
|---|---|---|
| Email/password login, logout, `/me` | NOT IMPLEMENTED | IMPLEMENTED |
| Access tokens (opaque, hashed, 15 min) | NOT IMPLEMENTED | IMPLEMENTED |
| Refresh rotation, reuse detection, revocation | NOT IMPLEMENTED | IMPLEMENTED |
| scrypt password hashing, rehash-on-login support | NOT IMPLEMENTED | IMPLEMENTED |
| Password reset (expiring, single use, sessions revoked) | NOT IMPLEMENTED | IMPLEMENTED (delivery simulated) |
| Activation / deactivation | NOT IMPLEMENTED | IMPLEMENTED |
| Account lockout + rate limiting | NOT IMPLEMENTED | IMPLEMENTED (in-process limiter per worker) |
| Patient self-registration | NOT IMPLEMENTED | IMPLEMENTED (`SELF_REGISTRATION_ENABLED`) |
| RBAC (5 roles, central matrix) | NOT IMPLEMENTED | IMPLEMENTED |
| Organizations, memberships, assignments | NOT IMPLEMENTED | IMPLEMENTED |
| Scoped lists / details / writes, 404 concealment | NOT IMPLEMENTED | IMPLEMENTED |
| Scoped dashboard / population insight / AI audit | NOT IMPLEMENTED | IMPLEMENTED |
| Verified patient linking (invitation + DOB) | NOT IMPLEMENTED | IMPLEMENTED |
| Patient portal APIs | NOT IMPLEMENTED | IMPLEMENTED |
| Patient-facing follow-up tasks, responses, assistance and appointment requests | NOT IMPLEMENTED | IMPLEMENTED |
| Server-derived actor attribution | NOT IMPLEMENTED | IMPLEMENTED (`users` mode) |
| Security audit log (append-only, filtered retrieval) | NOT IMPLEMENTED | IMPLEMENTED |
| AI audit with initiating user / org | PARTIALLY IMPLEMENTED | IMPLEMENTED |
| en/ar message catalog, negotiation, RTL metadata, date formatting | PARTIALLY IMPLEMENTED | IMPLEMENTED |
| Arabic outreach drafts with Arabic guardrails | NOT IMPLEMENTED | IMPLEMENTED (deterministic template; LLM output validated) |
| OIDC / SSO | NOT IMPLEMENTED | PENDING (design is extensible) |
| Real e-mail/SMS delivery (reset codes, invitations, reminders) | NOT IMPLEMENTED | PENDING (deliberately not implemented; simulated) |
| PostgreSQL RLS | NOT IMPLEMENTED | PENDING (application-level enforcement only) |
| Distributed rate limiting (multi-instance) | NOT IMPLEMENTED | PENDING (per-process limiter + persistent account lockout) |
| MFA | NOT IMPLEMENTED | PENDING |
| Live PostgreSQL verification of 0011 (`tests/test_identity_live_pg.py`) | — | NEEDS VERIFICATION (written, not yet run: local Podman networking was degraded) |
