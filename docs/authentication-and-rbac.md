# PulseReach — Authentication, RBAC and Organization Isolation

Engineering design of the identity layer added in migration `0011`. All patient data is
synthetic. This is a hackathon-grade implementation that follows standard practices; it has
**not** had an independent security review and is not claimed to be production-ready or compliant
with any regulation.

Code map:

| Concern | Location |
|---|---|
| Settings | `backend/app/core/config.py` (`AUTH_MODE`, token TTLs, lockout, scrypt cost, …) |
| Permission matrix | `backend/app/core/permissions.py` |
| Principal + dependencies (`require`, scope, `with_actor`) | `backend/app/core/auth.py` |
| Rate limiter | `backend/app/core/rate_limit.py` |
| Localized errors | `backend/app/core/i18n.py`, `backend/app/core/errors.py` |
| Models | `backend/app/models/identity.py` (schemas `identity`, `engagement`) |
| Store (PostgreSQL / in-memory SQLite) | `backend/app/services/identity/store.py` |
| Auth flows | `backend/app/services/identity/service.py`, `credentials.py` |
| Organizations, memberships, assignments, links | `backend/app/services/identity/directory.py` |
| Audit events | `backend/app/services/identity/audit.py` |
| Bootstrap / demo seed CLI | `backend/app/services/identity/demo.py`, `__main__.py` |
| Routers | `backend/app/api/auth.py`, `admin.py`, `portal.py`, `engagement.py`, `v1.py` |

---

## 1. Modes

| `AUTH_MODE` | Behaviour |
|---|---|
| `users` (default) | Every `/api/v1` route needs `Authorization: Bearer <access token>` (except login, registration, refresh and password-reset endpoints), enforces a permission, and limits patient data to the caller's scope. Client-supplied `recorded_by` / `reviewed_by` / `reviewer` are ignored and replaced by the authenticated user id. |
| `legacy` | The previous contract: public reads, shared `X-PulseReach-Write-Key` on writes, client-supplied actor (still required). Identity/portal/admin endpoints return 404. Kept only so the existing frontend keeps working during migration. Logged as a warning at startup. Do not use with real accounts. |

The offline regression suites run in `legacy` mode (set in `tests/conftest.py`); the identity,
RBAC, isolation, portal, localization and audit suites run in `users` mode.

## 2. Authentication flow and token lifecycle

```
POST /api/v1/auth/login {email, password, organization_id?}
  -> {access_token "pra_…", refresh_token "prr_…", expires_in, refresh_expires_in,
      user, organization_id, role, permissions}
GET  /api/v1/... Authorization: Bearer pra_…
POST /api/v1/auth/refresh {refresh_token}     -> new pair (rotation)
POST /api/v1/auth/logout                      -> session revoked
```

- **Opaque tokens**, 256-bit random (`secrets.token_urlsafe`). Only their SHA-256 digest is stored
  (`identity.auth_token`); raw tokens exist only in the response. No JWT library or signing secret
  is needed, and every request is checked against the server-side session, so revocation and
  deactivation take effect on the next request.
- **Session** (`identity.auth_session`): created at login, bound to one organization (or none for
  a self-registered account without membership), absolute lifetime `SESSION_MAX_AGE_SECONDS`
  (30 days). Access tokens live `ACCESS_TOKEN_TTL_SECONDS` (15 min); refresh tokens
  `REFRESH_TOKEN_TTL_SECONDS` (7 days), both capped by the session expiry.
- **Rotation**: a refresh marks the presented refresh token used, revokes the session's outstanding
  access tokens and returns a new pair.
- **Reuse detection**: presenting an already-used refresh token revokes the whole session
  (`revoke_reason = refresh_token_reuse`) and writes an `auth.refresh_reuse_detected` audit event.
- **Revocation**: `POST /auth/logout` (current session), `POST /auth/logout-all` (all sessions);
  password change keeps the current session and revokes the others; password reset, account
  deactivation, membership deactivation/role change and link revocation revoke sessions.
- **Validation on every request**: token exists, kind `access`, not revoked/expired; session not
  revoked/expired; user active; membership and organization of the session still active.
  Otherwise `401` with `WWW-Authenticate: Bearer`.
- **Organization switch**: `POST /auth/switch-organization {organization_id}` issues a new session
  in another organization where the user has an active membership; the old session is revoked.

### Passwords

