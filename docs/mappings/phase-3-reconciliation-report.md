# PulseReach — Phase 3, Step 4: Mapping and Canonical Design Reconciliation Report

**Date:** 2026-11-15
**Status:** **Review document. Nothing in it is approved.** It proposes; the owner, the clinical/rules owner, and the named external publishers decide.
**Scope:** review and documentation only. No YAML, loader, test, ingestion script, canonical design, ERD or existing mapping document was changed. No SQL, models, migrations or tables were created. No synthetic data was generated. Nothing was committed or pushed.

> **Approval boundary.** This report does not record any clinical, legal, governance or publisher approval. Every item marked *PROPOSED* is a recommendation awaiting a named decision-maker. Where a finding says "inferred", the inference is stated as such and is not to be stored as a source fact.

---

## 0. Method and evidence base

**Documents read:** `docs/phase-3-database-design.md` (rev 2.4), `docs/phase-3-database-design-review.md`, both ERDs, all three `docs/mappings/` documents, `docs/data-acquisition-report.md`, `data/metadata/data_quality_report.md`, `data/metadata/data_dictionary.md`, `data/README.md`, `data/reference/source_manifest.yaml`, all five clinical YAML files, `rule_loader/{loader,models,errors}.py`, `tests/test_rule_loader.py`, and the five ingestion/transformation scripts.

**Source data inspected directly (not taken from earlier reports):** all 86 `statad_api` indicator detail files (14,913 rows), the 6 relevant metadata workbooks, all 9 SDI GeoJSON layers (5,339 features), the processed facility CSV and quality report, `scad_health_tables_en.xlsx`, and the three acquisition logs.

**How checks were run:** read-only Python scripts kept in the session scratchpad (outside the repository), run with bytecode writing disabled. `git status` was clean before and after. The loader was imported and run against the real YAML to obtain rule/authority counts.

**Limits of this review**
- `pytest` is not installed in the available interpreters, so the existing test suite was **not** executed. Loader behaviour was checked by importing it and by reading the code and tests.
- The multi-dimension reconciliation in §B.3 uses a simple slice test (one dimension varied, the others held fixed). It is a screening result, not a classification.
- No source URL was re-fetched. Anything about publisher intent is marked as needing publisher confirmation.

---

## 1. Executive summary

**What was reproduced.** The counts in the Step 3 documents are accurate where they are counts: 54 rules, 47 authoritative, 30 of those 47 citing open questions, 42 non-reconciling cells of 528, 8 conditions (5 inclusion, 3 exclusion), 14 non-null licence statuses, 434 unidentified records, four projection indicators. **The errors are in the explanations and in two authority rules, not in the counts.**

**What was wrong or incomplete (most important first)**

1. **Item authority is unsafe in the mapping design (CA-2).** The existing loader never produces a child item under a non-authoritative rule, so the symptom is *not reproducible there*. But the clinical mapping (§2.10b) creates 75 `package_component` rows, 6 of which sit under the 4 verified-but-flagged packages, and gives them `is_authoritative = true` through a generated column that sees only the item's own status. This will happen in the database as designed.
2. **The 2024 projection discrepancy is not rounding (B-3).** Age-band leaves for 2024 exceed the stated total by 10,940. Every band is rounded to a multiple of 5, which can explain at most ±42.5 across 17 bands. The quality report (A4) and mapping §8.2 attribute it to disclosure rounding; the evidence does not support that. The other four projection cells (±1,000 to 3,000) *are* consistent with rounding to the nearest thousand.
3. **33 of the 42 mismatches are source zeros, not rounding or coverage (B-2).** `3465 Births by Region` reports `0` for all three regions in 1977–2009 while the emirate total is non-zero. The same pattern accounts for 297 of the multi-dimension slice mismatches in `3549`. **No regional birth split exists in the held data before 2010.**
4. **The "totals reconcile exactly" statement is too strong (B-1, B-4).** It holds for 486 of 528 testable single-dimension cells. A screening of the multi-dimension cubes, which the mapping says were "not tested", finds **479 non-reconciling slices of 4,858**.
5. **`bool()` is risky in the fail-open direction, not only the fail-closed one (CA-3).** The mapping warns that the string `"false"` becomes `True` (a safe error). It misses that `null`, `""`, `0` and an *absent key* all become `False`, so the rule silently becomes authoritative.
6. **Open-question citations are not exhaustive (CA-4).** `OQ-COMMON-AGE-CALC` is declared to affect all 54 rules but is cited by 16. 17 authoritative rules cite no question at all, yet most are IFHAS packages that the age, sex and frequency questions plainly cover. Authority must not be computed from "cites no open question".
7. **The 4868-only statement is wrong; four indicators are projections (C).** Confirmed. A fifth SCAD projection indicator (4867, by citizenship) is referenced by the extracts but not held.
8. **Provenance has five distinct gaps (D):** no SCAD API retrieval time (157 files); the SDI files say 2026-11-14 and the documents say 2026-11-15; the orphan workbook's quality-report description is wrong in two respects; acquisition logs record temporary absolute paths; and no processing timestamp exists for the one transformation.
9. **Facility mapping is sound but the design/ERD say "15" licence statuses (E).** 14 raw non-null values exist; the 15th is `NULL`. The raw `INPATIENTBEDCAPACITY` is a string and the processed layer cannot distinguish "not recorded" from null. The raw properties `Longitude`/`Latitude` are **not** an independent correction source: they carry the same defects.
10. **Conditions: both kinds are supported by storage but not by semantics (F).** `kind` is unconstrained text; the meaning of `attribute`/`required_value` for an `exclusion`, and how conditions combine, are undefined. Today this is harmless because every exclusion is non-machine-evaluable and sits in a flagged rule.

**Readiness in one line:** the **official-data** path is ready for implementation planning once the documentation corrections in §4 are accepted. The **clinical** path is ready to load *as transcription* but **not** to claim authority, and the item-authority design (CD-1) must be fixed before any model or migration is written. Details in §8.

### Finding register

| ID | Finding | Verdict | Classification | Blocks future work? |
|---|---|---|---|---|
| CA-1 | 30 of 47 authoritative rules cite open questions | **Verified** (30/47); effect depends on the question | Clinical approval required | Authoritative *evaluation*: yes. Loading: no |
| CA-2 | Child items under verified-but-flagged rules can be authoritative | **Not reproducible in loader; reproducible in mapping design (6 rows)** | Confirmed correction to documentation + Loader validation requirement | **Yes — models/migrations** |
| CA-3 | `bool()` on `requires_clinical_review` | **Verified; risk is mostly fail-open** | Loader validation requirement | Yes — clinical load |
| CA-4 | OQ citations incomplete versus `affects` | **New finding** | Loader validation requirement + Clinical approval required | Authoritative evaluation: yes |
| CA-5 | "Authoritative" ≠ approved ≠ in force | **New finding** (23 authoritative rules have no effective date) | Confirmed correction to documentation | No |
| CA-6 | `unresolved ⇒ flagged` is a DB CHECK but not a loader rule | **New finding** | Loader validation requirement | No |
| AG-1 | 42 of 528 cells do not reconcile | **Verified exactly** (33 + 5 + 4) | Mapping clarification | No |
| AG-2 | Mapping's cause table is imprecise | **Partly incorrect** | Confirmed correction to documentation | No |
| AG-3 | 2024 age bands +10,940 is "rounding" | **Not supported by the data** | Confirmed correction to documentation + External publisher clarification | No |
| AG-4 | Multi-dimension cubes "not tested" | **Tested here: 479 of 4,858 slices fail** | Mapping clarification | No |
| PR-1 | Four projection indicators | **Verified** (4866, 4868, 4869, 4870) | Confirmed correction to documentation | No |
| PR-2 | 2024 in the projection series is the base-year estimate | **New finding** | Mapping clarification | No |
| PR-3 | Projection indicator 4867 not held | **New finding** | External publisher clarification | No |
| PV-1 | No SCAD API retrieval timestamp | **Verified** (157 files) | Unresolved; safe interim representation required | Second vintage only |
| PV-2 | SDI 2026-11-14 versus manifest 2026-11-15 | **Verified** | Confirmed correction to documentation | No |
| PV-3 | Orphan `scad_health_tables_en.xlsx` | **Verified; quality-report description wrong** | Confirmed correction to documentation + External publisher clarification | 1 of 215 files |
| PV-4 | Acquisition logs hold temporary absolute paths | **New finding** | Mapping clarification | No |
| PV-5 | Retrieval, publication and processing time not cleanly separated | **Partly** | Mapping clarification | No |
| FA-1 | 15 vs 14 licence statuses | **14 non-null; 15 only if `NULL` counted** | Confirmed correction to documentation | No |
| FA-2 | Bed capacity typing and empty strings | **Verified** | Mapping clarification | No |
| FA-3 | 434 unidentified records | **Verified; all of one layer** | Unresolved; safe interim representation required | Profiles: yes (D13) |
| FA-4 | Original versus corrected coordinates | **Verified; no independent correction source** | Mapping clarification | No |
| CT-1 | Three `exclusion` conditions | **Verified** (all in one flagged rule) | Confirmed correction to documentation + Loader validation requirement | No |

