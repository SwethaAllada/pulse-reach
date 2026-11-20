# PulseReach — Synthetic Data Generation Specification

**Status: specification only. No synthetic population has been generated.**
This document defines what the generator must produce, before it is built, so that the database
schema in Phase 3 is derived from a stated contract rather than guessed.

**Version:** 0.1.0 (draft, 2026-11-14)
**Scope:** the two MVP pathways — IFHAS adult screening and Well-Child Visits.

> Every record this specification describes is **fabricated**. None of it is derived from, or
> validated against, real Abu Dhabi patient data, because no such data is available to this project
> and none will be used. Nothing here is clinically validated.

---

## 1. Non-negotiable safety rules

These come first because they constrain every table below.

### 1.1 Synthetic records must be unmistakable

| Mechanism | Rule |
|---|---|
| Identifier prefix | Every primary key begins `SYNTH-` (e.g. `SYNTH-PAT-000001`). No exceptions. |
| Emirates ID | **Never generate a structurally valid Emirates ID.** Use a `SYNTH-EID-` prefixed token that fails the real 784-YYYY-NNNNNNN-C format and its checksum. A field named `emirates_id_synthetic` holds it; the field is never named `emirates_id`. |
| Names | Drawn from an explicitly fictional pool, every record suffixed `(synthetic)` in the display name. |
| Contact details | Phone numbers from a reserved non-routable range; emails on `@example.invalid` (RFC 2606 reserved). No real address — only region plus a fictional district label. |
| Dates of birth | Generated; never a real person's. |
| Row-level marker | Every table carries `is_synthetic = true`, `generator_version`, `generation_seed`, `clinically_validated = false`. |
| File-level marker | Every output file is accompanied by a data card naming the generator version, seed, row counts and this document. |
| UI obligation | Any screen showing these records displays a persistent synthetic-data banner. Not a footnote. |

**The test:** if a single row were exported and shown without context, it must still be obvious it
is not a real patient. If that is not true of a field, that field is wrong.

### 1.2 Never fabricate clinical truth

- Eligibility, intervals and visit ages come **only** from `data-pipeline/rules/`, by `rule_id`.
  The generator reads the rules; it never restates or hard-codes a threshold.
- Where a rule is `unresolved` or `requires_clinical_review`, the generator must **not** invent the
  missing criterion. It generates the *record* and leaves the status as the rules permit —
  `unknown`, `insufficient_information` or `requires_clinical_review`.
- `overdue` must not be produced for Well-Child visits while `OQ-WCV-DUE-WINDOW` is open. Generated
  child records use the vocabulary the rules allow, and the absence of an overdue state is a
  faithful reflection of the standard, not a gap to fill.
- No prevalence figure is invented. Abnormal-result rates are **generator parameters with no
  clinical meaning**, named as such (`param_abnormal_rate_*`), documented as arbitrary, and never
  presented as epidemiology.
- NHANES may inform the *distribution shape* of a measurement value (BMI, BP, HbA1c, lipids). It
  may never set an Abu Dhabi prevalence, and any model touched by it is labelled a technical
  scaffold (Responsible AI Standard §3.1.5.1.1).
- SCAD aggregates may calibrate population *shape* only. They are never disaggregated into people.

### 1.3 Provenance

Each generated table records, per row, which `rule_id` + `rule_version` governed its creation where
a rule applies. A generated screening record that cannot name its rule is invalid.

---

## 2. Population calibration

The synthetic population's shape is anchored to real Abu Dhabi aggregates **for plausibility only**.

| Dimension | Anchor | Source | Caveat |
|---|---|---|---|
| Region split | Abu Dhabi 68% / Al Ain 24% / Al Dhafra 8% | SCAD census portal, 2024 | Context figures, not a dataset (see quality report §4) |
| Age structure | 18 five-year bands, 0-4 … 85+ | SCAD 2024 pyramid | **Band values are multiples of 5; the bands do not reconcile to the headline total (2024 gap +10,940, unexplained and not attributable to rounding — see `docs/mappings/phase-3-reconciliation-report.md` AG-3).** Shape only — never counts |
| Sex ratio | 67% male / 33% female overall | SCAD 2024 | Driven by a migrant labour force; heavily skewed in working-age bands |
| Child cohort | 39,333 live births in 2024, by region and citizenship | `raw/scad/scad_birth_statistics_2024_en.xlsx` | Only 2024 is held; a 0–6 cohort needs seven birth years (quality report B6) |
| Facility mix | 67 hospitals, 1,136 health centres, 765 clinics by region | `raw/scad/scad_health_statistics_2022_en.xlsx` | 2022 reference period; counts only, no names or coordinates |

