# PulseReach Backend API Contracts (`/api/v1`)

> **Governance & Synthetic Data Notice:**
> - Every patient record, evaluation, care gap, and outreach preview returned by `/api/v1/*` is **100% synthetic** (`is_synthetic: true`, IDs prefixed `SYNTH-<CODE>-`, Emirates IDs prefixed `SYNTH-EID-`).
> - Clinical rules are transcribed from published Abu Dhabi Department of Health (DoH) standards for engineering use (`clinical_review_status: "not_reviewed"`).
> - Eligibility, due dates, and care gaps are computed exclusively by the deterministic evaluation engine (`app.services.evaluation`), never by an LLM.
> - Missing screening history (`not_available`) always evaluates to `unknown`, never `due` or `overdue`.
> - Unresolved or review-flagged rules always evaluate to `requires_clinical_review`.
> - Outreach previews (`POST /api/v1/outreach/preview`) are **simulated only** (`simulated_only: true`) and blocked unless `contact` consent is `granted`.

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
| `GET /api/v1/patients/{patient_id}/evaluations` | All 54 deterministic rule evaluations, fired reasons/guards, rule citations, zero-PII `input_snapshot`, and care gaps | `PatientEvaluationsOut` |
| `POST /api/v1/evaluations` | Run dynamic deterministic evaluation for a synthetic patient (`patient_id`, `look_ahead_days` `0..365`) | `PatientEvaluationsOut` |
| `GET /api/v1/rules` | List/filter clinical rules (`pathway` in `ifhas\|well_child`, `verification_status` in `verified\|reported\|unresolved`, `is_authoritative`) | `PaginatedRulesOut` |
| `GET /api/v1/rules/{rule_id}` | Full rule detail, partial-date triples, items (`effective_authority`), and open questions | `RuleDetailOut` |
| `GET /api/v1/care-gaps` | Paginated evidence-backed care gaps (`patient_id`, `status`, `gap_type`, `rule_id`, `limit`, `offset`) | `PaginatedCareGapsOut` |
| `GET /api/v1/care-gaps/{gap_id}` | Single care gap detail with linked appointments, referrals, outreach events, and follow-up events | `CareGapDetailOut` |
| `POST /api/v1/care-gaps/{gap_id}/follow-ups` | Append-only follow-up event (`outreach_attempted`, `completion_documented`, `note_recorded`) with consent & evidence enforcement | `FollowUpEventOut` |
| `GET /api/v1/appointments` | Paginated synthetic appointments (`patient_id`, `care_gap_id`, `status`, `limit`, `offset`) | `PaginatedAppointmentsOut` |
| `POST /api/v1/appointments` | Schedule a synthetic appointment (`AppointmentCreateIn`) | `AppointmentOut` |
| `PATCH /api/v1/appointments/{appointment_id}` | Validated appointment status/reschedule update (`AppointmentPatchIn`) | `AppointmentOut` |
| `GET /api/v1/referrals` | Paginated synthetic referrals (`patient_id`, `status`, `limit`, `offset`) | `PaginatedReferralsOut` |
| `POST /api/v1/referrals` | Create a synthetic referral linked to screening/visit/assessment (`ReferralCreateIn`) | `ReferralOut` |
| `PATCH /api/v1/referrals/{referral_id}` | Validated referral status/date transition (`ReferralPatchIn`) | `ReferralOut` |
| `GET /api/v1/facilities` | Raw official Abu Dhabi SDI facility facts (`capability_basis: "unverified_sdi_facts_only"`, capability fields `null`) | `PaginatedFacilitiesOut` |
| `POST /api/v1/explanations` | Bounded plain-language explanation of a precomputed evaluation with deterministic fallback | `ExplanationOut` |
| `POST /api/v1/outreach/preview` | Permission-checked simulated outreach message preview (never sends real messages) | `OutreachPreviewOut` |

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

## 3. Implementation & Verification Summary

- **Schemas & Migrations (`0001`–`0008`):**
  - `official` schema (9 tables, migrations `0001`–`0005`).
  - `clinical` schema (12 tables + 2 authority views, migration `0006`).
  - `synthetic` schema (19 tables + append-only triggers with transaction-local reset guard `pulsereach.allow_synthetic_reset`; migration `0007` frozen with static DDL, migration `0008` adding append-only `synthetic.care_gap_follow_up_event`).
- **Clinical & Synthetic Pipeline:**
  - `54` clinical rules (`47` authoritative, `7` review-flagged, `3` unresolved), `249` rule items, and `23` open questions parsed from `data-pipeline/rules/*.yaml`.
  - Deterministic evaluation engine (`app.services.evaluation.engine`) derives IFHAS/Well-Child age and month bounds from YAML rule specs, enforces strict Boolean attribute/evidence checks, and never treats `declined`/`cancelled`/`expired`/`pending` referrals as completed.
  - `550` deterministic synthetic patients (seed `20261116`, `SPEC_VERSION = "2.6.0"`) with enriched background operational journeys (`T-10`), `scoring_suppressed_reason="model_not_implemented"` (no fabricated priority scores, `T-13`), and regenerated `50`-patient demo fixture (`data/synthetic/fixtures/demo_patients_50.json`).
  - Raw official Abu Dhabi SDI health facilities served by `GET /api/v1/facilities` with `capability_basis: "unverified_sdi_facts_only"` and null capability fields (`T-11`).
- **Backend Architecture, Observability & Packaging:**
  - Explicit `DATA_SOURCE=memory|db` repository parity (`app.repositories.read_repo` and `app.repositories.followup_repo`) plus `python -m app.cli.seed`.
  - `X-Request-ID` correlation middleware, PII-redacted JSON logging omitting query parameters, and `llm_enabled=False` by default (`T-16`).
  - CI workflow (`.github/workflows/ci.yml`) with PostgreSQL 16 + `TEST_DATABASE_URL`, and `backend/Dockerfile` + `infrastructure/docker-compose.yml` packaging/mounting `data-pipeline/rules` and `data/` (`T-14`, `T-17`).
- **Automated Test Verification:**
  - `data-pipeline`: `122 passed`
  - `backend`: `187 passed, 85 skipped` (PostgreSQL `@live` tests gated on `TEST_DATABASE_URL`)