- `hashlib.scrypt` (standard library, memory-hard, an OWASP-listed algorithm) with a random 16-byte
  salt, N = 2^17, r = 8, p = 1 by default (`PASSWORD_SCRYPT_N`), stored as
  `scrypt$N$r$p$salt$hash`. Hashes with a lower N are re-hashed on the next successful login, so
  the format can later move to Argon2id without a reset campaign. No custom cryptography: only
  standard-library primitives (`hashlib`, `hmac.compare_digest`, `secrets`).
- Policy: at least `PASSWORD_MIN_LENGTH` (12) characters, at most 1024 bytes, at least 5 distinct
  characters, must not contain the e-mail local part.
- Unknown e-mail, wrong password and disabled account return the same `401
  auth.invalid_credentials`; a dummy hash is computed for unknown accounts to equalize timing.

### Brute-force protection

- Per-account lockout: after `LOGIN_MAX_FAILURES` (5) consecutive failures the account is locked
  for `LOGIN_LOCKOUT_SECONDS` (15 min) → `429 auth.account_locked`. Persistent (database).
- Per-IP and per-identifier sliding window (`AUTH_RATE_LIMIT_PER_MINUTE`, 10/min) on login,
  registration, refresh, password change/reset and patient linking → `429` with `Retry-After`.
  The window is per worker process; use the platform (Cloud Armor / gateway) for distributed limits.

### Registration, activation, reset

- `POST /auth/register` (patients; disable with `SELF_REGISTRATION_ENABLED=false`) always answers
  `202 auth.registration_accepted`, whether or not the address existed. The account has no
  organization, role or data until it redeems a staff invitation (see `patient-portal-api.md`).
  The preferred language is taken from the body, otherwise from `Accept-Language`.
- Staff accounts are created by an organization administrator (`POST /admin/users`) **without** a
  password; the response contains a single-use activation code (`delivery:
  out_of_band_not_sent`) redeemed at `POST /auth/password-reset/confirm`.
- Password reset: `POST /auth/password-reset/request` always answers `202` and is audited.
  PulseReach has no e-mail/SMS integration, so codes are issued by an administrator
  (`POST /admin/users/{id}/password-reset`) and handed over out of band. Codes are single-use,
  expire (`PASSWORD_RESET_TTL_SECONDS`, 30 min; activation 3 days) and invalidate earlier codes.

### Profile and language

`GET/PATCH /api/v1/me` (full name, preferred language), `GET/PATCH /api/v1/me/preferences`
(`preferred_language` ∈ `en`, `ar`). See `localization-and-language-support.md`.

## 3. Roles and permissions

Roles are assigned per organization (`identity.membership`, one role per user per organization).
Routers depend only on permissions (`require("…")`); a test fails if any `/api/v1` route lacks a
permission marker.

| Permission | ADMIN | PHM | COORD | CLIN | PATIENT |
|---|:-:|:-:|:-:|:-:|:-:|
| users.read / create / update / deactivate | ✓ | | | | |
| organizations.manage | ✓ | | | | |
| assignments.manage | ✓ | ✓ | | | |
| patient_links.manage (list/revoke links) | ✓ | | | | |
| patient_links.invite | | ✓ | ✓ | | |
| audit_logs.read (`/audit-events`, `/ai/audit`) | ✓ | | | | |
| rules.read, rules.manage¹, facilities.read, platform.status | ✓ | ✓ (no manage) | ✓ (no manage) | ✓ (no manage) | facilities only |
| patients.read (whole organization) | | ✓ | grant² | grant² | |
| patients.read_assigned | | ✓ | ✓ | ✓ | |
| patients.read_self | | | | | ✓ |
| care_gaps.read, evaluations.read, appointments.read, referrals.read, followups.read, insights.read, ai.explain | | ✓ | ✓ | ✓ | |
| care_gaps.review | | ✓ | ✓ | ✓ | |
| care_gaps.complete (documented completion) | | | ✓ | ✓ | |
| evaluations.run | | ✓ | | ✓ | |
| appointments.create | | | ✓ | | |
| appointments.update | | | ✓ | ✓ | |
| referrals.create / update | | | ✓ | ✓ | |
| followups.create | | ✓ | ✓ | ✓ | |
| followups.update | | ✓ | ✓ | | |
| patient_requests.manage | | ✓ | ✓ | | |
| outreach.draft / outreach.review | | | ✓ | | |
| followups.respond, patient_requests.create | | | | | ✓ |

¹ `rules.manage` is reserved (no rule-editing endpoint exists; rules come from the versioned
bundle). ² Coordinators and clinicians see **assigned** patients only; an administrator can grant
organization-wide access explicitly (`PATCH /admin/users/{id} {"patient_access": "organization"}`).