**The sex skew matters.** A 67/33 male population is not a typical screening population: it will
distort any naive aggregate of female-specific packages (cervical, breast, mammography). The
generator must expose the demographic profile as a parameter and the dashboard must not present
synthetic coverage rates as representative.

**Recommended MVP scale:** 5,000 adults and 2,000 children — enough to exercise every rule branch
and populate a dashboard, small enough to regenerate quickly and to commit a trimmed demo fixture.

---

## 3. Entities

Eleven tables. Relationships in §4.

### 3.1 `patients`

| Field | Type | Notes |
|---|---|---|
| `patient_id` | string PK | `SYNTH-PAT-NNNNNN` |
| `emirates_id_synthetic` | string | Deliberately invalid token |
| `given_name`, `family_name` | string | Fictional pool, `(synthetic)` suffixed |
| `date_of_birth` | date | Drives all age computation |
| `sex` | enum | `male`, `female` — as the standards print it (IFHAS §4.5.3 is sex-based) |
| `nationality_group` | enum | `emirati`, `non_emirati`, `not_stated` — mirrors SCAD's own categories |
| `region` | enum | `abu_dhabi`, `al_ain`, `al_dhafra` |
| `district_label` | string | Fictional |
| `thiqa_member` | boolean / null | IFHAS §4.5.1 eligibility gate. **Null is meaningful** → `insufficient_information` |
| `preferred_language` | enum | `ar`, `en` |
| `preferred_channel` | enum | `sms`, `phone`, `email`, `app` |
| `registered_facility_id` | FK | → `facilities` |
| `date_of_death` | date / null | Must suppress outreach |
| `is_synthetic`, `generator_version`, `generation_seed`, `clinically_validated` | — | §1.1 markers |

A child patient is a `patients` row whose age falls in the WCV scope (1 month – 6 years,
`WCV-PROG-SCOPE`), linked to a guardian — not a separate table.

### 3.2 `guardians`

`guardian_id` PK, `patient_id` FK, `relationship` (`mother`/`father`/`legal_guardian`),
fictional name, contact fields, `preferred_language`, `preferred_channel`,
`consent_to_contact` (boolean). Child outreach addresses the guardian, never the child.

### 3.3 `facilities`

| Field | Type | Notes |
|---|---|---|
| `facility_id` | string PK | `SYNTH-FAC-NNNN` |
| `name` | string | Fictional, `(synthetic)` suffixed |
| `facility_type` | enum | `hospital`, `health_centre`, `clinic`, `pharmacy`, `other` — **SCAD Table 2 categories** |
| `region` | enum | Proportioned to SCAD Table 2 regional counts |
| `latitude`, `longitude` | float | **Invented.** Plausible within-region coordinates, flagged `coordinates_are_synthetic = true`. No real facility coordinates are held (quality report H6) |
| `offers_ifhas`, `offers_wcv` | boolean | Pathway capability |
| `evening_hours`, `weekend_hours` | boolean | WCV §3.9.1.1 flexible hours |

### 3.4 `screening_eligibility`

The deterministic rules engine output, materialised per patient per package. Not ML.

`eligibility_id` PK, `patient_id` FK, `rule_id` (e.g. `IFHAS-PKG-MAMMOGRAPHY-40-75`),
`rule_version`, `evaluation_status`, `reason_code`, `evaluated_at`, `next_due_date` (nullable),
`requires_clinical_review` (boolean).

`evaluation_status` uses **only** the vocabulary in `rules/common/status_definitions.yaml`:
`eligible`, `not_eligible`, `due`, `upcoming`, `overdue`, `completed`, `unknown`,
`insufficient_information`, `requires_clinical_review`.

The generator must produce records exercising every guard: missing DOB →
`insufficient_information`; missing sex → `insufficient_information`; eligible but no history →
`unknown` (never "not completed"); conflicting records → `requires_clinical_review`; any rule that
is `unresolved` or review-flagged → `requires_clinical_review`.

### 3.5 `ifhas_screenings`

| Field | Notes |
|---|---|
| `screening_id` PK, `patient_id` FK, `facility_id` FK | |
| `rule_id`, `rule_version` | The package screened, by rule |
| `package_name` | As printed in the standard |
| `scheduled_date`, `performed_date` | |
| `completion_status` | `complete`, `partial`, `not_attended`, `refused` |
| `components_completed` / `components_outstanding` | Arrays. IFHAS §4.11.4.3: an incomplete package means claims cannot be submitted — model `partial` explicitly |
| `results_communicated_date` | §4.9.2.1 — within 10 days of the initial visit |
| `journey_reported_date` | §4.11.4.3 — within 15 days |
| `has_abnormal_finding` | boolean, from `param_abnormal_rate_*` (arbitrary) |