---

## 2. Clinical rules — Finding A

### 2.0 Current state (reproduced)

| Fact | Value | How checked |
|---|---|---|
| Rules | **54** (IFHAS 29, Well-Child 25) | loader run |
| By `verification_status` | verified 51, reported 0, unresolved 3 | loader |
| `requires_clinical_review: true` | **7** — 3 unresolved + 4 verified-but-flagged (cervical ×2, liquid biopsy, lung) | loader + raw YAML |
| Authoritative today | **47** (IFHAS 24, Well-Child 23) | loader |
| Authoritative rules citing ≥ 1 open question | **30** | loader |
| Authoritative rules citing none | 17 | loader |
| Authoritative rules with `effective_date = null` | **23** (all Well-Child) | loader |
| `requires_clinical_review` as written in YAML | real booleans in all 54 (IFHAS 24 false / 5 true; Well-Child 23 false / 2 true) | raw YAML types |
| Items (visit rules only) | 174 = 165 verified + **9 unresolved**; all 174 sit under authoritative parents | loader |
| Open questions | 23, all `status: open` | loader |

### CA-1 — 30 of 47 authoritative rules cite open questions

**Verdict: verified.** The number is correct. The question is what it *means*.

**Finding.** The three conditions in your intended rule are not equivalent to "cites no open question". The 16 questions cited by rules fall into three different effects. Effect is a property of the **(rule, question) link**, not of the question: `OQ-IFHAS-AGE-CEILING` blocks `IFHAS-PROG-AGE-CEILING` (already `unresolved`) but is purely informational on `IFHAS-PROG-ELIG-MIN-AGE`, whose own note says "this clause alone must not be used to treat people above 75 as eligible".

**Proposed effect classes** *(PROPOSED — requires the clinical/rules owner)*

| Effect | Meaning | Consequence |
|---|---|---|
| `blocks_rule` | The rule's transcribed content is itself contested, conflicting or incomplete | Rule is non-authoritative while the question is open |
| `gates_outputs` | The rule is a faithful transcription, but specific evaluation outputs cannot be produced until answered | Rule stays authoritative as a transcription; named outputs return `requires_clinical_review` |
| `informational` | Context the user must be able to see; changes no result | Shown with the rule; blocks nothing |

**Proposed classification of every question cited by a rule**

| Question | Cited by (rules) | Proposed effect | Reasoning from the question's own text |
|---|---|---|---|
| `OQ-IFHAS-CERVICAL-CONFLICT` | 2 (both flagged) | `blocks_rule` | Appendix 7 conflicts with a later standard; which governs is unknown |
| `OQ-IFHAS-LIQUID-BIOPSY-CRITERIA` | 1 (flagged) | `blocks_rule` | Criteria not machine-evaluable; who assesses is unspecified |
| `OQ-IFHAS-LUNG-CRITERIA` | 1 (flagged) | `blocks_rule` | `and/or` logic and pack-year method externally defined, not reviewed |
| `OQ-IFHAS-AGE-CEILING` | 2 | `blocks_rule` on `IFHAS-PROG-AGE-CEILING`; `informational` on `IFHAS-PROG-ELIG-MIN-AGE` | See above |
| `OQ-COMMON-AGE-CALC` | 16 | `gates_outputs` | Boundary determinations only (e.g. age 39 y 11 m against "40–64"); needs a configured convention |
| `OQ-COMMON-SEX-ATTRIBUTE` | 1 | `gates_outputs` | Sex-specific package eligibility; missing/other value is already `insufficient_information` |
| `OQ-IFHAS-FREQUENCY-ANCHOR` | 2 | `gates_outputs` | `due` / `upcoming` / `completed` cannot be computed without an anchor |
| `OQ-IFHAS-CRC-OVERLAP` | 3 (1 flagged, 2 not) | `gates_outputs` | Whether FIT, colonoscopy, liquid biopsy are alternatives or cumulative |
| `OQ-IFHAS-AAA-SMOKING-DEFINITION` | 1 | `gates_outputs` — **owner decision, see below** | "Ever smoked" undefined, yet the condition is `machine_evaluable: true` |
| `OQ-WCV-DUE-WINDOW` | 16 (1 unresolved + 15 verified) | `gates_outputs` (`due`, `upcoming`, `overdue`) | Already enforced by the separate unresolved rule `WCV-TIMING-DUE-WINDOW` and the status-definition note |
| `OQ-WCV-MCHAT-FOLLOWUP-TIMING` | 4 | `gates_outputs` (referral deadlines) | Windows conflict; YAML preserves them unmerged |
| `OQ-WCV-REFUSAL-STATE` | 1 | `gates_outputs` | The status vocabulary has no refusal state |
| `OQ-WCV-EFFECTIVE-DATE` | 15 (1 unresolved + 14 verified) | `informational` (display is mandatory; forbids an "in force" claim) | Does not change the transcribed schedule |
| `OQ-WCV-MCHAT-REFERRAL-TARGET` | 2 | `informational` | Destination wording differs; preserved per source |
| `OQ-IFHAS-INVITATION-OWNERSHIP` | 1 | `informational` | Governance; the provider obligation is transcribed |
| `OQ-IFHAS-KPI-TARGET` | 1 | `informational` | The `>100%` KPI target is not encoded; the 15-working-day period is |

**Effect on the 30 authoritative rules under this proposal**
- **0** would be demoted by `blocks_rule` automatically.
- **28** carry at least one `gates_outputs` link (they remain authoritative transcriptions with named output gates).
- **2** carry `informational` links only (`IFHAS-WF-INVITATION-SYSTEM`, `IFHAS-WF-REFERRAL-15WD`).

