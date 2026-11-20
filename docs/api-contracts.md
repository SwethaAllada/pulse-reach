# PulseReach Backend API Contracts (`/api/v1`)

> **Governance & Synthetic Data Notice:**
> - Every patient record, evaluation, care gap, and outreach preview returned by `/api/v1/*` is **100% synthetic** (`is_synthetic: true`, IDs prefixed `SYNTH-<CODE>-`, Emirates IDs prefixed `SYNTH-EID-`).
> - Clinical rules are transcribed from published Abu Dhabi Department of Health (DoH) standards for engineering use (`clinical_review_status: "not_reviewed"`).
> - Eligibility, due dates, and care gaps are computed exclusively by the deterministic evaluation engine (`app.services.evaluation`), never by an LLM.
> - Missing screening history (`not_available`) always evaluates to `unknown`, never `due` or `overdue`.
> - Unresolved or review-flagged rules always evaluate to `requires_clinical_review`.
> - Outreach previews (`POST /api/v1/outreach/preview`) are **simulated only** (`simulated_only: true`) and blocked unless `contact` consent is `granted`.
> - AI assistance (explanations, outreach drafts, population insights) only restates deterministic results; it is off unless `LLM_ENABLED=true` with `LLM_API_KEY` and `LLM_MODEL`, and every output is validated with a deterministic fallback.
>
> **Errors:** every error body keeps `detail` and adds `error: {status, code, message, request_id}` (+ `message_key`, `locale` for localized errors; `code` in `bad_request`, `unauthorized`, `forbidden`, `not_found`, `conflict`, `validation_error`, `rate_limited`, `service_unavailable`, `internal_error`). Validation `detail` items carry only `type`, `loc`, `msg`. Database and unexpected errors never return SQL, parameters or tracebacks. Database constraint violations on writes are `409`.
>
> **Authentication (`AUTH_MODE=users`, default):** every `/api/v1` endpoint requires `Authorization: Bearer <access token>` from `POST /api/v1/auth/login`, except login, registration, refresh and password-reset endpoints. Missing/invalid/expired/revoked token → `401` (`WWW-Authenticate: Bearer`); missing permission → `403` (`error.code = "forbidden"`); patient-owned resources outside the caller's organization/assignment/self scope → `404` with the same body as a missing record. List endpoints and dashboard/insight aggregates include only the caller's authorized patients (filtered before `total`/pagination). Rate limits → `429` (`rate_limited`, `Retry-After`). See `authentication-and-rbac.md`.
>
> **Writes:** in `AUTH_MODE=users` the actor fields (`recorded_by`, `reviewed_by`, `reviewer`) are optional and **ignored**: the stored actor is the authenticated user id. Every state-changing request also produces an audit event (`GET /api/v1/audit-events`).
>
> **Legacy mode (`AUTH_MODE=legacy`, migration only):** the previous contract — GET endpoints public; every non-GET request except `POST /evaluations`, `POST /outreach/preview` and `POST /explanations` needs `X-PulseReach-Write-Key` (`WRITE_API_KEY`; missing/invalid → `401`, not configured → `503`); actor fields are client-supplied and required. Identity, admin, portal and engagement endpoints return `404`.
>
> **Localization:** `?lang=en|ar` > user preference > `Accept-Language`. Catalog-backed errors add `error.message_key` and `error.locale` and localize `error.message`; `detail` is unchanged. See `localization-and-language-support.md`.
>
> **Conflicts (`409`):** `detail` is a string for constraint violations, or an object for:
> - duplicate requests — `{"message", "code": "duplicate_request", "existing_id"}`: an active (`scheduled`/`rescheduled`) appointment for the same patient, facility profile, type and `scheduled_datetime`; an active (`pending`/`initiated`) referral for the same patient, rule/version and target; or a non-completion follow-up identical to one recorded on the same gap within 60 s (same requested event type, actor and note). A second completion of a closed gap stays `422` (`care_gap_not_open`).
> - an outreach draft that already has a final decision — `{"message", "code": "draft_already_reviewed", "review_status": "approved" | "rejected", "review_audit_id", "follow_up_id"}`.
>
> `error.message` repeats `detail.message` when `detail` is an object.

---

## 1. Endpoint Summary

