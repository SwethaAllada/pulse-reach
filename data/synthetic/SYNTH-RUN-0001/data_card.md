# PulseReach Synthetic Dataset Data Card — `SYNTH-RUN-0001`

> **SYNTHETIC DATA NOTICE:** Every record in this dataset is 100% fabricated (`is_synthetic = true`).
> No real personal identifiers, Emirates IDs, phone numbers, emails, or patient histories are used.
> This dataset is **not clinically validated** (`clinically_validated = false`) and does not claim
> Abu Dhabi disease prevalence or real screening programme coverage.

## 1. Provenance & Reproducibility
- **Generation Run ID:** `SYNTH-RUN-0001`
- **Evaluation Run ID:** `SYNTH-EVR-000001`
- **Generator Version:** `0.1.0`
- **Specification Version:** `2.5.0`
- **Random Seed:** `20261116`
- **Reference Date:** `2026-11-16`
- **Population Profile:** `labelled_alternative`

## 2. Row Counts Across the 18 `synthetic.*` Tables
| Table | Rows |
|---|---|
| `synthetic.generation_run` | 1 |
| `synthetic.evaluation_run` | 1 |
| `synthetic.facility_service_profile` | 3 |
| `synthetic.patient` | 550 (411 adults, 139 children) |
| `synthetic.guardian` | 139 |
| `synthetic.consent` | 9 |
| `synthetic.history_availability` | 550 |
| `synthetic.eligibility_evaluation` | 29700 |
| `synthetic.evaluation_reason` | 10413 |
| `synthetic.appointment` | 1 |
| `synthetic.ifhas_screening` | 96 |
| `synthetic.well_child_visit` | 5 |
| `synthetic.component_result` | 0 |
| `synthetic.assessment` | 4 |
| `synthetic.referral` | 1 |
| `synthetic.care_gap` | 1451 |
| `synthetic.care_gap_review` | 1 |
| `synthetic.outreach_event` | 4 |

## 3. Safety & Governance Guarantees
- Every primary key begins with `SYNTH-<CODE>-`.
- Every `emirates_id_synthetic` begins with `SYNTH-EID-` and never matches `784-...`.
- Every `family_name` ends with ` (synthetic)`.
- Missing screening history (`not_available`) evaluates to `unknown`, never `due` or `overdue`.
- Unresolved or review-flagged clinical rules evaluate to `requires_clinical_review`.
- Well-Child rules never produce `overdue` while `OQ-WCV-DUE-WINDOW` is unresolved.
