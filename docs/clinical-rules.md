# PulseReach — Clinical Rules Foundation (Phase 2)

Versioned, source-traceable rule configuration for the two MVP pathways:
**IFHAS adult screening** and **Well-Child visits**.

> **PulseReach is not clinically validated and makes no compliance claim.** The rules are a
> *transcription* of published Abu Dhabi DoH standards for engineering use. Every output
> requires review by an appropriate healthcare professional. Use synthetic data only.

## Layout

```
data-pipeline/
  rules/                      # configuration only (YAML)
    common/
      sources.yaml            # registry of source standards (name, version, ref, URL, dates)
      status_definitions.yaml # verification + evaluation statuses, guards
      open_questions.yaml     # unresolved interpretation / governance register (OQ-*)
    ifhas/ifhas_rules.yaml
    well_child/well_child_rules.yaml
  rule_loader/                # Python: load + validate only (no eligibility engine)
  tests/                      # pytest; synthetic fixtures for loader mechanics
```

Rules live in `data-pipeline/rules/`, **not** in `data/` (that folder is git-ignored and is for
generated datasets).

Run the tests: `pip install -r data-pipeline/requirements.txt && cd data-pipeline && pytest`.

## Sources and verification

| Pathway | Standard | Reference | Status |
|---|---|---|---|
| IFHAS | Standard for the Provision of the Periodic Comprehensive Screening Program for Adults – IFHAS, V10 | `DoH/SD/ADPHC-CHS/IFHAS/V10/2025` | Effective July 2025 |
| Well-Child | Standard for Well-Child Visits, V10 (Revised) | `DOH/WCV/SD/10/2025` | **Effective Date: TBD** — current published standard, *not* a confirmed in-force regulation |

Both PDFs were re-read from the official DoH URLs (see `sources.yaml`) and compared with
`docs/data-sources.md` on 2026-11-14. Page references are **PDF page indexes**. Appendix 7 contains
exactly 20 package rows (PDF pp.19–22). The later *Cervical Cancer Screening Standard*
(`DoH/SD/CHS/SCCSPPR/V1/2025`) was also checked, and it conflicts with Appendix 7 (below).

### Verification statuses

| Status | Meaning | May drive decisions? |
|---|---|---|
| `verified` | Transcribed from, and checked against, the primary standard text. **Not clinical validation.** | Yes, unless flagged `requires_clinical_review` |
| `reported` | Stated by an official body in secondary material only. Expose only as a visibly unverified, configurable parameter. | No |
| `unresolved` | Unconfirmed, conflicting or silent. | No |

Authority is **derived, never configured**: a rule is authoritative only if it is `verified`
**and** `requires_clinical_review` is false (`Rule.is_authoritative`). A config containing an
`authoritative:` key is rejected. `Rule.require_authoritative()` raises
`NonAuthoritativeRuleError`; the future engine must call it before using any rule.

## Rule structure

Every rule has these mandatory fields (validated by the loader):

`rule_id`, `pathway`, `rule_version`, `source_name`, `source_version`, `source_reference`,
`verification_status`, `effective_date`, `last_reviewed`, `description`.

Optional: `rule_type`, `effective_date_note` (**required when `effective_date` is null**),
`requires_clinical_review`, `open_question_ids`, `history`, `notes`, `spec` (type-specific payload).
Unknown keys are rejected, so typos surface as errors.

### IFHAS (`ifhas_rules.yaml`, 29 rules)

* `screening_package` ×20 — one rule per Appendix 7 row (IDs like `IFHAS-PKG-MAJOR-40-64`).
  `spec` holds `package_name`, `eligibility.age {min_years, max_years, as_printed}`,
  `eligibility.sex`, `eligibility.conditions` (verbatim inclusion/exclusion criteria, with
  `machine_evaluable`), `frequency {type, interval, as_printed}`, `one_time`, `components`.
  Age bands, sex and frequencies are exactly as printed; one-time (AAA ultrasound) is
  `once_per_lifetime`.
* `programme_eligibility` ×4 — Thiqa membership (4.5.1), 18+ (4.5.2), sex per package (4.5.3), and
  the **unresolved** age-ceiling placeholder.
* `workflow_timing` ×5 — invitation system (4.7.1), results within 10 days (4.9.2.1), journey within
  15 days (4.11.4.3), KPI reporting within 21 days (4.11.4.4), referral within 15 working days
  (Appendix 9 note).

### Well-Child (`well_child_rules.yaml`, 25 rules)

* `visit_schedule` ×14 — `WCV-VISIT-01M` … `WCV-VISIT-72M` (1, 2, 4, 6, 9, 12, 15, 18 months; 2, 2.5,
  3, 4, 5, 6 years). `spec.timing` has the recommended age (as printed + months), age band
  (sections 3.2.5–3.2.7) and `due_window: null`. Assessments are lists of items
  (`preventive_assessments`, `developmental_assessments`, `follow_up_requirements`), each with its
  **own** `source_reference` and `verification_status`; plus `history_components` and
  `counselling_elements` (from Appendix 1).
* `developmental_screening_tier` ×4 — M-CHAT-R low (0–2) / moderate (3–7) / high (8 or above)
  and the IDAQ referral rule. Outcomes are **screening results, never diagnoses**
  (`is_diagnosis: false`).