### 3.6 `well_child_visits`

`visit_id` PK, `patient_id` FK, `guardian_id` FK, `facility_id` FK, `rule_id`
(`WCV-VISIT-01M` … `WCV-VISIT-72M`), `rule_version`, `scheduled_age_months`,
`scheduled_date`, `performed_date`, `attendance_status`
(`attended`, `not_attended`, `refused`, `catch_up`), `is_catch_up_visit`
(`WCV-POLICY-CATCHUP-ELIGIBILITY` §3.10.1.3 — a defaulter attending for catch-up vaccination
remains screening-eligible), `assessments_completed` / `assessments_outstanding`.

No `overdue` field. The standard defines visit ages, not due windows
(`WCV-TIMING-DUE-WINDOW`, `OQ-WCV-DUE-WINDOW`).

### 3.7 `assessments`

Scored instruments as structured results — the thing Synthea cannot provide.

`assessment_id` PK, `patient_id` FK, `encounter_id` FK (visit or screening),
`instrument` (`M-CHAT-R`, `IDAQ`, `PHQ-9`, `GAD-7`), `instrument_version`,
`administered_date`, `raw_score`, `item_responses` (array), `result_band`,
`rule_id`, `is_diagnosis = false` (always — these are screening results, never diagnoses),
`requires_clinical_review`.

- **M-CHAT-R** at 18 and 24 months; bands `low (0-2)`, `moderate (3-7)`, `high (8+)` per
  `WCV-MCHATR-LOW/MODERATE/HIGH`. Generate all three bands.
- **IDAQ** at 18 months, 6 items; referral when item 1 = YES or any other item = NO
  (`WCV-IDAQ-REFERRAL`).
- **PHQ-9 / GAD-7** in the IFHAS Major Package. **Scoring bands are not encoded in the rules**
  (`docs/clinical-rules.md` limitations), so the generator produces raw scores and item responses
  only, and **must not** assign a severity band.

### 3.8 `care_gaps`

The prioritisation surface. `care_gap_id` PK, `patient_id` FK, `pathway` (`ifhas`/`well_child`),
`rule_id`, `gap_type` (`never_screened`, `interval_elapsed`, `partial_completion`,
`referral_not_initiated`, `visit_not_attended`), `identified_date`, `evaluation_status`,
`priority_score` (nullable float), `priority_explanation` (string), `clinician_reviewed`
(boolean), `clinician_override` (nullable), `override_reason`.

**A care gap is produced by rules, never by a model.** The model may only order already-identified
gaps (`priority_score`), and `priority_explanation` must be populated whenever the score is
(Responsible AI Standard §3.1.6.3). Clinicians retain decision authority (§3.1.7.2.2) and overrides
are recorded (§3.1.7.2.3).

### 3.9 `appointments`

`appointment_id` PK, `patient_id` FK, `facility_id` FK, `care_gap_id` FK (nullable),
`appointment_type`, `scheduled_datetime`, `slot_type` (`weekday`, `evening`, `weekend` — WCV
§3.9.1.1), `status` (`scheduled`, `attended`, `no_show`, `cancelled_by_patient`,
`cancelled_by_facility`, `rescheduled`), `booked_via`, `reminder_count`.

### 3.10 `outreach_events`

`outreach_id` PK, `patient_id` FK, `care_gap_id` FK, `event_type` (`invitation`, `reminder`,
`recall_positive_result`, `recall_insufficient_result`, `referral_follow_up` — IFHAS §4.7.1
requires an Invitation System covering first screening, rescreening, **and recall for positive and
insufficient results**), `channel`, `sent_datetime`, `delivery_status`, `response`
(`no_response`, `booked`, `declined`, `opted_out`, `wrong_contact`), `recipient`
(`patient`/`guardian`), `suppressed` (boolean), `suppression_reason`,
`clinician_approved_by` (nullable), `message_template_id`.

Outreach generated from a model score alone, with no clinician approval, must be representable so
the human-oversight requirement can be tested (§3.1.1.2).

### 3.11 `consent_and_preferences`

A first-class state, not a flag on the patient row.

`consent_id` PK, `patient_id` FK, `consent_type` (`contact`, `data_processing`,
`ai_assisted_prioritisation`, `screening_participation`), `state` (`granted`, `withdrawn`,
`refused`, `never_requested`), `recorded_date`, `recorded_by`, `documented_in_record` (boolean),
`signature_on_file` (boolean), `refusal_reason` (nullable), `applies_to`
(`self`/`child_by_guardian`).

