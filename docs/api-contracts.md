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
> **Errors:** every error body keeps `detail` and adds `error: {status, code, message, request_id}` (`code` in `bad_request`, `not_found`, `conflict`, `validation_error`, `service_unavailable`, `internal_error`). Validation `detail` items carry only `type`, `loc`, `msg`. Database and unexpected errors never return SQL, parameters or tracebacks. Database constraint violations on writes are `409`.
>
> **Writes:** every write requires a non-blank actor (`recorded_by`, or `reviewer` for reviews).

---

## 1. Endpoint Summary

| Method & Path | Purpose | Response Schema |
|---|---|---|
| `GET /health` | Service health check | `{"status": "ok"}` |
| `GET /health/db` | Database connectivity status (`200` when connected, `503` when degraded) | `{"status": "ok" \| "degraded", "database": "connected" \| "not_configured" \| "unreachable"}` |
| `GET /api/v1/dashboard/summary` | Population, per-person status, pathway, gap, region, and clinical rule breakdowns | `DashboardSummaryOut` |
| `GET /api/v1/patients` | Paginated synthetic patient list with search (`q`), sorting (`sort_by`, `sort_dir`), and filters (`sex`, `region_id`, `pathway`, `evaluation_status`, `has_open_care_gaps`, `history_status`, `age_band`) | `PaginatedPatientsOut` |
| `GET /api/v1/patients/{patient_id}` | Single synthetic patient detail and pathway history availability | `PatientSummaryOut` |
| `GET /api/v1/patients/{patient_id}/history` | Clinical history, screenings, well-child visits, component results, assessments, and referrals | `PatientHistoryOut` |
| `GET /api/v1/patients/{patient_id}/consents` | Recorded consent history and current effective consent state | `PatientConsentsOut` |
| `GET /api/v1/patients/{patient_id}/evaluations` | All 54 deterministic rule evaluations, fired reasons/guards, rule citations, zero-PII `input_snapshot`, and care gaps. Evaluations are the unchanged historical results of `evaluation_run_id` at `reference_date`; `superseded_by_completion` / `superseded_by_care_gap_id` mark an evaluation whose care gap was later closed as `closed_completed` (the care gap holds the current state) | `PatientEvaluationsOut` |
| `POST /api/v1/evaluations` | Run dynamic deterministic evaluation for a synthetic patient (`patient_id`, `look_ahead_days` `0..365`) | `PatientEvaluationsOut` |
| `GET /api/v1/rules` | List/filter clinical rules (`pathway` in `ifhas\|well_child`, `verification_status` in `verified\|reported\|unresolved`, `is_authoritative`) | `PaginatedRulesOut` |
| `GET /api/v1/rules/{rule_id}` | Full rule detail, partial-date triples, items (`effective_authority`), and open questions | `RuleDetailOut` |
| `GET /api/v1/care-gaps` | Paginated evidence-backed care gaps (`patient_id`, `status`, `gap_type`, `rule_id`, `limit`, `offset`) | `PaginatedCareGapsOut` |
| `GET /api/v1/care-gaps/{gap_id}` | Care gap detail: closing evidence (`closed_by_ifhas_screening_id` / `_well_child_visit_id` / `_referral_id`), linked appointments, referrals, outreach events, follow-up events, `workflow_events` (appointment/referral status history), clinical `reviews`, and `recommended_pathway` (next step transcribed verbatim from the rule spec: `status` = `documented_next_step` \| `requires_clinical_review` \| `no_documented_pathway`; never inferred) | `CareGapDetailOut` |
| `GET /api/v1/care-gaps/{gap_id}/follow-ups` | Paginated follow-up timeline of the gap, newest first | `PaginatedFollowUpEventsOut` |
| `POST /api/v1/care-gaps/{gap_id}/reviews` | Record a clinical-review decision (`reviewer`, `action` = `confirmed` \| `dismissed`, `reason`). Does not change the gap status. `priority_overridden` → `422` (no priority model exists) | `CareGapReviewOut` |
| `GET /api/v1/care-gaps/{gap_id}/reviews` | Review decisions for the gap, oldest first | `CareGapReviewsOut` |
| `GET /api/v1/patients/{patient_id}/activity` | Audit trail of all follow-up and workflow events recorded for the person | `PatientActivityOut` |
| `POST /api/v1/care-gaps/{gap_id}/follow-ups` | Append-only follow-up event (`outreach_attempted`, `completion_documented`, `note_recorded`) with consent & evidence enforcement. `completion_documented` requires `close_gap=true` (and vice versa). An `outreach_attempted` with granting contact consent is stored with `outcome_status: "simulated_not_sent"` (outreach is never sent or delivered); anything else is stored as `outreach_suppressed` with the blocking reason. A missing language template does not suppress a consented attempt. `close_gap=true` requires a screening / well-child visit / referral of the same patient and the gap's rule, with completed status and valid date, on which the deterministic engine re-run with current records reports the rule `completed`/`upcoming`; otherwise `422` with a `reason_code` in `detail` (e.g. `evidence_rule_mismatch`, `evidence_not_completed`, `evaluation_requires_clinical_review`) | `FollowUpEventOut` |
| `GET /api/v1/appointments` | Paginated synthetic appointments (`patient_id`, `care_gap_id`, `status`, `limit`, `offset`) | `PaginatedAppointmentsOut` |
| `POST /api/v1/appointments` | Schedule a synthetic appointment (`AppointmentCreateIn`, `recorded_by` required). Writes a workflow event and, when `care_gap_id` is set, an `appointment_scheduled` gap event | `AppointmentOut` |
| `PATCH /api/v1/appointments/{appointment_id}` | Validated status transition (`AppointmentPatchIn`, `recorded_by` required; `scheduled_datetime` required for and only allowed with `rescheduled`). Prior status and datetime are kept in the history; `attended` never closes a gap | `AppointmentOut` |
| `GET /api/v1/appointments/{appointment_id}/history` | Append-only status history (`from_status` null on creation) | `WorkflowHistoryOut` |
| `GET /api/v1/referrals` | Paginated synthetic referrals (`patient_id`, `status`, `limit`, `offset`) | `PaginatedReferralsOut` |
| `POST /api/v1/referrals` | Create a synthetic referral linked to screening/visit/assessment (`ReferralCreateIn`, `recorded_by` required, optional `care_gap_id` of the same patient to link it to a gap) | `ReferralOut` |
| `PATCH /api/v1/referrals/{referral_id}` | Validated referral status/date transition (`ReferralPatchIn`, `recorded_by` required). Logged on every linked gap (subject gap or `care_gap_id` given at creation) | `ReferralOut` |
| `GET /api/v1/referrals/{referral_id}/history` | Append-only status history incl. initiated/completed dates | `WorkflowHistoryOut` |
| `GET /api/v1/facilities` | Official Abu Dhabi SDI facility facts with published coordinates (`latitude`, `longitude`, `geo_quality`). Filters: `region_id` (1-3), `facility_type` (case-insensitive, e.g. `Hospital`), `source_layer`, `q` (name/city). `capability_basis: "unverified_sdi_facts_only"`; capability fields are always `null` | `PaginatedFacilitiesOut` |
| `GET /api/v1/facilities/{ch_fid}` | All published SDI facts for one facility, by publisher key `ch_fid` (URL-encode it: it contains `#`) | `FacilityDetailOut` |
| `GET /api/v1/open-questions` | Open-question register (`oq_id`, `title`, `detail`, `status`, `category`, `affects`, `resolve_via`, linked `rule_ids`); filters `status`, `category`. Questions are reported, never answered | `PaginatedOpenQuestionsOut` |
| `GET /api/v1/open-questions/{oq_id}` | One open question | `OpenQuestionOut` |
| `POST /api/v1/explanations` | Plain-language explanation of a precomputed evaluation; AI-grounded when enabled, deterministic otherwise. `ai` gives `generation_mode`, `prompt_version`, `provider`, `model`, `fallback_reason`, `violations`, `audit_id` | `ExplanationOut` |
| `POST /api/v1/outreach/preview` | Permission-checked simulated outreach message preview (never sends real messages) | `OutreachPreviewOut` |
| `POST /api/v1/outreach/draft` | Same gate as the preview; when allowed, an AI-assisted (or template) simulated draft. `sendable` is always `false`; the model is never called for blocked outreach | `OutreachDraftOut` |
| `GET /api/v1/insights/population` | Aggregate facts from the dashboard plus a narrative restating them (numbers not in the facts are rejected) | `PopulationInsightOut` |
| `GET /api/v1/ai/status` | AI configuration (enabled, provider, model, prompt versions; never the key) | `AIStatusOut` |
| `GET /api/v1/ai/audit` | Recent AI generation audit records (hashes of input/output, outcome, violations, latency); `feature`, `limit` | `AIAuditOut` |

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
- AI: `LLM_ENABLED`, `LLM_PROVIDER` (`openai_compatible` \| `anthropic`), `LLM_MODEL`, `LLM_API_KEY`, optional `LLM_BASE_URL`, `LLM_TIMEOUT_SECONDS`.