* `follow_up_window` ×2 — referral initiated within 7 days (3.9.1.3); specialist evaluation within
  2–4 weeks (3.9.1.4).
* `policy` ×2 — catch-up/defaulter eligibility (3.10.1.3), documented parental refusal (4.2.1).
* `programme_scope`, `programme_status` (Effective Date TBD), `visit_timing` (no due window) ×1 each.

## Versioning

* `rule_version` is semantic (`MAJOR.MINOR.PATCH`). `rule_id` never changes and never embeds a version.
* When a rule changes: bump `rule_version`, update `last_reviewed`, and **append the previous
  version to `history`** with its `rule_version`, `source_reference`, `verification_status`,
  `last_reviewed` and a `change_summary`. Never delete history or rewrite an old
  `source_reference`; the loader rejects incomplete history entries and a history version equal to
  the current one.
* `config_version` in each file's `config:` header tracks the file as a whole.

## Handling unresolved criteria

* Unresolved facts are **data**, not buried assumptions: an `unresolved` rule or item must cite at
  least one `open_question_ids` entry from `common/open_questions.yaml`.
* `requires_clinical_review: true` blocks authoritative use of a rule even when its transcription is
  `verified` (conflicting or ambiguous criteria). It also must cite an open question.
* Item-level `unresolved` blocks only that item (e.g. 15-month oral exam); the rest of the visit remains usable.
* The shared statuses (`status_definitions.yaml`) are distinct, with guards for the future engine:
  missing DOB → `insufficient_information` (never an age result); missing screening history →
  `unknown` (never "not completed"); conflicting records → `requires_clinical_review`; any
  non-verified or review-flagged rule → `requires_clinical_review`. `overdue` cannot be produced for
  Well-Child visits while `OQ-WCV-DUE-WINDOW` is open.

### Principal open questions (full register: `open_questions.yaml`)

| ID | Summary |
|---|---|
| OQ-IFHAS-AGE-CEILING | §4.5.2 "18 and above" vs packages ending ≤75 vs "18–75" in ADPHC comms. No rule for >75 is invented. |
| OQ-IFHAS-CERVICAL-CONFLICT | Appendix 7 (Pap q3y 25–29; HPV q5y 30–65) vs the later Cervical Standard (HPV q5y 25–65, sexually active, symptom free). Both rows flagged for review. |
| OQ-IFHAS-LUNG-CRITERIA / LIQUID-BIOPSY-CRITERIA | "and/or" logic, external pack-year method, preference-based inclusion. Not machine-evaluable. |
| OQ-IFHAS-FREQUENCY-ANCHOR, OQ-COMMON-AGE-CALC | Interval anchor, band transitions and age computation are unspecified. |
| OQ-WCV-EFFECTIVE-DATE | Effective Date TBD. |
| OQ-WCV-DUE-WINDOW | No due/grace/overdue window for any visit. |
| OQ-WCV-HEAD-CIRC, -ORAL-15M, -MILESTONES-4-6Y | Appendix 1 vs numbered sections disagree. Encoded as unresolved items. |
| OQ-WCV-MCHAT-FOLLOWUP-TIMING | M-CHAT-R 2/4 weeks vs 7-day referral initiation. Encoded as printed, not merged. |
| OQ-WCV-REFUSAL-STATE | Documented refusal must be distinct from "not done"; the requested status vocabulary has no such state. |
| OQ-GOV-DATA-RESIDENCY | **GCP Cloud Run target vs UAE data-residency requirements — needs architectural review.** |

## Adding or updating a rule

1. Read the cited section in the primary standard; do not rely on summaries.
2. Add/edit the entry in the pathway YAML with all mandatory metadata, a `source_reference` naming
   the document ref, section/appendix and PDF page, and `as_printed` wording beside any number.
3. Choose the status honestly. If the standard is silent or conflicting, use `unresolved`, add an
   `OQ-*` entry, and encode **no** threshold.
4. For an update: bump `rule_version` and move the old version into `history`.
5. Register any new source in `sources.yaml`; run `pytest`. Tests that assert transcribed values
   (Appendix 7, Appendix 1) must be updated from the source, never to fit a desired result.
6. Have a qualified healthcare professional review clinical changes before they are relied upon.

## Limitations and governance

* Not clinically validated; not compliant or certified. Both standards bind DoH-licensed providers.
* Only DoH standard content is encoded. Press-reported changes (e.g. 2025 expansion) are not adopted.
* Not encoded: referral specialist mapping (Appendix 8), KPI targets (Appendix 9; one is printed
  ">100%"), immunisation schedule (delegated to EPI circular 39/2024), PHQ-9/GAD-7 scoring,
  blood-pressure risk-condition list, vitamin D dosing.
* Evaluation must be **deterministic and traceable** to a `rule_id` + `rule_version`. No LLM may decide
  eligibility or screening frequency. Clinicians retain decision authority.
* Synthetic data only; never train on production health data.
* **Hosting:** the repository targets GCP Cloud Run, but UAE data-residency suitability is not
  established (Responsible AI Standard §3.1.4.5.1; ADHICS v2). Do not process real patient data in
  any environment until `OQ-GOV-DATA-RESIDENCY` is resolved. Deployment config is unchanged in this phase.