Required distinctions:
- **Refusal ≠ not yet done.** `WCV-POLICY-PARENTAL-REFUSAL` (§4.2.1) requires documented refusal
  with signature. A refused screening is not a care gap to chase.
- **AI opt-out is separate from contact opt-out.** Responsible AI Standard §3.1.6.1.3 gives a right
  to opt out of AI-driven services; ADHICS gives a right to object to automated processing. A
  patient may accept outreach while refusing AI prioritisation. `ai_assisted_prioritisation =
  withdrawn` must suppress scoring while leaving rule-based eligibility intact.

---

## 4. Relationships

```
facilities ──< patients >── guardians
                  │
     ┌────────────┼───────────────┬──────────────────┐
     │            │               │                  │
screening_    ifhas_        well_child_      consent_and_
eligibility   screenings      visits          preferences
     │            │               │
     │            └──────┬────────┘
     │                   │
     │              assessments
     │
  care_gaps ──< appointments
      │
      └──────< outreach_events
```

- `patients` 1─N everything. A child has 1─N `guardians`.
- `screening_eligibility` is one row per patient per applicable rule, regenerated on evaluation.
- `care_gaps` derive from `screening_eligibility`; `appointments` and `outreach_events` hang off a
  care gap so every contact traces to a rule-identified need.
- `assessments` attach polymorphically to a screening or a visit via `encounter_id`.

---

## 5. Representative scenarios

The generator must produce all of these. They are the acceptance criteria — each exercises a branch
that would otherwise go untested, and several exist specifically to prove the system behaves
honestly when it does not know something.

| # | Scenario | What it proves |
|---|---|---|
| 1 | Thiqa female, 45, no mammography on record, interval elapsed | Core adult `due` path (`IFHAS-PKG-MAMMOGRAPHY-40-75`) |
| 2 | Thiqa male, 52, Major Package completed 14 months ago | `completed` — must not appear as a gap |
| 3 | Thiqa female, 31, cervical screening due | **`requires_clinical_review`**: Appendix 7 and the Cervical Standard conflict (`OQ-IFHAS-CERVICAL-CONFLICT`) |
| 4 | Patient aged 78, otherwise eligible | **No invented rule.** `OQ-IFHAS-AGE-CEILING` is open; must surface as out-of-scope-pending-clarification |
| 5 | Patient with `thiqa_member = null` | `insufficient_information`, never "not eligible" |
| 6 | Patient with no DOB | `insufficient_information` — guard test, never an age result |
| 7 | Eligible patient, no screening history at all | `unknown`, **never "not completed"** |
| 8 | Major Package started, bloods outstanding | `partial` — IFHAS §4.11.4.3, claims cannot be submitted |
| 9 | Abnormal FIT, no referral after 15 working days | Referral-window breach (Appendix 9) |
| 10 | Results not communicated within 10 days | §4.9.2.1 breach |
| 11 | 60-year-old smoker meeting lung-criteria text | **Not machine-evaluable** (`OQ-IFHAS-LUNG-CRITERIA`) → `requires_clinical_review`, no auto-flag |
| 12 | Male, 67, ever-smoked, AAA ultrasound never done | `once_per_lifetime` frequency handling |
| 13 | Child 18 months, M-CHAT-R score 9 | High-risk band, referral within 2 weeks |
| 14 | Child 18 months, M-CHAT-R score 4 | Moderate band, 4-week referral, 1-month PHC follow-up |
| 15 | Child 18 months, M-CHAT-R 1, re-screen at 24 months | Low-risk re-screen path |
| 16 | Child 18 months, IDAQ item 1 = YES | `WCV-IDAQ-REFERRAL` |
| 17 | Child 14 months, 12-month visit not attended | Child non-attendance **without** an `overdue` status (`OQ-WCV-DUE-WINDOW`) |
| 18 | Child attending catch-up vaccination at 15 months | `WCV-POLICY-CATCHUP-ELIGIBILITY` §3.10.1.3 — still screening-eligible |
| 19 | Guardian refuses a screening, signed and documented | `WCV-POLICY-PARENTAL-REFUSAL` — distinct from "not done"; no chase |
| 20 | Patient opted out of AI prioritisation, accepts outreach | AI opt-out suppresses scoring, rules still evaluate |
| 21 | Patient withdrew contact consent | All outreach suppressed with a reason |
| 22 | Deceased patient with an open care gap | Outreach suppression |
| 23 | Wrong contact details, 3 failed invitations | Delivery-failure handling, not "declined" |
| 24 | Al Dhafra patient, nearest facility lacks the package | Capability + geography routing |
| 25 | Child 15 months, oral exam ambiguity | Item-level `unresolved` (`OQ-WCV-ORAL-15M`) blocks one item, not the visit |
| 26 | Two conflicting screening records for one patient | `requires_clinical_review` guard |
| 27 | Care gap scored by model, clinician overrides | Override + audit trail (§3.1.7.2.3) |