**Cases that need an explicit owner decision rather than a default** *(not decided here)*
1. **`IFHAS-PKG-AAA-M-65-75`** — the only `machine_evaluable: true` condition in the corpus, resting on a term the standard does not define. Either mark the condition not machine-evaluable (which, by the mapping's own cross-table rule, flags the rule), or require an explicit recorded `smoking_history.ever_smoked` value and treat missing as `insufficient_information`.
2. **`IFHAS-PKG-FIT-40-75` and `IFHAS-PKG-COLONOSCOPY-40-75`** — `OQ-IFHAS-CRC-OVERLAP` flags liquid biopsy but not the two packages the same question covers. The inconsistency is a decision, not a defect to fix silently.
3. **`IFHAS-PROG-ELIG-SEX-BY-PACKAGE`** — a verified, unflagged gate resting on a question about what "sex" means.

**Classification:** Clinical approval required (effect classes and the three decisions); Mapping clarification (the link-level `effect`). **Blocks:** authoritative *evaluation*, not loading.

**Recommended interim representation (until approved).** Keep the current formula unchanged (it is the conservative one: it never promotes anything). Load every citation. Treat "authoritative" as "verified transcription, not flagged", and require every consumer to surface the cited open questions beside the rule. Do not describe the 30 as "clean".

### CA-2 — Child items of verified-but-flagged rules

**Verdict: not reproducible in the existing loader; reproducible in the mapping design.**

**Existing loader (evidence).**
- `RuleItem.is_authoritative` is `verification_status == "verified"` only; it has no reference to its parent (`models.py`).
- But items are produced only from `preventive_assessments`, `developmental_assessments` and `follow_up_requirements`, which exist only on the 14 Well-Child `visit_schedule` rules. All 14 are authoritative. Result: **0 authoritative items under a non-authoritative rule** (checked across all 174 items). The 9 unresolved items are correctly non-authoritative.
- The 4 verified-but-flagged packages carry `spec.components`, which the loader does **not** turn into items. So the defect is latent in the model, not active in the data.

**Mapping design (evidence).** Clinical mapping §2.10(b) creates one `rule_item` row per `spec.components` entry, with `inherited_from_rule = true`, `verification_status` copied from the rule, and `is_authoritative` generated as `verification_status = 'verified'`. For the four flagged packages:

| Package | Component rows | Rule authoritative? | Item `is_authoritative` as designed |
|---|---|---|---|
| `IFHAS-PKG-CERVICAL-PAP-25-29` | 2 | no | **true** |
| `IFHAS-PKG-CERVICAL-HPV-30-65` | 2 | no | **true** |
| `IFHAS-PKG-LIQUID-BIOPSY-40-75` | 1 | no | **true** |
| `IFHAS-PKG-LUNG-LDCT-55-75` | 1 | no | **true** |
| **Total** | **6** | | **6 rows wrongly true** |

The inheritance copies only the *status*, not the *flag*. The mapping records this as CU-11 and tells consumers to AND the two values, but a generated column named `is_authoritative` that is wrong by construction invites misuse. The same issue can arise for the 14 visit rules the day one of them is flagged.

**Required semantics** (matches your stated rule)

```
rule.is_authoritative =
      verification_status = 'verified'
  AND requires_clinical_review = false          -- explicit boolean, see CA-3
  AND NOT EXISTS open link with effect = 'blocks_rule'   -- once CA-1 is approved

item.effective_authority =
      item.verification_status = 'verified'
  AND parent_rule.is_authoritative
  AND NOT EXISTS open item-level question with effect = 'blocks_rule'
```
An item **never** becomes authoritative on its own when the parent is not. For inherited component rows, the item's status adds nothing beyond the parent's.

**Recommended design change (CD-1, PROPOSED).** Keep the item column as a record of the item's *own* status, rename it to avoid the word "authoritative" (for example `status_is_verified`), and expose effective authority through one view that joins the parent. A generated column cannot reference another table, so the AND must live in a view (or be copied at load time); either is an additive design change for the owner to approve. The clinical ERD line "items: `verification_status = 'verified'`" and the design's "Item-level authority is the item's own status" need the same correction.

**Loader requirement (LV-2).** For every item: assert `effective_authority ⇒ parent.is_authoritative`. For every rule: `is_authoritative` must be recomputed from the typed inputs and compared to the database-generated value after load.

**Classification:** Confirmed correction to documentation (design §4.2/§4.4 wording, clinical ERD) + Loader validation requirement. **Blocks:** model and migration work on `rule_item`.

### CA-3 — The loader uses `bool()` on `requires_clinical_review`

**Verdict: verified** at `loader.py`: `review = bool(raw.get("requires_clinical_review", False))`.

| YAML value | `bool()` result | Effect on authority |
|---|---|---|
| `"false"`, `"no"`, `"0"` (strings) | `True` | Safe: over-flags |
| `true` | `True` | Correct |
| `false` | `False` | Correct |
| `null`, `~`, empty value | `False` | **Fail-open: becomes authoritative** |
| `0`, `""` | `False` | **Fail-open** |
| key **absent** | `False` (default) | **Fail-open**: the key is in `OPTIONAL_RULE_KEYS` |

The mapping (CU-15) describes only the first row. The dangerous cases are the fail-open ones. All 54 current rules carry a real boolean, so nothing is wrong today. The test file contains no test for a non-boolean value.

**Required:** the key is **mandatory** on every rule; the value must satisfy `isinstance(v, bool)`; anything else is a validation error, never coerced. The same applies to `machine_evaluable`, `one_time`, `is_diagnosis`, `is_screening_result_only` and `may_drive_decisions`. The existing loader must not be the final word: the database loader's checks run *in addition*, as the mapping already states.

**Classification:** Loader validation requirement. **Blocks:** the clinical load.

### CA-4 — Question citations are incomplete relative to `affects` *(new)*

For each question, `affects` names a scope (a pathway or rule IDs). Comparing scope with citations:

| Question | Declared scope (rules) | Cited by | In scope but not cited |
|---|---|---|---|
| `OQ-COMMON-AGE-CALC` | 54 | 16 | **38** |
| `OQ-COMMON-SEX-ATTRIBUTE` | 29 | 1 | **28** |
| `OQ-IFHAS-FREQUENCY-ANCHOR` | 29 | 2 | **27** |
| `OQ-IFHAS-AGE-CEILING` | 29 | 2 | **27** |
| `OQ-IFHAS-KPI-TARGET` | 29 | 1 | 28 |
| `OQ-WCV-EFFECTIVE-DATE` | 25 | 15 | 10 |
| `OQ-WCV-DUE-WINDOW` | 25 | 16 | 9 |
| `OQ-GOV-CLINICAL-VALIDATION` | 54 | **0** | 54 |
| `OQ-WCV-HEAD-CIRC`, `-ORAL-15M`, `-MILESTONES-4-6Y` | 5 / 1 / 3 | 0 (cited on **items**, not rules) | by design |

**Consequence.** 17 authoritative rules cite no question, yet most are IFHAS recurring packages to which the age, sex and frequency questions apply. "Cites no open question" therefore does **not** mean "has no applicable open question". An authority calculation based on citations alone would give a falsely clean result for exactly those rules.

**Required.** Authority gating must resolve applicability from a rule-complete source: either (a) the loader expands pathway-level `affects` into per-rule links at load time, recording them as *derived* links distinct from cited ones, or (b) the owner completes the citations. Option (a) is mechanical and needs no clinical judgement. **Classification:** Loader validation requirement; Clinical approval required for which pathway-wide questions should apply to which rules. **Blocks:** authoritative evaluation.

### CA-5 — "Authoritative" is not approval and not "in force" *(new)*

23 authoritative rules (every authoritative Well-Child rule) have `effective_date = null`, because the standard states "Effective Date: TBD". `OQ-GOV-CLINICAL-VALIDATION` states no rule is clinically validated. The status definition for `verified` already says it "is NOT clinical validation", but the design and mapping use "authoritative" without that qualifier.

**Required documentation wording** (PROPOSED): *authoritative = a faithful, source-checked transcription of a published standard that is not flagged for review. It is not clinical approval and not confirmation that the standard is in force.* This belongs in the design glossary, the clinical ERD's authority row and any UI copy. **Classification:** Confirmed correction to documentation. **Blocks:** nothing.

### CA-6 — `unresolved ⇒ flagged` is not enforced by the loader *(new)*

The mapping adds `CHECK (verification_status <> 'unresolved' OR requires_clinical_review)`. The existing loader enforces only `unresolved ⇒ ≥ 1 question`. It holds today (all 3 unresolved rules are flagged), but a future unresolved, unflagged rule would pass the loader and fail at insert. **Required:** assert it in the loader so the failure is reported with the other issues. **Classification:** Loader validation requirement. **Blocks:** nothing.

---

## 3. Official data

### 3.B Aggregate reconciliation — Finding B

#### AG-1 — The 42 cells reproduce exactly

Population tested: single-dimension indicators with unit `People` or `Number`, per (indicator, year). **680 cells = 486 reconcile + 141 no aggregate + 11 aggregate-only + 42 mismatch.** The "528 testable" are the 486 + 42 that have both an aggregate and leaves. All three figures match the mapping.

#### AG-2 — Cause of each of the 42 cells

| Indicator | Cells | Years | Leaf sum − aggregate | Evidence | Proposed class |
|---|---|---|---|---|---|
| **3465** Births by Region | **33** | 1977–2009 | −(entire aggregate) | All three region leaves are `0.0`; aggregate 9,524 (1977) to 29,068 (2009). 2010–2024 reconcile; 2025 has no aggregate | `RC-ZERO-LEAVES` |
| **3463** Births by Citizenship | 2 | 2008, 2009 | −12, −24 | Two leaves only (Emirati, Non-Emirati); no residual member present | `RC-RESIDUAL-BELOW` |
| **3466** Births by Gender | 1 | 2009 | −10 | Female + Male only | `RC-RESIDUAL-BELOW` |
| **3502** Post-Neonatal Deaths by Region | 1 | 2022 | −1 | 51 + 0 + 26 = 77 vs 78 | `RC-RESIDUAL-BELOW` |
| **4868** Projection by Age Group | 3 | 2024, 2030, 2035 | +10,940 / −1,000 / +3,000 | 2024: see AG-3. 2030, 2035: values are multiples of 1,000, 17 leaves | 2030, 2035: `RC-PROJ-ROUNDING`; **2024: `RC-UNEXPLAINED`** |
| **4869** Projection by Gender | 1 | 2040 | +1,000 | Multiples of 1,000, 2 leaves | `RC-PROJ-ROUNDING` |
| **4870** Projection by Region | 1 | 2030 | −1,000 | Multiples of 1,000, 3 leaves | `RC-PROJ-ROUNDING` |
| **Total** | **42** | | | | 33 + 4 + 4 + **1** |

**Documentation corrections.**
- Mapping §8.2 lists "4868 / 4869 / 4870 | 2024, 2030, 2035, 2040" as one block. The real set is **5 cells**: 4868 (2024, 2030, 2035), 4869 (2040), 4870 (2030). Not every indicator fails in every year.
- Mapping and quality report call all projection cells "disclosure rounding". That holds for **4 of the 5**, not for 2024 (AG-3).
- 3465's "region leaves present with value 0.0" is correct. What the mapping leaves open is whether `0` means "no births" or "no regional data". Births cannot be zero in every region while the emirate total is 9,524, so `0` is a **placeholder for missing regional attribution**. That is an inference from arithmetic; SCAD should confirm (OP-S1).
- **Implication for Well-Child cohort work:** regional births before 2010 are not available from `3465` or `3549`. Do not build a regional child-cohort history before 2010, and do not interpret the zeros.

#### AG-3 — The 2024 age-band discrepancy is not rounding

2024 age bands (4868) sum to **4,146,925**; the stated total (and the emirate total in `3916`, `3175`, `4866`, `4869`, `4870`) is **4,135,985**: a gap of **+10,940**.

- All 17 band values are multiples of 5, so they were rounded to the nearest 5.
- Rounding 17 values to the nearest 5 changes the sum by at most 17 × 2.5 = **42.5**. The observed gap is **257 times** that.
- The stated total (4,135,985) is the same figure as the 2024 estimate in `3916`/`3175`; whether it was itself rounded cannot be told from the data.
- 4869 (gender) and 4870 (region) reconcile in 2024, so the discrepancy is specific to the age distribution.

**Conclusion.** The cause is **unknown**. Plausible candidates (not evidence): the age structure comes from a different base, vintage or adjustment than the total. Treat 2024 age-band values as a shape only, never as counts that add to the total. **Classification:** Confirmed correction to documentation (quality report A4, mapping §8.2) + External publisher clarification (OP-S2). The quality report's remark that 2024 is "evidently rounded to the nearest 5" is true of the *values* and false as an *explanation of the gap*.

#### Reconciliation classification model (PROPOSED)

Cell state is one of the four existing values. For `mismatch`, add a `mismatch_class` and keep the numbers.

| `mismatch_class` | Test (deterministic) | Meaning | Source evidence preserved | May a consumer use leaf sums? |
|---|---|---|---|---|
| `RC-ZERO-LEAVES` | every leaf is `0` and aggregate `> 0` | Leaf level is a placeholder, not an observation | zeros stored as `0` | **No** |
| `RC-PROJ-ROUNDING` | projection indicator and `abs(diff) ≤ n_leaves × step / 2` (step 1,000 for 2030+; 5 for 2024) | Consistent with publisher rounding | leaves and aggregate | Leaves only as shape; the aggregate is authoritative |
| `RC-RESIDUAL-BELOW` | `leaf_sum < aggregate`, no residual member (`Missing/Unknown`, `Not stated`, `Abroad`) among the leaves | A category is probably unlisted (dimension coverage) | leaves and aggregate | No: use the aggregate |
| `RC-LEAVES-ABOVE` | `leaf_sum > aggregate`, not a projection within tolerance | Cannot be a missing category; indicates inconsistent aggregate classification, revision or error | leaves and aggregate | No |
| `RC-UNEXPLAINED` | exceeds the tolerance for its class (e.g. the 2024 projection) | Cause unknown | leaves and aggregate | No |
| `RC-HIERARCHY` | any cell where one aggregate member is nested in another (e.g. cause-of-death `Total`) | Aggregate semantics unclear | all | No |

**Rules.** Classification is a *report*, never a correction. No source value is changed and no aggregate is rewritten to equal its leaf sum. `v_derived_total_additive` excludes every `mismatch`, as the mapping already specifies. The tolerance parameters (`step`) are loader configuration, flagged *inferred from the data*, not publisher-stated.

**What the 42 become:** 33 `RC-ZERO-LEAVES`, 4 `RC-PROJ-ROUNDING`, 4 `RC-RESIDUAL-BELOW`, 1 `RC-UNEXPLAINED`. None is `RC-LEAVES-ABOVE`.

#### AG-4 — Multi-dimension cubes *(extends the finding)*

The mapping says 2- and 3-dimension cubes "were not tested". Screened here: for each dimension, other dimensions fixed, one aggregate and ≥ 1 leaf.

| Result | Slices |
|---|---|
| Reconcile | 4,379 |
| **Do not reconcile** | **479** |
| Not testable (no single aggregate / no leaf) | 432 |
| **Tested** | 4,858 |

Of the 479: **299** have all leaves at `0` (297 are `3549` region slices for 1977–2009 = 33 years × 9 citizenship×gender combinations, the same placeholder pattern as 3465), **128** have leaves below the aggregate and **52** above. By indicator: cause-of-death cubes (2583–2586) and the small-count mortality cubes (3422, 3424, 3505), where `Missing/Unknown` and `Abroad` members matter, account for most of the rest.

**Caveat.** This is a screening test. Cause-of-death cubes have nested categories and `Not applicable` members, so some of those 128 + 52 may be `RC-HIERARCHY` rather than errors. The point is narrower: **the sentence "totals reconcile exactly on every indicator tested" (quality report §2, §9) must not be read as covering the multi-dimension cubes.**

**Classification:** Mapping clarification (the load report must classify multi-dimension slices; none is asserted to reconcile, which the mapping already says). **Blocks:** nothing.

### 3.C Projection indicators — Finding C

#### PR-1 — Verified: four projection indicators

| Indicator | Title | Dimension | Years held | Total (each year) |
|---|---|---|---|---|
| **4866** | Projection of Population | none | 2024, 2030, 2035, 2040 | 4,135,985 / 5,195,000 / 5,799,000 / 6,328,000 |
| **4868** | …by Age Group | `AGE_GROUP` | same four | identical totals |
| **4869** | …by Gender | `GENDER` | same four | identical totals |
| **4870** | …by Region of Residence | `REGION` | same four | identical totals |

**Evidence that these are projections, not observations:**
- Titles begin "Projection of Population"; the publisher's own description reads "hypothetical developments of the population size and its structure based on a set of assumptions for fertility, mortality and net migration", and the method is "Future population (year n+1) = [population (year n) + births − deaths + in-migrants − out-migrants]".
- All four report `Last data update = 20400101` in the metadata workbook: a **sentinel**, not a date (it is the last projected year). Observed indicators carry `20250101` (65) or `20240101` (2). The JSON `Metadata.updated` is a real value (2025-12-16 to 2025-12-19) and differs per indicator.
- The four totals agree with each other in every year, which confirms they are one projection set.

The design's "4868 is `projected`" is **incomplete**; mapping D-1 is confirmed. The title-regex rule `(?i)projection` correctly selects all four held indicators. The loader should assert the set equals `{4866, 4868, 4869, 4870}` and report any other match.

#### PR-2 — Time periods and implications for `observation` *(new detail)*

- **2024 is the base year, not a forecast.** The 2024 total (4,135,985) equals the observed 2024 estimate in `3916`/`3175`. 2030, 2035 and 2040 are rounded to the thousand. So "2024" appears both as an observed and as a projected figure for the same quantity.
- Series are **sparse** (four points). There is no 2025 age breakdown; do not interpolate.
- `OBS_DT` is 1 January of the year; the publisher does not say what instant a projected population refers to. Do not assert one.
- Consequences for `observation`: projections load as ordinary rows (no PK conflict, since the key includes the indicator). But **every default view that returns "observed" data must exclude `series_kind = 'projected'`**, otherwise a 2024 population figure can be double-counted across `3916` and `4866`. The 2024 projection row must never be presented as an observation. `series_kind` must be visible in `v_observation_leaf` and any export.
- 2030–2040 age bands carry the same corrupted labels as 2024 (`2026-05-09`, `2026-10-14`): the `pending` correction state applies to all four years.

**Classification:** Confirmed correction to documentation (design §3.3 "4868"); Mapping clarification (base-year overlap). **Blocks:** nothing.

#### PR-3 — A fifth projection indicator is referenced but not held *(new)*

The `relatedSV` block of 4866 lists `4867 — Projection of Population by Citizenship`. It is not among the 86 acquired indicators. The held projection set is therefore **incomplete with respect to the publisher's own set**. **Classification:** External publisher clarification (OP-S3: is 4867 intentionally excluded or unavailable?). Not blocking.

### 3.D Source provenance — Finding D

**Evidence table**

| Source group | Where a time is recorded | What it is |
|---|---|---|
| SDI GeoJSON (9 files) | `_source.retrieved` in each file, `2026-11-14T13:20:17Z` to `13:20:58Z` | **Measured retrieval time** (UTC, seconds) written by the fetch script |
| SDI log, SCAD API log, open-data log | none (script and logs contain no timestamp) | — |
| SCAD API (86 + 71 files) | none in files, logs, or `fetch_statad_indicators.py` | Only `Metadata.updated` (publisher) and the manifest's date `2026-11-15` |
| SCAD workbooks (5) | manifest `downloaded` (date) and HTTP `Last-Modified` for 4 of 5 | Publisher-side header; no retrieval time |
| `processed/facilities/` | file mtime only; `quality_report.json` has no `generated_at`; `build_facilities.py` has no version stamp | Processing time not recorded |
| Raw files (inspected: 5 SCAD workbooks, the SCAD API log and a sample indicator, the SDI log and layers) | filesystem mtime `2026-11-15 13:39` (`13:39:26` for the SCAD files, API log and indicator checked); the two pre-existing SCAD workbooks show `2026-11-14 17:27:32` | **Copy time into the repo, not retrieval time** |

#### PV-1 — SCAD API retrieval time is not recorded anywhere

**Verified.** Neither `fetch_statad_indicators.py` nor `acquisition_log.json` records a time; the log holds path, size, SHA-256, row count, title and publisher `updated`. The manifest states only `downloaded: 2026-11-15`. This is not recoverable.

**Bounds that can be stated honestly (not values):** the latest publisher `updated` in the held files is `2026-11-05`, so retrieval cannot precede it; the first commit containing the files is `2026-11-15 14:01:39 +0530`. A retrieval therefore falls between `2026-11-05` and `2026-11-15 08:31Z`. These bounds must not be written into `retrieved_at`.

#### PV-2 — SDI facility files: 2026-11-14 versus 2026-11-15

**Verified.** All nine layers carry `_source.retrieved` on **2026-11-14** (13:20Z, equal to 18:50 IST on the 14th; the 14th in every timezone from UTC−11 to UTC+10). `source_manifest.yaml` (SRC-18 `downloaded: 2026-11-15`), `data/README.md` ("retrieved 2026-11-15"), the data quality report B6 ("Cite the retrieval date (2026-11-15), recorded in each file's `_source` block") and the design's D15 text all say the 15th. B6 contradicts the very block it cites.

**Reading.** The in-file stamp is a tool measurement; the manifest date is a manually entered date that matches when the files were copied into the repo (2026-11-15 13:39 IST) and validated. The stamp is primary. **Resolution:** manifest SRC-18 and the three documents should say 2026-11-14 for retrieval; 2026-11-15 is the date they were brought into the repository. **Classification:** Confirmed correction to documentation. Mapping §3 is already right in preferring the in-file stamp.

**Additional publisher-side evidence (inferred, requires publisher confirmation).** Every SDI feature has a `CH_FID` of the form `DOH_dd_mm_yyyy#n#n`: the 434 rehabilitation records carry `DOH_15_10_2026`, the other 4,905 carry `DOH_28_10_2026`. The latest `PRELIMISSUEDATE` is 2026-10-27. This is consistent with a Department of Health extract dated 28 October 2026 and suggests two delivery batches. It is an inference from an identifier string, not a stated publication date. The catalogue's "modified 2025-07-25/28" is clearly stale against content issued in 2026 and must not be used as a vintage. **Recommendation:** record `CH_FID` verbatim (the mapping currently excludes it) as raw evidence, never as `source_effective_date`.

#### PV-3 — Orphan `scad_health_tables_en.xlsx`

**Verified:** present on disk and in `raw_checksums.sha256` (SHA-256 `d52df9c0…1503`), listed in the acquisition report and `data/README.md`, absent from `source_manifest.yaml`. No URL, content-disposition name or `Last-Modified` is recorded for it anywhere.

**The quality report's description is wrong in two respects.**

| Claim (quality report C7, data dictionary) | What the file shows |
|---|---|
| "no stated reference period" | The 30 stacked tables state their periods in their titles: the first is "Table 1: Key Health Statistics, Abu Dhabi, **2012**"; others span "2008 to 2012", "1973 to 2012", "2005 to 2012". The embedded document title is "Health Statistic 2012"; embedded created/modified are 2013-12-30 and 2014-01-29 |
| "a 2023 server timestamp" | No server timestamp is recorded for this file. `2023-11-06T19:19:55Z` is the `Last-Modified` of a *different* file, the 2022 workbook (SRC-10) |

The review (`phase-3-database-design-review.md`) already noticed the periods; the quality report and data dictionary were not corrected. In-file source lines name "Statistics Centre – Abu Dhabi" and "Health Authority – Abu Dhabi" (and "Ministry of Health (1973-2005)" for older series). This is attribution *stated in the content*; it is not a retrieval record, a URL, or a licence statement.

**Policy.** Do not invent a manifest entry, URL or timestamp. Register nothing for it (mapping §2 already reports `unmapped_file`). Its facts can be cited as "content states: 2012 edition; sources as printed". The owner supplies the origin URL and acquisition date, or removes the file. **Classification:** Confirmed correction to documentation + External publisher/owner clarification. **Blocks:** registration of 1 of 215 files only.

#### PV-4 — Acquisition logs record temporary absolute paths *(new)*

All **86** `statad_api` log entries and the metadata/file paths of the open-data log point into `/private/tmp/claude-501/…/scratchpad/dl_*` — a different session's temporary directory, not the repository. `rec["detail"]["path"]` is therefore not a stable identifier and cannot be opened. **Required:** loaders key on the repository-relative path plus SHA-256 and ignore the logged `path`. Mapping §3 should say so. **Classification:** Mapping clarification.

#### PV-5 — A consistent provenance policy (PROPOSED)

Four time concepts exist and must never be substituted for one another.

| Concept | Meaning | Where it lives | Rule |
|---|---|---|---|
| **Publication / effective** | When the *publisher* says the data or standard is valid or was issued | `source_effective_note` (text), `facility.source_effective_date` (only if explicitly stated) | Verbatim, never parsed from sentinels (`20400101`), never taken from a catalogue "modified" field, never inferred from `CH_FID` |
| **Publisher update** | Publisher-stated update time (e.g. `Metadata.updated`) | `source_effective_note` | Verbatim. Where two publisher signals disagree (workbook `20250101` versus JSON `2026-07-15` for `3916`), keep both labelled; do not choose |
| **Retrieval** | When *our tool* fetched the bytes | `source_file.retrieved_at` (UTC), set only from a tool-written stamp | `NULL` if not recorded. Never defaulted to load time, copy time, file mtime or commit time |
| **Processing / load** | When *we* transformed or loaded | `registered_at`, `rule_load.loaded_at`, load-report run time; `transform_version` | Always ours; never labelled as source time |

**Gaps in the current implementation of that policy**
1. `retrieved_at` cannot express "retrieved on 2026-11-15, time unknown" for the SCAD files, because a date is not a timestamp. **Decision D-P1 (PROPOSED):** either leave it `NULL` and keep the manifest's date as an unverified text note in the load report, or add one nullable `retrieved_on DATE` column with a `retrieved_on_basis` note. The first needs no design change; the second does. Pick one before any second vintage is loaded.
2. The one transformation records neither a time nor a version, so `transform_version` has no source. **Recommendation:** the future loader writes it; `build_facilities.py` is not to be changed under this task.
3. The documents should use "retrieved 2026-11-14 (SDI), 2026-11-15 (SCAD, date only)" rather than one date for the whole of `data/`.

**Classification:** Unresolved; safe interim representation required (retrieved_at `NULL`; claimed date shown only as such). **Blocks:** only loading a second vintage (existing OU-13).

### 3.E Facility mapping — Finding E

#### FA-1 — Licence statuses: 14 raw non-null values, not 15

Counted across all 5,339 features:

| Raw `LICENSESTATUS` | Features |
|---|---|
| Active | 3,005 |
| *(null — the 434 unidentified)* | 434 |
| Preliminary - Cancelled by Law | 368 |
| Preliminary - Active | 327 |
| About to Expire | 287 |
| Cancelled | 231 |
| Preliminary - Cancelled | 151 |
| Cancelled by Law | 147 |
| Preliminary - About to Expire | 106 |
| Preliminary - In Progress | 85 |
| Temporary Closed | 73 |
| Expired | 50 |
| Pending Cancellation | 48 |
| **Preliminary -Cancelled by Law** *(typo: missing space)* | 24 |
| Revoked | 3 |

**15 keys, one of which is null → 14 non-null raw strings.** The 15 comes from the processed `quality_report.json`, whose `license_status_counts` uses `(blank)` for the nulls. The mapping's D-3 is correct. The design (§3.4 `license_status_raw`: "15 distinct values"), ERD (`raw_value PK "15 distinct today"`, and note 8 "the 15 current values") and quality report B3 ("…and others"; it names 8 of 14) should say **14**.

- **Raw versus normalised.** Raw stays verbatim and is the FK. The typo variant is its own raw value (24 rows). A whitespace/hyphen normalisation would merge it with `Preliminary - Cancelled by Law` (13 groups from 14 raw values). **No merge is applied**; the *normalised* grouping and `is_operating` flag exist only after review (D13).
- **Why D13 matters, quantified.** For hospitals: `Active` only = 71 hospitals / 8,828 beds; `Active` + `About to Expire` = 74 / 9,326; all licences = 114 / 11,721. SCAD reports 75 hospitals / 8,082 beds. The answer to "how many hospitals" varies from 71 to 114 depending on a status choice nobody has approved. This confirms R-O4 (do not combine the sources) and that no operating-facility count can be published before D13.

**Classification:** Confirmed correction to documentation. **Blocks:** nothing; operating-facility counts depend on D13.

#### FA-2 — Bed capacity: source values and empty strings

`INPATIENTBEDCAPACITY` in the source is a **string** for all 4,905 identified features and `null` for the 434. It is not a plain integer (design and `build_facilities.py`/`quality_report.json` say it is; mapping D-11 is right).

| Source value | Count | Proposed typed projection |
|---|---|---|
| digit string `"0"` | 2,586 | `0` (source-stated zero) |
| digit string `> 0` | 111 | positive integer (**all 111 are hospitals**) |
| empty string `""` | 2,208 | `NULL` (not recorded) |
| JSON `null` | 434 | `NULL` (unidentified record) |

- **Never treat `""` as `0`.** Digit-string zero and empty string are different statements: `"0"` is asserted; `""` is silence. Every non-hospital layer has digit strings that are all `"0"`.
- Of 114 hospitals, 111 have positive capacity and 3 have `"0"`.
- The **processed CSV cannot be used for this typing:** both `""` and `null` become an empty cell (2,642 = 2,208 + 434), so the distinction is lost there. Load from the raw GeoJSON, as the mapping already specifies. `quality_report.json` ("plain integer") should be corrected.
- Licensed capacity, not operational beds; and `BEDS` (composite string) was not parsed or reconciled with `INPATIENTBEDCAPACITY` in this review.

**Classification:** Mapping clarification (document the `"0"` / `""` / `null` distinction explicitly) + Confirmed correction to documentation (design, processed report). **Blocks:** nothing.

#### FA-3 — The 434 unidentified records

**Verified:** 434 features, **all** in `rehabilitation_center`, which has exactly 434 features — **the whole layer.** Every attribute is null except `OBJECTID` (1–434), `Longitude`, `Latitude` and `CH_FID`. All 434 have a point geometry; 360 distinct coordinate pairs (74 positions are shared); 5 need the coordinate swap; none is `(0,0)`.

- There is **no identified rehabilitation facility** in the register. No count of rehabilitation facilities can be derived.
- `CH_FID` for all 434 carries the earlier batch stamp (`DOH_15_10_2026`).
- Mapping treatment (`identity_status = 'unidentified'`, all identity fields `NULL`, excluded from counts and profiles) is consistent with the data. It records "OBJECTID and coordinates kept"; **`CH_FID` is the only publisher-assigned key that survives** and it is globally unique (5,339 distinct values; `OBJECTID` repeats across layers, 1,715 distinct). The mapping excludes it.

**Recommendation (PROPOSED, design review, not a table change):** keep `CH_FID` as a raw text column. It gives the unidentified rows a stable, publisher-assigned key (so idempotent reloads do not rely on an `OBJECTID` counter that a republish may reassign), and carries the extract stamp. **Classification:** Unresolved; safe interim representation required (the mapping's representation is safe). **Blocks:** facility service profiles for these rows; they are never eligible.

#### FA-4 — Original versus corrected coordinates

| Quantity | Value |
|---|---|
| Features | 5,339 |
| `ok` | 5,299 |
| `swapped_repaired` | 31 (each is in the box *only* when swapped; none is ambiguous) |
| `missing_placeholder` (`0,0`) | 6 |
| `out_of_bounds` | 3 |

- **The raw properties `Longitude`/`Latitude` are not an independent source.** They differ from the geometry by at most 1.5 × 10⁻⁴° (about 17 m) and are *identical* for the 6 zero placeholders. They carry the same defects. They cannot be used to repair anything.
- **The processed CSV overwrites coordinates in place.** It has `longitude`, `latitude` and `geo_quality` only: the as-published pair for the 31 swapped rows and the 6 placeholders is **not** present. Originals exist only in the raw GeoJSON.
- **Typed projection.** Store the as-published pair verbatim (`source_longitude`, `source_latitude`) and the repaired pair separately, usable only when `geo_quality` is `ok` or `swapped_repaired`, exactly as mapping §9 specifies. Also keep the geometry versus property difference out of scope.
- **`VIP DOCTOR L.L.C - BRANCH OF ABU DHABI`** (`provision_health_service`, OBJECTID 334) has longitude 34.4539 and latitude 24.4539. The identical fractional digits suggest a typo for 54.4539, but this is an **inference**; it stays `out_of_bounds` and unplotted. It must not be "fixed".
- **`ok` means "inside a rectangle"** (51.0–56.5 E, 22.0–25.5 N), which also covers parts of Dubai, Sharjah, Oman and Saudi Arabia. It is not a test against the emirate's boundary and not a check of coordinate-versus-`REGION` consistency. The documentation should not describe `ok` as "inside Abu Dhabi".

**Classification:** Mapping clarification. **Blocks:** nothing.

### 3.F Clinical condition types — Finding F

#### CT-1 — Verified: 5 inclusion + 3 exclusion

| Rule | Authority | `inclusion` | `exclusion` | `machine_evaluable` |
|---|---|---|---|---|
| `IFHAS-PKG-LIQUID-BIOPSY-40-75` | verified, **flagged** | 1 (`Unwilling to have a colonoscopy or FIT`) | **3** (`Personal history of colorectal cancer.`; `Genetic disorders: Known hereditary / germline risk…`; `Inflammatory Bowel Diseases Diagnosis.`) | all `false` |
| `IFHAS-PKG-LUNG-LDCT-55-75` | verified, **flagged** | 3 | 0 | all `false` |
| `IFHAS-PKG-AAA-M-65-75` | verified, not flagged | 1 (`ever_smoked`) | 0 | `true` (with `attribute` and `required_value`) |
| 17 other packages | | `conditions: []` | | |

All 3 exclusions exist in one rule, which is non-authoritative. Nothing is discarded: the mapping loads all 8 as `rule_condition` rows.

**Do the canonical design and mapping support both kinds?**
- **Storage: yes.** `rule_condition.kind` is verbatim text with no CHECK; the mapping (§2.9) correctly records `inclusion ×5, exclusion ×3`. The loader parses conditions nowhere, so nothing in the existing loader rejects them.
- **Wording: no.** Design §4.2 says "Verbatim (`inclusion` observed)". The data contradict "observed"; the mapping logged this as C-1. It should read `inclusion` (5) and `exclusion` (3).
- **Semantics: not yet.** Four gaps are not documented anywhere:
  1. **Meaning of `attribute` + `required_value` for an exclusion.** For an inclusion it is the value that must hold. For an exclusion the same pair could mean "the value that triggers exclusion" or "the value required to avoid it". There is no machine-evaluable exclusion today, so it does not matter yet.
  2. **How conditions combine.** Liquid biopsy needs *(inclusion) AND NOT (any exclusion)*; lung uses `and/or` inside the printed text; `condition_ordinal` must not imply logic.
  3. **Absence is not "no exclusions".** 17 packages have `conditions: []`, but the later Cervical Cancer Screening Standard states exclusions (hysterectomy; over 65 with three negative tests) that Appendix 7 omits. An empty list means "none printed in Appendix 7".
  4. **No constraint on `kind`.** A typo (`exclude`, `Exclusion`) would load and then be ignored or misread by the future engine.

**Required (see §6):** loader accepts only `{inclusion, exclusion}` (reject, not warn), and rejects `machine_evaluable: true` on an `exclusion` until the owner approves the semantics. Optionally add a `CHECK (kind IN ('inclusion','exclusion'))` to the design, which is a constraint and not a table change.

**Classification:** Confirmed correction to documentation; Loader validation requirement; Clinical approval required for exclusion semantics. **Blocks:** nothing now; blocks any machine-evaluable exclusion.

---

## 4. Recommended canonical-design changes (PROPOSED; none applied)

| ID | Change | Section | Rationale | Needs |
|---|---|---|---|---|
| **CD-1** | Item authority: stop presenting `rule_item.is_authoritative` as authority. Rename to the item's own-status flag and define effective authority as `item verified AND parent rule authoritative`, via a view or a load-time copy. Correct the design's "item-level authority is the item's own status" and the clinical ERD row | §4.4, ERD | CA-2: 6 component rows would be wrongly authoritative | Owner |
| **CD-2** | Add an `effect` (`blocks_rule` / `gates_outputs` / `informational`) to each rule–question and item–question link, plus a derived/cited marker. No new table | §4.5, §4.6 | CA-1, CA-4: blocking is a property of the link | Clinical/rules owner |
| **CD-3** | Authority definition text: add the third condition (no open `blocks_rule` link) and the glossary sentence that authoritative ≠ approved ≠ in force | R-C3, glossary | CA-1, CA-5 | Owner |
| **CD-4** | `rule_condition.kind`: change "`inclusion` observed" to "`inclusion` and `exclusion`"; add `CHECK (kind IN ('inclusion','exclusion'))`; state combination and exclusion semantics once approved | §4.2 | CT-1 | Owner + clinical |
| **CD-5** | `license_status_raw` / `license_status_map`: "15" → "14 non-null raw values (15 including the null of the unidentified records)" | §3.4, ERD | FA-1 | Owner |
| **CD-6** | `series_kind`: "4868 is projected" → "4866, 4868, 4869, 4870 are projected"; state that default observed views exclude projected series | §3.3 | PR-1, PR-2 | Owner |
| **CD-7** | Reconciliation premise: replace "leaves sum to the aggregate (the quality report states they do)" with "reported and classified per `mismatch_class`; never asserted" | §3.3, §6.3 #2 | AG-1…AG-4 | Owner |
| **CD-8** | `INPATIENTBEDCAPACITY` is a string; document `"0"` vs `""` vs `null` | §3.4 | FA-2 | Owner |
| **CD-9** | Provenance: record the four time concepts of PV-5; decide D-P1 (`retrieved_on`) before any second vintage | §3.2, D15 | PV-1, PV-2, PV-5 | Owner |
| **CD-10** | Consider carrying `CH_FID` as raw text on `facility` (global key, extract stamp) | §3.4 | FA-3, PV-2 | Owner |
| **CD-11** | Document that `geo_quality = ok` means "inside the bounding rectangle", not "inside Abu Dhabi" | §3.4 | FA-4 | Owner |

None of these adds, removes or re-keys a table. CD-1, CD-2, CD-9 and CD-10 would add columns or a view and therefore need explicit approval.

---

## 5. Mapping and source-document corrections required

| ID | Document | Correction |
|---|---|---|
| **MC-1** | `official-source-to-table-mapping.md` §8.2 | The projection cells are **5**, not a 4-year block (4868 ×3, 4869 ×1, 4870 ×1). Replace "disclosure rounding" with the `mismatch_class` for each; mark the 2024 cell `RC-UNEXPLAINED` |
| **MC-2** | same §8.2, D-2 | Add the multi-dimension screening result (479 of 4,858) |
| **MC-3** | same §3, OU-13 | The SDI retrieval date is 2026-11-14; manifest/README are wrong. Add PV-4 (ignore logged `path`) |
| **MC-4** | same §9 | State `CH_FID` presence, uniqueness and batch stamps; document the raw `Longitude`/`Latitude` properties as non-independent; document "0" / "" / null for bed capacity |
| **MC-5** | same §10 | Already 14; add the status-sensitivity example (hospitals 71 / 74 / 114) |
| **MC-6** | `clinical-yaml-to-database-mapping.md` §2.10(b) and CU-11 | Items inherited from a package do not carry independent authority; replace the "AND at the consumer" caution with the view/loader assertion of CA-2 |
| **MC-7** | same §2.9 | Document `exclusion` semantics gaps (CT-1) and the absence-is-not-none rule |
| **MC-8** | same CU-10, CU-15 | Add the fail-open `bool()` table (CA-3), the `affects` coverage gap (CA-4), and the per-link effect model (CA-1) |
| **MC-9** | `data_quality_report.md` §2, §9 | "Totals reconcile exactly" → scope it to the 486 of 528 single-dimension cells and the named known-answer checks |
| **MC-10** | same A4 | The +10,940 gap is not explained by rounding to the nearest 5 |
| **MC-11** | same B3 | List all 14 raw statuses, including `Preliminary -Cancelled by Law` (24) |
| **MC-12** | same B6 | The date recorded in each file's `_source` block is 2026-11-14 |
| **MC-13** | same C7, `data_dictionary.md` line 124 | The workbook states its periods (2008–2012, 1973–2012, 2005–2012), titles it "Health Statistic 2012", and records no server timestamp |
| **MC-14** | `data/README.md` line 33, `source_manifest.yaml` SRC-18 | Retrieval 2026-11-14 |
| **MC-15** | `quality_report.json`, `build_facilities.py` docstring | `inpatient_bed_capacity` is not a "plain integer" (not changed here; scripts are out of scope) |
| **MC-16** | `data-loading-and-validation-strategy.md` §8 | The "known answers" and reconciliation rows should reference `mismatch_class` and the multi-dimension result |

---

## 6. Loader validation requirements

**Clinical loader (in addition to everything the existing loader already rejects)**

| ID | Requirement | Motivation |
|---|---|---|
| **LV-1** | `requires_clinical_review` is **mandatory** and must be a real boolean; reject `null`, `""`, `0`, strings and absence. Same for `machine_evaluable`, `one_time`, `is_diagnosis`, `is_screening_result_only` | CA-3 |
| **LV-2** | After load, recompute every rule's authority and every item's effective authority and compare with the database; assert `effective_authority ⇒ parent.is_authoritative` | CA-2 |
| **LV-3** | `verification_status = 'unresolved' ⇒ requires_clinical_review` | CA-6 |
| **LV-4** | Expand pathway-level `affects` into derived per-rule links, stored separately from cited links; report rules that cite none while in scope of an open question | CA-4 |
| **LV-5** | Once CD-2 is approved: reject a link without an `effect`; compute authority including `blocks_rule` | CA-1 |
| **LV-6** | Condition `kind ∈ {inclusion, exclusion}` (reject, not warn); reject `machine_evaluable: true` on an `exclusion`; reject `machine_evaluable: true` without `attribute` and `required_value` (tested with `is not None`, never truthiness) | CT-1 |
| **LV-7** | A rule with any `machine_evaluable: false` condition has `requires_clinical_review: true` (holds today) | existing mapping rule |
| **LV-8** | A non-null Well-Child `due_window` is accepted only if `WCV-TIMING-DUE-WINDOW` is verified and unflagged | existing mapping rule |
| **LV-9** | Assert exact counts (54 rules, 47/7 authority, 8 conditions of which 5/3, 249 items, 23 questions) and report any difference | reconciliation |

**Official-data loader**

| ID | Requirement | Motivation |
|---|---|---|
| **LV-10** | Classify every (indicator, year, dimension) cell as `reconciles` / `no_aggregate` / `aggregate_only` / `mismatch`, and every mismatch with a `mismatch_class`; never fail the load on a mismatch; never modify a value | AG-2 |
| **LV-11** | The projection set must equal `{4866, 4868, 4869, 4870}`; any additional title match is reported, not silently classified | PR-1 |
| **LV-12** | `series_kind = 'projected'` rows are excluded from every observed-data view and from derived totals | PR-2 |
| **LV-13** | Registered paths are repository-relative; the logged `path` field is ignored; every file is matched by SHA-256 | PV-4 |
| **LV-14** | `retrieved_at` is set only from a tool-written `_source.retrieved`; a manifest date is never converted to a timestamp | PV-1, PV-5 |
| **LV-15** | Licence status: assert 14 non-null raw values; any unseen value is inserted `unreviewed` and reported; the typo variant is not merged | FA-1 |
| **LV-16** | Bed capacity: digit string → integer, `""` → `NULL`, `null` → `NULL`, anything else fails; `"0"` is never confused with `""` | FA-2 |
| **LV-17** | Assert: 434 unidentified, all in `rehabilitation_center`; names, licences, status, region null together | FA-3 |
| **LV-18** | Geometry: as-published pair is stored verbatim; usable pair populated only for `ok` / `swapped_repaired`; the `out_of_bounds` set equals the three known features, and a different set blocks the load for a decision | FA-4 |

---

## 7. Outstanding questions

### 7.1 External — publishers

| ID | To | Question | Needed for |
|---|---|---|---|
| **OP-S1** | SCAD | In `3465` and `3549`, do the regional zeros for 1977–2009 mean "no births" or "regional attribution not available"? Is there a regional series before 2010? | Regional child cohort; `RC-ZERO-LEAVES` |
| **OP-S2** | SCAD | Why do the 2024 age bands in `4868` sum to 4,146,925 when the total is 4,135,985? Which is authoritative? What is the disclosure-rounding rule for projections? | `RC-UNEXPLAINED`; age-band use |
| **OP-S3** | SCAD | Is `4867` (projection by citizenship) available? Do the four held projection indicators share one scenario and vintage (their `updated` dates differ)? | Projection completeness |
| **OP-S4** | SCAD | The small residuals in 3463 (2008, 2009), 3466 (2009), 3502 (2022): is a category omitted? | `RC-RESIDUAL-BELOW` |
| **OP-S5** | SCAD | Corrupted age labels `2026-05-09` / `2026-10-14` / `2026-01-04` (existing D4); duplicate row in 3422 (existing D5) | Age bands |
| **OP-S6** | SCAD | What is the source, retrieval record and licence status of `scad_health_tables_en.xlsx`? (The file's own content names Statistics Centre – Abu Dhabi and Health Authority – Abu Dhabi.) | OU-14 |
| **OP-D1** | DoH Abu Dhabi | What does `CH_FID` encode (`DOH_dd_mm_yyyy#n#n`)? Does it indicate the extract date? Why is the whole rehabilitation layer unidentified? | Facility vintage, 434 records |
| **OP-D2** | DoH Abu Dhabi | Which `LICENSESTATUS` values denote an operating facility? What do `Preliminary - Active`, `About to Expire` and `Pending Cancellation` mean operationally? Is `Preliminary -Cancelled by Law` a typo? | D13 |
| **OP-D3** | DoH Abu Dhabi | Is `INPATIENTBEDCAPACITY = ""` "not recorded" and `"0"` "no inpatient beds"? | FA-2 |
| **OP-D4** | DoH Abu Dhabi | Is the register's actual publication date available (it states none)? | D15 |
| **OP-A1** | ADPHC (IFHAS) | Existing questions (`OQ-IFHAS-*`) plus: do the age, sex and frequency questions apply to every package? | CA-4 |

### 7.2 Clinical and rules-owner decisions

| ID | Decision | Default until decided |
|---|---|---|
| **OC-1** | Approve the three effect classes and the per-link classification in CA-1 | Formula unchanged; questions shown beside each rule; no claim of "clean" |
| **OC-2** | `IFHAS-PKG-AAA-M-65-75`: define "ever smoked", or flag, or require an explicit recorded value | Treat as unapproved; engine returns `insufficient_information` when absent |
| **OC-3** | FIT / colonoscopy flagging consistent with liquid biopsy (`OQ-IFHAS-CRC-OVERLAP`) | Unchanged |
| **OC-4** | Semantics of `exclusion` conditions and combination logic (CT-1) | No machine-evaluable exclusions accepted |
| **OC-5** | Whether `IFHAS-PROG-ELIG-SEX-BY-PACKAGE` should be gated | Unchanged |
| **OC-6** | Glossary wording for "authoritative" (CA-5) | Use the proposed wording in documentation |

### 7.3 Owner decisions (not clinical, not publisher)

**D-P1** (provenance column choice), **OU-14** (what to do with the orphan file), **D13** (licence-status review), **CD-10** (`CH_FID`).

---

## 8. Final readiness assessment

**Statement of fact.** The data and rules inspected are internally consistent with the Step 3 counts. The corrections above change *explanations, wording and four design details*; none changes the table inventory or the architecture.

| Area | Assessment | Reason |
|---|---|---|
| **Clinical rule loading as transcription** | **Ready with conditions** | Load all 54 rules and conditions after LV-1, LV-3, LV-6 are specified. All 54 values are currently well-formed |
| **Clinical `rule_item` design** | **Not ready** | CD-1 must be decided; as designed it yields 6 wrongly authoritative rows |
| **Authoritative clinical evaluation** | **Not ready** | Requires OC-1…OC-4, CD-2, CD-3, LV-4/LV-5, and the existing blockers (`OQ-WCV-DUE-WINDOW`, `OQ-COMMON-AGE-CALC`, and the others) |
| **Official indicator and observation ingestion** | **Ready with conditions** | After MC-1…MC-3, MC-9, MC-10, CD-6, CD-7. Reconciliation is reported, not asserted |
| **Official facility ingestion** | **Ready with conditions** | After CD-5, CD-8, MC-4. Operating-facility counts, service profiles and any "active facility" display remain blocked by D13 |
| **Provenance** | **Safe interim representation exists** | `retrieved_at` `NULL` for 157 SCAD files; one orphan file unregistered; D-P1 before a second vintage |

**Risks to carry forward**
1. **Clinical:** a flagged package's components being read as authoritative (CA-2); a mis-typed `requires_clinical_review` silently producing an authoritative rule (CA-3); treating "no cited question" as "no applicable question" (CA-4).
2. **Official data:** summing leaves where the aggregate is the only reliable figure (`RC-ZERO-LEAVES`, `RC-PROJ-ROUNDING`); treating the 2024 projection row as an observation; counting licences as operating facilities.
3. **Both:** presenting any figure as measured performance, any rule as approved, or any retrieval date as more precise than it is.

**Remaining blockers**
- **Hard (before models/migrations):** CD-1 (item authority).
- **Hard (before authoritative evaluation):** OC-1…OC-4, CD-2, LV-4.
- **Soft (before a second vintage):** D-P1, OU-13.
- **Soft (single file):** OU-14.
- **Domain-gated:** D13 (operating facilities); OP-S1 (regional births before 2010); OP-S2 (2024 age structure).

**Recommendation.** Review this report, decide the items in §7, approve or amend the changes in §4, and have the owner apply the documentation corrections in §5. Only then proceed to the next Phase 3 step. This review claims no approval of any of those decisions.

---

## Appendix A — Evidence for the 42 non-reconciling cells

| Indicator | Year | Aggregate | Leaf sum | Difference | Class |
|---|---|---|---|---|---|
| 3465 | 1977–2009 (33 years) | 9,524 … 29,068 | 0 | −aggregate in every year | `RC-ZERO-LEAVES` |
| 3463 | 2008 | 28,456 | 28,444 | −12 | `RC-RESIDUAL-BELOW` |
| 3463 | 2009 | 29,068 | 29,044 | −24 | `RC-RESIDUAL-BELOW` |
| 3466 | 2009 | 29,068 | 29,058 | −10 | `RC-RESIDUAL-BELOW` |
| 3502 | 2022 | 78 | 77 | −1 | `RC-RESIDUAL-BELOW` |
| 4868 | 2024 | 4,135,985 | 4,146,925 | +10,940 | `RC-UNEXPLAINED` |
| 4868 | 2030 | 5,195,000 | 5,194,000 | −1,000 | `RC-PROJ-ROUNDING` |
| 4868 | 2035 | 5,799,000 | 5,802,000 | +3,000 | `RC-PROJ-ROUNDING` |
| 4869 | 2040 | 6,328,000 | 6,329,000 | +1,000 | `RC-PROJ-ROUNDING` |
| 4870 | 2030 | 5,195,000 | 5,194,000 | −1,000 | `RC-PROJ-ROUNDING` |

For 2009, the three births cuts give three different leaf totals against one aggregate of 29,068 (regional leaves 0, citizenship 29,044, gender 29,058). The residuals differ by cut, which is consistent with a different omitted category in each; this is an observation, not a diagnosis.

## Appendix B — Files created or changed by this review

| File | Change |
|---|---|
| `docs/mappings/phase-3-reconciliation-report.md` | **Created** (this document) |

No other repository file was created, modified, deleted, staged or committed. Temporary analysis scripts were written to the session scratchpad, outside the repository.