SYSTEM_ADMIN has **no** patient-data permissions by default. Patients have no access to staff
endpoints, analytics, other patients, staff notes or audit logs.

Status codes: `401` unauthenticated · `403` authenticated without the permission (audited as
`authz.denied`) · `404` for patient-owned resources outside the caller's scope, with exactly the
same body as a missing record (audited as `authz.scope_denied`).

## 4. Organization isolation (tenant model)

- **Patient-anchored tenancy.** `identity.patient_organization` gives each synthetic patient at
  most one owning organization. Evaluations, care gaps, appointments, referrals, follow-up events,
  AI subjects and patient requests belong to a patient and inherit its organization; new tables
  (`engagement.*`, `identity.audit_event`, links, assignments) also store `organization_id`.
  Global reference data (rules, facilities, open questions) is not tenant-scoped.
- **Scope** (`Principal.patient_scope()`): organization patients (`patients.read`), assigned
  patients within the organization (`patients.read_assigned`), or the linked record (patients).
  Organization comes from the authenticated session, never from the request.
- **Lists** pass the allowed patient ids into the repositories, which filter **before** counting
  and pagination (`patient_ids` parameter on `list_patients`, `list_care_gaps`,
  `list_appointments`, `list_referrals`, `get_dashboard_summary`). Dashboard and population
  insight aggregates are computed over the caller's patients only (adults/children recomputed
  from guardian records when scoped).
- **Detail / update / history** endpoints resolve the owning patient first
  (`get_care_gap_patient_id`, `get_appointment_patient_id`, `get_referral_patient_id`) and answer
  404 when it is outside the scope. Create endpoints check the target patient.
- **AI**: explanations/drafts check the patient scope before any context is built; AI audit
  records store `actor_user_id`, `actor_role`, `organization_id`, and `/ai/audit` returns only the
  caller's organization. A draft from another organization cannot be reviewed.
- **Ownership changes** (`POST /admin/patient-ownership`) only attach unowned patients; patients
  owned by another organization are refused (409). Release ends assignments and portal links.
- **Background work**: there are no background jobs or queues; AI generation runs inside the
  request with the initiating user's scope.
- **PostgreSQL Row-Level Security is not used**: synthetic tables carry no organization column and
  memory mode has no database. Application-level enforcement is mandatory and covered by tests
  (`tests/test_tenant_isolation.py`); RLS is recommended hardening for a production design.

## 5. Audit logging

`identity.audit_event` (append-only: UPDATE/DELETE/TRUNCATE rejected by triggers in PostgreSQL)
records, for every state-changing operation, authentication event and authorization denial:
`occurred_at`, `request_id` (the `X-Request-ID` correlation id), `actor_user_id`, `actor_role`,
`organization_id`, `permission`, `action`, `resource_type`, `resource_id`, `patient_id`, `outcome`
(`success` · `denied` · `failed`), `status_code`, and `details` (identifiers/metadata only — never
notes, messages, passwords or tokens). Events are also mirrored to the JSON log
(`pulsereach.audit`).

Retrieval: `GET /api/v1/audit-events` (`audit_logs.read`), organization-scoped, filters `action`,
`resource_type`, `actor_user_id`, `patient_id`, `outcome`, `since`, `until`, paginated after
filtering. There is no API to modify or delete audit events.

Limitation: audit events are written in their own transaction after the business write; a failed
audit write is logged loudly (`AUDIT WRITE FAILED`) but does not undo the completed operation.

## 6. Environment variables

| Variable | Default | Notes |
|---|---|---|
| `AUTH_MODE` | `users` | `legacy` only during frontend migration |
| `ACCESS_TOKEN_TTL_SECONDS` | `900` | 60–3600 |
| `REFRESH_TOKEN_TTL_SECONDS` | `604800` | |
| `SESSION_MAX_AGE_SECONDS` | `2592000` | absolute session lifetime |
| `PASSWORD_RESET_TTL_SECONDS` / `ACCOUNT_ACTIVATION_TTL_SECONDS` | `1800` / `259200` | |
| `PATIENT_INVITATION_TTL_SECONDS` / `PATIENT_INVITATION_MAX_ATTEMPTS` | `604800` / `5` | |
| `PASSWORD_MIN_LENGTH` | `12` | |
| `PASSWORD_SCRYPT_N` | `131072` | lower only in tests |
| `LOGIN_MAX_FAILURES` / `LOGIN_LOCKOUT_SECONDS` | `5` / `900` | |
| `AUTH_RATE_LIMIT_PER_MINUTE` | `10` | per worker |
| `SELF_REGISTRATION_ENABLED` | `true` | patient self-registration |
| `DEFAULT_LOCALE` | `en` | `en` or `ar` |
| `DEMO_IDENTITY_SEED` / `DEMO_IDENTITY_PASSWORD` | `false` / unset | memory mode only; seeds demo users at startup |
| `WRITE_API_KEY`, `ALLOW_UNPROTECTED_WRITES` | | legacy mode only |