Scenarios 3–7, 11, 17, 19, 20, 25 and 26 all test the **same underlying property**: the system
reports what it does not know instead of guessing. That property is the submission's governance
story, so it must be demonstrable in the data, not just described in a document.

### 5.1 Condition records and geographic scenarios (BE-33)

`synthetic.condition_record` (`SYNTH-CND-*`, `is_synthetic = true`) holds problem-list entries for
type 2 diabetes, hypertension, dyslipidaemia and asthma, generated by
`backend/app/services/synthetic_generator/conditions.py` on a separate random stream seeded from
the run seed, so every record above is unchanged (except the scenario-7 local areas below) and
reseeding is idempotent (the run is replaced). Background rates are illustrative, not Abu Dhabi
prevalence. Entries carry a diagnosis date (≈3 % unknown), a later `recorded_at` (0–10 day
reporting lag), occasional duplicates from a second source, `entered_in_error` entries and resolved
asthma, so de-duplication and data-quality handling are exercised.

| # | Scenario | Construction |
|---|---|---|
| G1 | Increasing type 2 diabetes in Mussafah | 10 diagnoses in the latest 90 complete days, 1 in the previous 90 (`BE33-S1`) |
| G2 | Stable hypertension in Khalifa City | 4 diagnoses in every 90-day window for two years (`BE33-S2`) |
| G3 | Decreasing hypertension in Al Bateen | 2 vs 9 in the latest vs previous 90 days (`BE33-S3`) |
| G4 | High preventive-care gaps | Not generated: produced by the evaluation engine's real care gaps |
| G5 | Limited facility coverage | Not generated: the official SDI register lists few care facilities for Zakhir |
| G6 | Insufficient history in Al Jimi | Its record feed starts 50 days before the reference date (`BE33-S6`) |
| G7 | Missing local area | Patients with `idx ≥ 60` and `idx % 41 == 0` have `district_label = NULL` |

Windows are anchored to the reference date and the default 14-day reporting delay. Scenarios are
skipped when an area has too few eligible people (small `total_patients`). Expected dashboard
results are not stored anywhere: the backend derives every trend from these records.

---

## 6. What the generator must not do

- Must not generate a valid Emirates ID, a real name, or a routable contact detail.
- Must not assign a PHQ-9 or GAD-7 severity band (not encoded in the rules).
- Must not produce `overdue` for Well-Child visits while `OQ-WCV-DUE-WINDOW` is open.
- Must not invent an age ceiling for IFHAS (`OQ-IFHAS-AGE-CEILING`).
- Must not auto-flag lung-cancer or liquid-biopsy eligibility from the non-machine-evaluable
  criteria text.
- Must not emit a prevalence or coverage rate described as representative of Abu Dhabi.
- Must not write to `data/raw/`, and must not read clinical thresholds from anywhere but
  `data-pipeline/rules/`.

## 7. Outputs

| Path | Contents | Committed? |
|---|---|---|
| `data/synthetic/synthea/` | Raw Synthea generator output (base population) | No |
| `data/synthetic/pulsereach/` | The eleven tables above, as CSV or Parquet | No |
| `data/synthetic/fixtures/` | A trimmed demo set (~50 patients) for tests and demos | **Yes** — small and useful |
| `data/synthetic/<run>/data_card.md` | Generator version, seed, row counts, parameters, limitations, link to this spec | Yes |

The data card is required by Responsible AI Standard §3.2.5. A generated dataset without one is
incomplete.

## 8. Open items before generation

1. Confirm whether the 2025 SCAD Birth Statistics edition should replace the 2024 file.
2. Decide the 0–6 cohort construction: fetch 2019–2023 birth editions, or document a flat-cohort
   assumption (quality report B6).
3. Decide whether MOHAP geocoded facility data can be obtained from a UAE network — if so, real
   coordinates replace invented ones (manifest `SRC-13-MOHAP-OPEN-DATA`).
4. Fix the generator's demographic parameters: the real 67/33 sex skew distorts female-package
   aggregates, so decide whether the demo population mirrors it or uses a stated, labelled
   alternative.
5. Confirm the hackathon's data-use rules, which were not fully readable
   (manifest `SRC-09-FUTURE-HEALTH-CHALLENGE`).