| Method & Path | Purpose | Response Schema |
|---|---|---|
| `GET /health` | Service health check | `{"status": "ok"}` |
| `GET /health/db` | Database connectivity status (`200` when connected, `503` when degraded) | `{"status": "ok" \| "degraded", "database": "ok" \| "not_configured" \| "unavailable"}` |
| `GET /api/v1/dashboard/summary` | Population, per-person status, pathway, gap, region, and clinical rule breakdowns | `DashboardSummaryOut` |
| `GET /api/v1/patients` | Paginated synthetic patient list with search (`q`), sorting (`sort_by`, `sort_dir`), and filters (`sex`, `region_id`, `pathway`, `evaluation_status`, `has_open_care_gaps`, `history_status`, `age_band`). With `pathway`, `has_open_care_gaps` counts only open gaps under that programme's rules and `history_status` matches that programme's history record; without `pathway` both match any programme | `PaginatedPatientsOut` |
| `GET /api/v1/programmes/{pathway}/summary` | Programme aggregates for the caller's patient scope (`insights.read` + `care_gaps.read`; organization or assigned patients) and optional `region_id`, `sex`, `age_band`, `period` (`7d`\|`30d`\|`90d`\|`6m`\|`12m`, default `90d`): `members` (people with a history record for the programme, the same set as `/patients?pathway=`), `history`, mutually exclusive `segments` (`open_gap` under the programme's rules, otherwise the history status), `people_with_open_gap`, `care_gaps` (records by status + `total`), `open_gaps_by_type`, `eligibility` (dashboard semantics restricted to the members) and `trend`. The trend compares periods only when persisted evaluation runs cover the previous window (`previous_period_observed`); otherwise previous counts are `null` and the direction is `INSUFFICIENT_DATA` (`evaluation_history_incomplete`). Counts `0 < n < POPULATION_MIN_CELL_SIZE` and the complementary cell of a partition with a published total are `null` and listed in `suppressed` (`["all"]` when the member set is below the threshold) | `ProgrammeSummaryOut` |
| `GET /api/v1/patients/{patient_id}` | Single synthetic patient detail and pathway history availability | `PatientSummaryOut` |
| `GET /api/v1/patients/{patient_id}/history` | Clinical history, screenings, well-child visits, component results, assessments, and referrals | `PatientHistoryOut` |
| `GET /api/v1/patients/{patient_id}/consents` | Recorded consent history and current effective consent state | `PatientConsentsOut` |
| `GET /api/v1/patients/{patient_id}/evaluations` | All 54 deterministic rule evaluations, fired reasons/guards, rule citations, zero-PII `input_snapshot`, and care gaps. Evaluations are the unchanged historical results of `evaluation_run_id` at `reference_date`; `superseded_by_completion` / `superseded_by_care_gap_id` mark an evaluation whose care gap was later closed as `closed_completed` (the care gap holds the current state) | `PatientEvaluationsOut` |
| `POST /api/v1/evaluations` | Deterministic evaluation for a synthetic patient (`patient_id`, `look_ahead_days` `0..365`). With the run's default look-ahead (30) it returns the stored evaluations (`is_persisted: true`). Otherwise it recomputes ad hoc and stores nothing: `is_persisted: false` and ids are `EPHEMERAL-{patient_id}-EVL-NNNN` / `EPHEMERAL-{patient_id}-GAP-NNNN`, which never resolve via `/care-gaps/{id}` | `PatientEvaluationsOut` |
| `GET /api/v1/rules` | List/filter clinical rules (`pathway` in `ifhas\|well_child`, `verification_status` in `verified\|reported\|unresolved`, `is_authoritative`) | `PaginatedRulesOut` |
| `GET /api/v1/rules/{rule_id}` | Full rule detail, partial-date triples, items (`effective_authority`), and open questions | `RuleDetailOut` |
| `GET /api/v1/care-gaps` | Paginated evidence-backed care gaps (`patient_id`, `status`, `gap_type`, `rule_id`, `limit`, `offset`) | `PaginatedCareGapsOut` |
| `GET /api/v1/care-gaps/{gap_id}` | Care gap detail: closing evidence (`closed_by_ifhas_screening_id` / `_well_child_visit_id` / `_referral_id`), linked appointments, referrals, outreach events, follow-up events, `workflow_events` (appointment/referral status history), clinical `reviews`, and `recommended_pathway` (next step transcribed verbatim from the rule spec: `status` = `documented_next_step` \| `requires_clinical_review` \| `no_documented_pathway`; never inferred) | `CareGapDetailOut` |
| `GET /api/v1/care-gaps/{gap_id}/follow-ups` | Paginated follow-up timeline of the gap, newest first | `PaginatedFollowUpEventsOut` |
| `POST /api/v1/care-gaps/{gap_id}/reviews` | Record a clinical-review decision (`reviewer`, `action` = `confirmed` \| `dismissed`, `reason`). Does not change the gap status. `priority_overridden` → `422` (no priority model exists) | `CareGapReviewOut` |
| `GET /api/v1/care-gaps/{gap_id}/reviews` | Review decisions for the gap, oldest first | `CareGapReviewsOut` |
| `GET /api/v1/patients/{patient_id}/activity` | Audit trail of all follow-up and workflow events recorded for the person | `PatientActivityOut` |
| `POST /api/v1/care-gaps/{gap_id}/follow-ups` | Append-only follow-up event (`outreach_attempted`, `completion_documented`, `note_recorded`) with consent & evidence enforcement. `completion_documented` requires `close_gap=true` (and vice versa). An `outreach_attempted` with granting contact consent is stored with `outcome_status: "simulated_not_sent"` (outreach is never sent or delivered); anything else is stored as `outreach_suppressed` with the blocking reason. A missing language template does not suppress a consented attempt. `close_gap=true` requires a screening / well-child visit / referral of the same patient and the gap's rule, with completed status and valid date, on which the deterministic engine re-run with current records reports the rule `completed`/`upcoming`; otherwise `422` with a `reason_code` in `detail` (e.g. `evidence_rule_mismatch`, `evidence_not_completed`, `evaluation_requires_clinical_review`) | `FollowUpEventOut` |
| `GET /api/v1/appointments` | Paginated synthetic appointments (`patient_id`, `care_gap_id`, `status`, `limit`, `offset`; Phase 5: `status_group` = `active` (scheduled\|rescheduled) \| `cancelled`, `profile_id`, `scheduled_from` (inclusive) / `scheduled_to` (exclusive), `order` = `desc` (default) \| `asc` by scheduled time, then `appointment_id` — same order in memory and PostgreSQL) | `PaginatedAppointmentsOut` |
| `GET /api/v1/facility-service-profiles` | Simulated facility service profiles appointments are recorded against (`pathway` filter = offers IFHAS / well-child). `capability_basis` is always `simulated`; `facility_name` is the published SDI name in DB mode (`null` in memory mode). No availability or booking engine exists: an appointment is recorded for coordination, not confirmed with a provider (`notice`) | `ServiceProfilesOut` |
| `POST /api/v1/appointments` | Schedule a synthetic appointment (`AppointmentCreateIn`, `recorded_by` required). Writes a workflow event and, when `care_gap_id` is set, an `appointment_scheduled` gap event | `AppointmentOut` |
| `PATCH /api/v1/appointments/{appointment_id}` | Validated status transition (`AppointmentPatchIn`, `recorded_by` required; `scheduled_datetime` required for and only allowed with `rescheduled`). Prior status and datetime are kept in the history; `attended` never closes a gap | `AppointmentOut` |
| `GET /api/v1/appointments/{appointment_id}/history` | Append-only status history (`from_status` null on creation) | `WorkflowHistoryOut` |
| `GET /api/v1/referrals` | Paginated synthetic referrals (`patient_id`, `status`, `limit`, `offset`) | `PaginatedReferralsOut` |
| `POST /api/v1/referrals` | Create a synthetic referral linked to screening/visit/assessment (`ReferralCreateIn`, `recorded_by` required, optional `care_gap_id` of the same patient to link it to a gap) | `ReferralOut` |
| `PATCH /api/v1/referrals/{referral_id}` | Validated referral status/date transition (`ReferralPatchIn`, `recorded_by` required). Logged on every linked gap (subject gap or `care_gap_id` given at creation) | `ReferralOut` |
| `GET /api/v1/referrals/{referral_id}/history` | Append-only status history incl. initiated/completed dates | `WorkflowHistoryOut` |
| `GET /api/v1/facilities` | Official Abu Dhabi SDI facility facts with published coordinates (`latitude`, `longitude`, `geo_quality`). Filters: `region_id` (1-3), `facility_type` (case-insensitive, e.g. `Hospital`), `source_layer`, `q` (name/city). `capability_basis: "unverified_sdi_facts_only"`; capability fields are always `null` | `PaginatedFacilitiesOut` |
| `GET /api/v1/facilities/points` | Map/directory facility layer: identified SDI facilities with an `Active` (or `Temporary Closure`) licence and `geo_quality` `ok`, for `source_layer` (repeatable; default hospitals, health centres, clinics; unknown layer → `422`). `register` reconciles the full published register to the plotted points, exclusions applied in order: `register_total` (all layers), `in_layers`, `excluded_unidentified`, `excluded_license_status`, `excluded_invalid_coordinates`, `mappable` (= `total`), `license_statuses_included` (statuses actually present among mappable rows). Default request: 5,339 / 2,654 / 0 / 1,028 / 1 / 1,625, `["Active"]`. `excluded_without_coordinates` = `register.excluded_invalid_coordinates`. Points carry facility fields only, never patient data | `FacilityPointsOut` |
| `GET /api/v1/facilities/{ch_fid}` | All published SDI facts for one facility, by publisher key `ch_fid`. Always percent-encode it as one path segment (`encodeURIComponent`): it contains `#`, which a browser otherwise treats as a fragment and never sends (e.g. `/api/v1/facilities/abc%23123`) | `FacilityDetailOut` |
| `GET /api/v1/open-questions` | Open-question register (`oq_id`, `title`, `detail`, `status`, `category`, `affects`, `resolve_via`, linked `rule_ids`); filters `status`, `category`. Questions are reported, never answered | `PaginatedOpenQuestionsOut` |
| `GET /api/v1/open-questions/{oq_id}` | One open question | `OpenQuestionOut` |
| `POST /api/v1/explanations` | Plain-language explanation of a precomputed evaluation; AI-grounded when enabled, deterministic otherwise. `ai` gives `generation_mode`, `prompt_version`, `provider`, `model`, `fallback_reason`, `violations`, `audit_id` | `ExplanationOut` |
| `POST /api/v1/outreach/preview` | Permission-checked simulated outreach message preview (never sends real messages). `language` `en` or `ar` (Arabic template) | `OutreachPreviewOut` |
| `POST /api/v1/outreach/draft` | Same gate as the preview; when allowed, an AI-assisted (or template) simulated draft. `sendable` is always `false`; the model is never called for blocked outreach. `ai.audit_id` is the durable draft id used for review (in `DATA_SOURCE=db` it survives restarts and is shared by all workers) | `OutreachDraftOut` |
| `POST /api/v1/outreach/draft/review` | Human decision on a draft (`draft_audit_id`, `patient_id`, `rule_id`, `care_gap_id`, `channel`, `language` must match the draft; `decision` = `approved` \| `rejected`; `final_message` required for approval; `reviewed_by`; optional `reason`, whose text is not stored). Approval re-checks consent and eligibility (`review_status: "blocked"` + `blocked_reason` if they changed), re-validates the possibly edited text (`422` with `violations`), and records one `outreach_attempted` follow-up with `outcome_status: "simulated_not_sent"`, returned as `follow_up` (also visible at once in `/care-gaps/{id}/follow-ups` and `/patients/{id}/activity`). Response also has `review_audit_id`, `edited`, `simulated_outreach_status`, and `simulated_only: true`, `sendable: false`, `delivered: false`. One final decision per draft: a replayed or concurrent approval, or approving a rejected draft, is `409 draft_already_reviewed`; unknown or blocked drafts are `404` | `OutreachDraftReviewOut` |
| `GET /api/v1/insights/population` | Aggregate facts from the dashboard plus a narrative restating them (numbers not in the facts are rejected) | `PopulationInsightOut` |
| `GET /api/v1/ai/status` | AI configuration (enabled, provider, model, prompt versions; never the key) | `AIStatusOut` |
| `GET /api/v1/ai/audit` | Recent AI generation and human-review audit records, newest first (`feature` = `explanation` \| `outreach_draft` \| `outreach_review` \| `population_insight`, `limit` 1-500). Each record: `audit_id`, `recorded_at`, `request_id`, `feature`, `subject` (synthetic ids), `run_id`, `prompt_version`, `provider`, `model`, `generation_mode` (`llm_grounded`, `deterministic_fallback`, `not_generated`, `human_approved` / `_rejected` / `_blocked` / `_invalid`), `fallback_reason`, `violations`, `input_sha256`, `output_sha256`, `latency_ms`, `extra` (channel, language, tone, `reviewed_by`, `follow_up_id`, `simulated_outreach_status`, `edited`, fingerprints). Message texts are never stored. `durable: true` when stored in PostgreSQL (`synthetic.ai_audit_record`, append-only); memory mode keeps a bounded in-process buffer | `AIAuditOut` |