No JWT/signing secret is required (opaque tokens).

## 7. Migration and initialization

- `alembic upgrade head` (or `python -m app.db.init --seed`) applies `0011`: new schemas
  `identity` and `engagement`; nothing existing is altered. Initialization stays idempotent and
  never reseeds a seeded database.
- `python -m app.services.synthetic_generator.seed` (reseed) does not touch identity data; links
  and ownership refer to the deterministic `SYNTH-PAT-*` ids and keep working.
- Downgrading `0011` refuses while accounts, audit events, tasks or requests exist unless
  `alembic -x allow_data_loss=true downgrade 0010`.

## 8. Creating the first administrator (securely)

From `backend/` with `DATA_SOURCE=db` and `DATABASE_URL` set:

```bash
python -m app.services.identity create-admin \
  --email admin@your-org.example --full-name "Platform Admin" \
  --org-name "Your Organization" --org-slug your-org
# Password is prompted (not echoed); for automation set PULSEREACH_ADMIN_PASSWORD from a secret
# manager for that one command only. Never put it in the repository, images or shell history.
```

Then, signed in as that administrator: attach patients (`POST /api/v1/admin/patient-ownership`
`{"region_id": 1}` or `{"patient_ids": [...]}`), create staff (`POST /api/v1/admin/users`, hand the
activation code over out of band), and assign patients (`POST /api/v1/admin/assignments`).

## 9. Demo organizations and users

```bash
# PostgreSQL (DATA_SOURCE=db): passwords random and printed once, or shared via the env var
DEMO_IDENTITY_PASSWORD='<choose-a-demo-passphrase>' python -m app.services.identity seed-demo
# Memory mode: seeded at API startup
DATA_SOURCE=memory DEMO_IDENTITY_SEED=true DEMO_IDENTITY_PASSWORD='<choose-a-demo-passphrase>' uvicorn app.main:app
```

Creates `demo-org-a` (region 1) and `demo-org-b` (regions 2 and 3), and in each:
`admin.{a|b}@demo.pulsereach.invalid` (SYSTEM_ADMIN), `manager.*` (POPULATION_HEALTH_MANAGER,
organization-wide), `coordinator.*` (CARE_COORDINATOR, 20 assigned patients), `clinician.*`
(CLINICIAN, 10 assigned patients) and `patient.*` (PATIENT, linked to one patient through the
invitation + date-of-birth workflow). All names are marked synthetic; addresses use the reserved
`.invalid` TLD. Idempotent; existing passwords are never changed.

## 10. Testing each role

```bash
TOKEN=$(curl -s localhost:8000/api/v1/auth/login -H 'content-type: application/json' \
  -d '{"email":"coordinator.a@demo.pulsereach.invalid","password":"<demo passphrase>"}' | jq -r .access_token)
curl -s localhost:8000/api/v1/patients -H "Authorization: Bearer $TOKEN" | jq .total   # 20 (assigned)
curl -s localhost:8000/api/v1/admin/users -H "Authorization: Bearer $TOKEN"            # 403
```

| Sign in as | Expect |
|---|---|
| `admin.a` | `/admin/*`, `/audit-events`, `/ai/audit` work; `/patients` → 403 |
| `manager.a` | `/patients` total = region-1 population; dashboard/insights scoped; `/admin/assignments` works |
| `coordinator.a` | 20 patients; drafts/reviews outreach; manages follow-up tasks and patient requests |
| `clinician.a` | 10 patients; documented completion, referrals; no outreach |
| `patient.a` | `/portal/*` only; `/patients` → 403; other ids → 404 |
| `manager.b` | never sees region-1 patients (404 / excluded from totals) |

Automated: `tests/test_auth.py`, `test_rbac.py`, `test_tenant_isolation.py`,
`test_patient_portal.py`, `test_localization.py`, `test_audit_events.py` (offline) and
`test_identity_live_pg.py` (PostgreSQL).

## 11. Extending to OIDC / SSO

`get_principal` is the only place that turns a credential into a `Principal`. An OIDC integration
would validate the identity provider's token there (or exchange it at a new `/auth/oidc/callback`
for a PulseReach session), map the subject to `identity.user_account`, and keep memberships,
permissions, scope and audit unchanged.