### Permissions of the clinical endpoints (`AUTH_MODE=users`)

| Endpoint(s) | Permission | Scope |
|---|---|---|
| `GET /dashboard/summary`, `GET /insights/population` | `insights.read` | aggregates over the caller's patients |
| `GET /patients`, `/patients/{id}`, `/history`, `/consents` | `patients.read` or `patients.read_assigned` | organization or assigned patients |
| `GET /patients/{id}/evaluations` | `evaluations.read` | same |
| `POST /evaluations` | `evaluations.run` | same |
| `GET /patients/{id}/activity`, `GET /care-gaps/{id}/follow-ups` | `followups.read` | same |
| `GET /care-gaps`, `/care-gaps/{id}`, `GET …/reviews` | `care_gaps.read` | same |
| `POST /care-gaps/{id}/reviews` | `care_gaps.review` | same |
| `POST /care-gaps/{id}/follow-ups` | `followups.create` (+ `care_gaps.complete` for `completion_documented`) | same |
| `GET /appointments`, `…/history` · `POST` · `PATCH` | `appointments.read` · `appointments.create` · `appointments.update` | same |
| `GET /referrals`, `…/history` · `POST` · `PATCH` | `referrals.read` · `referrals.create` · `referrals.update` | same |
| `POST /explanations` | `ai.explain` | same |
| `POST /outreach/preview`, `POST /outreach/draft` | `outreach.draft` | same |
| `POST /outreach/draft/review` | `outreach.review` | same; draft must come from the caller's organization |
| `GET /rules*`, `GET /open-questions*` | `rules.read` | global reference data |
| `GET /facilities*`, `GET /facility-service-profiles` | `facilities.read` | global reference data |
| `GET /ai/status` | `platform.status` | — |
| `GET /ai/audit` | `audit_logs.read` | records initiated in the caller's organization (`extra.organization_id`, `extra.actor_user_id`, `extra.actor_role`) |

### Identity, administration, engagement and portal endpoints (`AUTH_MODE=users` only)

| Method & Path | Permission | Purpose |
|---|---|---|
| `POST /api/v1/auth/login` | public | `{email, password, organization_id?}` → `TokenOut` (`access_token`, `refresh_token`, `expires_in`, `refresh_expires_in`, `user`, `organization_id`, `role`, `permissions`) |
| `POST /api/v1/auth/refresh` | public | `{refresh_token}` → new `TokenOut` (rotation; reuse revokes the session) |
| `POST /api/v1/auth/register` | public | Patient self-registration; always `202` |
| `POST /api/v1/auth/password-reset/request` | public | Always `202` (no e-mail is sent) |
| `POST /api/v1/auth/password-reset/confirm` | public | `{token, new_password}` (reset or activation code) → `204` |
| `POST /api/v1/auth/logout`, `/auth/logout-all` | authenticated | Revoke current / all sessions → `204` |
| `POST /api/v1/auth/password/change` | authenticated | `{current_password, new_password}` → `204`, other sessions revoked |
| `POST /api/v1/auth/switch-organization` | authenticated | `{organization_id}` → new `TokenOut` |
| `GET/PATCH /api/v1/me`, `GET/PATCH /api/v1/me/preferences` | authenticated | Profile, memberships, permissions, language |
| `GET/POST /api/v1/admin/organizations` | `organizations.manage` | List own / create (creator becomes admin) |
| `POST /api/v1/admin/patient-ownership`, `…/release` | `organizations.manage` | Attach unowned patients (`patient_ids` / `region_id`; others' → `409`) / release |
| `GET/POST /api/v1/admin/users`, `GET/PATCH /api/v1/admin/users/{id}` | `users.read` / `users.create` / `users.update` | Members of the organization; create returns a one-time activation code |
| `POST /api/v1/admin/users/{id}/deactivate`, `/activate` | `users.deactivate` | Account (or, if multi-org, membership) status; sessions revoked |
| `POST /api/v1/admin/users/{id}/password-reset` | `users.update` | One-time reset code for out-of-band delivery |
| `GET/POST /api/v1/admin/assignments`, `POST …/{id}/end` | `assignments.manage` | Staff ↔ patient assignments |
| `POST /api/v1/patients/{id}/portal-invitations` | `patient_links.invite` + patient scope | One-time invitation code |
| `GET /api/v1/admin/patient-links`, `POST …/{id}/revoke` | `patient_links.manage` | Account ↔ record links |
| `GET /api/v1/audit-events` | `audit_logs.read` | Organization audit events (filters before pagination) |
| `GET/POST /api/v1/follow-up-tasks`, `GET/PATCH /api/v1/follow-up-tasks/{id}`, `POST …/notes`, `…/escalate`, `…/complete` | `followups.read` / `followups.create` / `followups.update` | Patient-facing follow-up tasks (see `patient-portal-api.md`). Phase 5 (migration 0013): `priority` (`routine` default \| `high` \| `urgent`; operational urgency, not a clinical score) on create/PATCH, `is_due_soon` (active, due within 7 days); list filters `active`, `assigned_to` (`me` \| `unassigned` \| user id), `priority`, `pathway` (programme of the task's rule), `region_id` (patient region), `due_after` / `due_before` |
| `POST /api/v1/follow-up-tasks/{id}/contact-attempts` | `followups.update` + patient scope | Documents a contact attempt a staff member made outside PulseReach (`channel` = `phone`\|`sms`\|`email`\|`in_person`\|`portal`, `outcome` = `reached`\|`no_answer`\|`left_message`\|`wrong_contact_details`\|`declined`, optional `note`). Internal `contact_attempt` event (outcome in `response_code`); never shown to the patient; does not change the task status; nothing is sent. `422 workflow.contact_not_permitted` unless the current applicable `contact` consent (same resolution as outreach, for the task's rule/programme; global consent for tasks without a rule) is `granted`, or when the patient is deceased; `409` on closed tasks |
| `GET /api/v1/follow-up-tasks/summary` | `followups.read` | Exact counts over every task in the caller's scope matching the list filters: `total`, `active`, `overdue`, `due_soon` (`due_soon_days` = 7), `completed`, `cancelled`, `unassigned_active`, `patient_reported_completion`, `by_status`, `active_by_priority`, per-assignee `workload` (`assigned_to_user_id` null = unassigned) and the 12 most recent task events (types only, no message text) |
| `GET /api/v1/care-team` | `followups.read` | Active staff of the caller's organization (`user_id`, `full_name`, `role`, `patient_access`, `is_self`; no e-mail). With `patient_id` (patient scope enforced) `can_be_assigned` says whether the member may be assigned that patient's tasks |
| `GET /api/v1/patient-requests`, `GET/PATCH /api/v1/patient-requests/{id}` | `patient_requests.manage` | Appointment / assistance / change requests from patients |
| `/api/v1/portal/*` | `patients.read_self` (linked PATIENT) | Patient portal — see `patient-portal-api.md` |

### Geospatial population intelligence (`/api/v1/population`, BE-33)

Organization-level aggregates of the caller's organization (from the session) computed by the
backend from synthetic condition records, care gaps, screenings, follow-ups and the SDI facility
register; counts 1…`POPULATION_MIN_CELL_SIZE − 1` (default 5) and complementary cells are `null`
and listed in `suppressed`. No patient-level fields. Responses share `is_synthetic`, `as_of`,
`complete_through`, `latest_data_at`, `aggregation` (`run_id`, `status`, `finished_at`, `stale`,
`refresh_scheduled`, …), `privacy`, `disclaimer`. Details, metric definitions and thresholds:
`geospatial-population-intelligence.md`.

| Method & Path | Permission | Purpose |
|---|---|---|
| `GET /population/map` | `population.read` | Areas of one `geography` (`country`\|`state`\|`district`\|`city`\|`local_area`) with population, `metric_value` (`metric` = `population`, `new_cases`, `patients_with_condition`, `prevalence`, `trend`, `hotspot`, `open_care_gaps`, `preventive_coverage`, `care_facilities`), disease block for `condition` + `period` (`7d`\|`30d`\|`90d`\|`6m`\|`12m`) + `cohort` (`all`\|`adults`\|`children`\|`female`\|`male`), hotspot class, active alert count, care/facility figures, data quality. `bbox=minLon,minLat,maxLon,maxLat` (published facility-point extent; `excluded_without_geometry`), `sort` (`metric_desc`\|`name`), `limit` ≤ 500, `offset`. `boundary`/`reference_point` are `null` (no boundary data). Disease metric without `condition` / bad bbox → `422` |
| `GET /population/trends` | `population.read` | `condition` (required), `area_id` or `geography` (default `district`), `period`, `cohort`, pagination: current vs previous period comparisons (counts, change, prevalence, `trend.direction` `INCREASING`\|`DECREASING`\|`STABLE`\|`INSUFFICIENT_DATA` with `reason_codes`) and 12 complete calendar months. Unknown area → `404` |
| `GET /population/hotspots` | `population.read` | Threshold-based hotspots (`CRITICAL`\|`HIGH`\|`MODERATE`\|`WATCH`\|`NO_ALERT`\|`INSUFFICIENT_DATA`) at district/local level (or `geography`), `condition`, `period`, `min_classification` (default `WATCH`); each with `reason_codes`, `supporting_metrics`, `thresholds`, windows, `detected_at`, `data_freshness_at`, `statistical_significance: "not_assessed"` |
| `GET /population/areas/{area_id}` | `population.read` | Area profile: ancestors, children, population by cohort, all conditions (current, every period, series, hotspot, data quality), active alerts, facilities (association basis, counts by layer, point extent, distance/capacity unavailable), preventive care, data quality |
| `GET /population/summary` | `population.read` | Population represented, conditions monitored, areas monitored, areas with increasing recorded cases, hotspots by class, active alerts by severity, preventive-care indicators, latest aggregation time |
| `GET /population/updates` | `population.read` or `population.refresh` | Aggregation status, last aggregation, latest aggregated data time, `data_changed_since_aggregation`, `staleness_seconds`, dataset/version ids, `recommended_poll_seconds` (map 60, alerts 30, trends 300); schedules a background refresh when stale |
| `POST /population/refresh` | `population.refresh` | Run the aggregation now (`409` while one is running); audited |
| `GET /population/config` · `PATCH /population/config` | `population.read` or `population.configure` · `population.configure` | Organization thresholds (`PopulationThresholds`, unknown fields → `422`); PATCH increments `version`, is audited and refreshes |
| `GET /population/alerts` | `population.alerts.read` | Filters `condition`, `area_id`, `severity`, `status` (`NEW`\|`ACKNOWLEDGED`\|`INVESTIGATING`\|`RESOLVED`\|`DISMISSED`), `category`, `active_only`, `since`, `until`; paginated, newest detection first |
| `GET /population/alerts/{alert_id}` | `population.alerts.read` | Alert with `allowed_transitions` and append-only `history`; other organizations' alerts → `404` |
| `PATCH /population/alerts/{alert_id}` | `population.alerts.manage` | `{status, note?}`; invalid transition → `409`; actor from the session; audited (`population_alert.status_changed`) |

`EvaluationItemOut` carries `reason_detail` (the engine's own reason text recorded at evaluation time, or the generic template for the code), `input_snapshot` (de-identified inputs) and `input_snapshot_basis`: `recorded_at_evaluation` (stored with the evaluation) or `reconstructed_at_read` (legacy rows evaluated before migration 0010, rebuilt from current records and possibly different from what the engine saw). `PatientEvaluationsOut.is_persisted` is `false` only for ad-hoc recomputations.

`EvaluationItemOut` also carries `applicability` (`in_band` \| `out_of_band` \| `not_determined`: is the person inside the rule's printed age/sex band, or the pathway's programme scope when the rule has none) with `applicability_basis`, and `review_origin` (`rule` \| `record`, only for `requires_clinical_review`).

---

## 2. Example Responses

### `GET /api/v1/dashboard/summary`
```json
{
  "is_synthetic": true,
  "run_id": "SYNTH-RUN-0001",
  "evaluation_run_id": "SYNTH-EVR-000001",
  "reference_date": "2026-11-16",
  "total_patients": 550,
  "n_adults": 411,
  "n_children": 139,
  "open_care_gaps_count": 1450,
  "closed_refused_care_gaps_count": 1,
  "evaluation_status_counts": {
    "not_eligible": 19518,
    "requires_clinical_review": 3983,
    "eligible": 3691,
    "due": 1451,
    "unknown": 772,
    "completed": 151,
    "insufficient_information": 108,
    "upcoming": 26
  },
  "unknown_history_patients_count": 64,
  "review_flagged_patients_count": 39,
  "rule_review_patients_count": 550,
  "patient_status_counts": {
    "due": 384, "eligible": 61, "insufficient_information": 2,
    "unknown": 64, "requires_clinical_review": 39
  },
  "patient_status_precedence": [
    "requires_clinical_review", "overdue", "due", "upcoming", "unknown",
    "insufficient_information", "eligible", "completed", "not_eligible"
  ],
  "pathway_breakdown": {
    "ifhas": {"patients_with_history": 357, "programme_eligible_patients": 411,
              "due_or_upcoming_patients": 273, "unknown_history_patients": 54,
              "review_flagged_patients": 35, "rule_review_patients": 411,
              "open_care_gaps_count": 1334}
  },
  "rules_summary": {
    "total_rules": 54,
    "authoritative_rules": 47,
    "review_flagged_rules": 7,
    "unresolved_rules": 3,
    "total_rule_items": 249,
    "clinical_review_status": "not_reviewed"
  },
  "governance_disclaimer": "All patient records shown are 100% synthetic (`is_synthetic=true`). Clinical rules are transcribed from published DoH standards for engineering use (`clinical_review_status=not_reviewed`) and require healthcare-professional review."
}
```

Dashboard semantics (numbers above are illustrative):
- `evaluation_status_counts` counts **evaluations**; every `*_patients*` field counts **people**.
- `patient_status_counts` is mutually exclusive and sums to `total_patients`: each person is counted once, under the first status in `patient_status_precedence` among their results that are inside the rule's band (`applicability != out_of_band`) and not rule-origin reviews (`no_applicable_result` if none).
- `review_flagged_patients_count` / `pathway_breakdown.*.review_flagged_patients`: people whose **own records** need clinical review (`review_origin = record`). `rule_review_patients_count` / `rule_review_patients`: people with an in-band result under a rule that itself is unresolved or review-flagged (`review_origin = rule`). Do not present the latter as "people needing review".
- `pathway_breakdown.*`: `programme_eligible_patients` (in-band programme `eligible`, not a care need) and `due_or_upcoming_patients` (in-band `due`/`upcoming`/`overdue`) replace the former `eligible_or_due_patients`.
- `/insights/population` facts include `review_flagged_patients_count` and `rule_review_patients_count`.

### `POST /api/v1/explanations`
Request:
```json
{
  "patient_id": "SYNTH-PAT-000003",
  "rule_id": "IFHAS-PKG-CERVICAL-HPV-30-65"
}
```
Response:
```json
{
  "synthetic_patient_id": "SYNTH-PAT-000003",
  "rule_id": "IFHAS-PKG-CERVICAL-HPV-30-65",
  "rule_version": "1.0.0",
  "evaluation_status": "requires_clinical_review",
  "is_authoritative": false,
  "is_synthetic": true,
  "generation_mode": "deterministic_fallback",
  "summary_text": "Evaluation for IFHAS-PKG-CERVICAL-HPV-30-65 v1.0.0 routes to clinical review (REQUIRES_CLINICAL_REVIEW). No authoritative automated recommendation is made.",
  "why_text": "The governing rule is flagged `requires_clinical_review = true`; no automated recommendation is produced.",
  "missing_or_uncertain_text": "History availability is 'available'. Guards triggered: GUARD-RULE-REVIEW-FLAG. Open questions: OQ-IFHAS-CERVICAL-CONFLICT.",
  "rule_citation_text": "Standard for the Provision of the Periodic Comprehensive Screening Program for Adults - IFHAS — DoH/SD/ADPHC-CHS/IFHAS/V10/2025, Appendix 7, PDF p.21 (IFHAS-PKG-CERVICAL-HPV-30-65 v1.0.0)",
  "warnings": [
    "Rule IFHAS-PKG-CERVICAL-HPV-30-65 is non-authoritative (verification_status=verified); open questions: OQ-IFHAS-CERVICAL-CONFLICT.",
    "SYNTHETIC RECORD — Not clinically validated. All outputs require healthcare-professional review."
  ]
}
```

### `POST /api/v1/outreach/preview`
Request:
```json
{
  "patient_id": "SYNTH-PAT-000021",
  "rule_id": "IFHAS-PKG-MAJOR-40-64",
  "channel": "sms",
  "language": "en"
}
```
Response (blocked because contact consent was withdrawn):
```json
{
  "synthetic_patient_id": "SYNTH-PAT-000021",
  "care_gap_id": "SYNTH-GAP-000051",
  "rule_id": "IFHAS-PKG-MAJOR-40-64",
  "rule_version": "1.0.0",
  "allowed": false,
  "simulated_only": true,
  "blocked_reason": "contact_consent_withdrawn",
  "preview_message": null,
  "disclaimer": "SIMULATED OUTREACH PREVIEW ONLY — No real SMS, email, phone call, or push notification is ever sent by PulseReach."
}
```

---

## 3. Setup

- Fresh database (from `backend/`, `DATABASE_URL` set): `python -m app.db.init --seed` (migrations → official register if empty → clinical + synthetic seed if unseeded; safe to re-run). Explicit reseed: `python -m app.services.synthetic_generator.seed` (replaces the synthetic run, including follow-up history; official and clinical data are untouched; atomic).
- Docker: `docker compose --env-file .env -f infrastructure/docker-compose.yml up --build` (`db-init` runs the bootstrap once, then `backend` starts).
- The API refuses to start if the rule bundle is missing/invalid, or (in `DATA_SOURCE=db`) if the database has no matching clinical load or seeded run.
- Migrations: head is `0011` (schemas `identity` and `engagement`: accounts, organizations, memberships, sessions/tokens, assignments, patient links, audit events, follow-up tasks, patient requests). Downgrading `0011`/`0010`/`0009` refuses while it would delete recorded data (accounts, audit events, tasks, AI audit, recorded snapshots, workflow history) unless run with `alembic -x allow_data_loss=true downgrade <rev>`.
- First administrator: `python -m app.services.identity create-admin …`; synthetic demo organizations/users: `python -m app.services.identity seed-demo` (see `authentication-and-rbac.md` §8–9).
- AI: `LLM_ENABLED`, `LLM_PROVIDER` (`openai_compatible` \| `anthropic`), `LLM_MODEL`, `LLM_API_KEY`, optional `LLM_BASE_URL`, `LLM_TIMEOUT_SECONDS`.
