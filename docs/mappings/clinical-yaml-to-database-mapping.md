# PulseReach — `clinical` schema: YAML-to-database mapping

**Phase 3, Step 3 (design only).** No SQL, SQLAlchemy model, migration, YAML rule, rule-loader code or synthetic data was created or changed. This document specifies how the twelve `clinical` tables are populated from the YAML that is actually in `data-pipeline/rules/`.

**Date:** 2026-11-15
**Canonical design:** [`../phase-3-database-design.md`](../phase-3-database-design.md) revision 2.5 (§4, §2.3, §6.3, §8, §13). **ERD:** [`../erd/clinical-schema-erd.md`](../erd/clinical-schema-erd.md).
**Companions:** [`official-source-to-table-mapping.md`](official-source-to-table-mapping.md), [`data-loading-and-validation-strategy.md`](data-loading-and-validation-strategy.md).
**Status:** **DRAFT for review.** **Nothing in the `clinical` schema is clinically validated** (`clinical_review_status = 'not_reviewed'` in both rule files). No clinical, legal, governance or publisher approval is claimed. **D2 is provisional (clinical approval required); D6, D7, D11 are recommendations awaiting owner confirmation (not approved); D10, D14, D17 are open.** The standards' PDFs are **not held** locally (manifest: `blocked` for SRC-02 and SRC-03), so no `source_reference` page number can be re-checked from this repository.
**Revision (Phase 3, Step 4):** corrected per the reconciliation report (MC-6, MC-7, MC-8 and the owner-approved CD-1, CD-3, CD-4): parent-aware item authority, exclusion-condition gaps, the fail-open `bool()` table, the `affects` coverage gap and the proposed per-link effect model. **CD-2 and OC-1 … OC-5 are not approved and nothing here records a clinical approval; no YAML, loader or test was changed.**

> **Governing rules (restated from the task and design R-C1…R-C7).**
> 1. **YAML is the single source of truth.** The database is a loaded, hash-verified, append-only *copy*. This mapping defines **no** rule content: every value below is copied or mechanically derived from YAML. There is no database authoring path.
> 2. **`is_authoritative` is derived, never configured.** `rule.is_authoritative = (verification_status = 'verified' AND NOT requires_clinical_review)`; `rule_item.status_is_verified = (verification_status = 'verified')` records the item's **own status only and is not authority**; an item's **effective authority** is `status_is_verified AND parent rule.is_authoritative`, exposed by the view `v_rule_item_effective_authority` (CD-1, MC-6). Both columns are generated; the loader never names them in an `INSERT`, and rejects an `authoritative:` key in YAML. **"Authoritative" means a faithful, source-checked transcription of a published standard that is not flagged for review — not clinical approval and not confirmation that the standard is in force** (design R-C8).
> 3. **Nothing is invented to fit a column**: no effective date, no threshold, no due window, no score range, no code. Absence stays `NULL`/empty and is explained.

---

## 0. What was inspected

| Input | How |
|---|---|
| `docs/phase-3-database-design.md` (§4 in full, §2.3, §6.3, §8 D2/D10/D11/D14/D16/D17), `docs/erd/clinical-schema-erd.md` | Read |
| `data-pipeline/rules/common/sources.yaml`, `status_definitions.yaml`, `open_questions.yaml` | Read in full |
| `data-pipeline/rules/ifhas/ifhas_rules.yaml`, `well_child/well_child_rules.yaml` | **Parsed and profiled in full** (54 rules); representative rules of every `rule_type` read in full |
| `data-pipeline/rule_loader/models.py`, `loader.py`, `errors.py` | Read in full (the loader is **not** modified) |
| `data-pipeline/tests/conftest.py`, `test_rule_loader.py` | Skimmed (35 test functions); **not re-run** in this step |
| `data/reference/source_manifest.yaml` (SRC-02, SRC-03) | Read |

"Verified" below = recomputed from the YAML in this step.

---

## 1. YAML sources and their structure

| File | `config_version` | Top level | Feeds |
|---|---|---|---|
| `rules/common/sources.yaml` | **none** (no version key) | `sources[]` (2) | `standard` |
| `rules/common/status_definitions.yaml` | `1.0.0` | `config_version`, `last_reviewed`, `verification_statuses[]` (3), `evaluation_statuses[]` (9), `reason_codes[]` (9 strings), `guards[]` (7), `deterministic_evaluation_policy` | `verification_status`, `evaluation_status`, `reason_code`, `guard` |
| `rules/common/open_questions.yaml` | `1.0.0` | `config_version`, `last_reviewed`, `questions[]` (23) | `open_question` |
| `rules/ifhas/ifhas_rules.yaml` | `1.0.0` (`config.config_version`) | `config{pathway, config_version, clinical_review_status, disclaimer}`, `rules[]` (29) | `rule`, `rule_condition`, `rule_item`, associations |
| `rules/well_child/well_child_rules.yaml` | `1.0.0` | `config{pathway, config_version, clinical_review_status, publication_status, effective_date_as_printed, disclaimer}`, `rules[]` (25) | idem |

**Rule mapping keys (all 54 rules, verified):** `rule_id, pathway, rule_type, rule_version, source_name, source_version, source_reference, verification_status, effective_date, last_reviewed, description, requires_clinical_review, open_question_ids, history, notes, spec` (+ `effective_date_note` on all 25 Well-Child rules). Rule types: IFHAS — `screening_package` 20, `programme_eligibility` 4, `workflow_timing` 5; Well-Child — `visit_schedule` 14, `developmental_screening_tier` 4, `follow_up_window` 2, `policy` 2, `programme_scope` 1, `programme_status` 1, `visit_timing` 1. All `rule_version = 1.0.0`, all `last_reviewed = 2026-11-14`. Authority today: **47 authoritative / 7 not** (IFHAS 24 verified+clean, 4 verified+flagged, 1 unresolved; Well-Child 23 verified+clean, 2 unresolved).

**Relationship to the existing loader.** `rule_loader.load_rules()` is the **validation authority** (collects every problem, raises `RuleConfigError`). Its frozen dataclasses deliberately drop things the database needs verbatim: the raw rule mapping's `history` as given, `effective_date` typing, `notes`, and every non-`sources` key of `sources.yaml` entries (`publisher`, `revision_date`, `pdf_pages`, `contact`, `status_note`), plus `sources_in_conflict` on open questions, `resolution`/`resolved_on`, and the `config` block. Therefore the database loader (a future task) must: **(1)** call `load_rules()` first and abort on `RuleConfigError`; **(2)** re-read the same five YAML files raw; **(3)** assert that rule ids, versions, item codes, open-question ids and counts match the validated bundle — it adds *projections and checks*, never a second definition; **(4)** write. The existing loader is **not** modified by this task.

---

## 2. Table mappings

Conventions: YAML paths use `a.b[i]` (0-based) in prose and 1-based where an ordinal is stored. "Verbatim" = value exactly as the YAML parser returns it (folded `>-` scalars arrive as one line). Date-like YAML scalars that the parser turns into `date` objects (unquoted `YYYY-MM-DD`) are rendered back to ISO text (`_text()` in the existing loader); `YYYY-MM` is a string already.

### 2.1 `clinical.standard`

**Source:** `sources.yaml → sources[]` (2 rows: IFHAS V10, Well-Child V10). Natural unique keys `(source_name, source_version)` and `document_ref`.

| Destination | YAML path | Conversion | Null / missing |
|---|---|---|---|
| `standard_id` | — | `SMALLINT` identity | — |
| `source_name` | `source_name` | verbatim | required |
| `source_version` | `source_version` | verbatim (`V10` ×2) | required |
| `document_ref` | `document_ref` | verbatim; UNIQUE | required |
| `publisher` | `publisher` | verbatim | required |
| `publication_date_text` / `_precision` / `_from` | `publication_date` | partial-date triple (§3.1): IFHAS `2025-07` → text `2025-07`, `month`, `from NULL`; WCV `2025-12` → `month` | `NULL`/`unknown` only if the key is null (neither is) |
| `effective_date_text` / `_precision` / `_from` | `effective_date` | triple. IFHAS `2025-07` → `month`. **WCV: YAML `null`** → text `NULL`, precision `unknown`, from `NULL` | WCV `NULL` — **never** `'TBD'` in a date column |
| `effective_date_note` | `effective_date_note` | verbatim. WCV: "The standard states 'Effective Date: TBD'. Treat as the current published standard, NOT as a confirmed in-force regulation." IFHAS: `null` | **mandatory when precision = `unknown`** (CHECK + loader) |
| `revision_date_text` | `revision_date` | verbatim (`2028-07`, `2029-12`) — text only, no precision/from columns by design | `NULL` if absent |
| `pdf_pages` | `pdf_pages` | `SMALLINT` (24, 32) | `NULL` |
| `url`, `contact`, `status_note` | same-named | verbatim | `NULL` |
| `manifest_source_id` | **manifest**, not this YAML | find the manifest source whose `document_reference` **equals** `document_ref` (`DoH/SD/ADPHC-CHS/IFHAS/V10/2025` → `SRC-02-IFHAS`; `DOH/WCV/SD/10/2025` → `SRC-03-WCV`; both exact matches, verified). Do **not** match on version (manifest SRC-03 says `V10 (Revised)`, `sources.yaml` says `V10`) | `NULL` + report if no match. **Soft reference, no FK** (§2.1 of the design) |
| `acquisition_state` | manifest `acquisition.state` of that source | `blocked` ×2 today; CHECK `IN ('blocked','document_obtained')` — **any other manifest state fails the load** | required |
| `local_copy_sha256` | — | `NULL`; may be set only with `acquisition_state = 'document_obtained'` (CHECK). `data/reference/doh_standards/` is empty | `NULL` |

**Keys / uniqueness.** PK `standard_id`; `UNIQUE (source_name, source_version)`; `UNIQUE (document_ref)`. **Idempotency:** `standard` is a *registry*, upserted by `document_ref`; a changed value with an unchanged `document_ref` is a YAML edit — allowed, reported, and recorded by the new `rule_load` (the table is small and the rules' own `source_reference` text is the citation that matters).
**Validation.** *Loader:* both `(source_name, source_version)` pairs are referenced by ≥ 1 rule; every rule's pair resolves (existing loader does this); manifest cross-check (`blocked` for both); partial-date regex. *DB:* the §2.3 triple CHECKs, `acquisition_state` CHECK, `local_copy_sha256` CHECK, UNIQUEs. *Manual/external:* the document itself — **not held**; page numbers and the "effective date TBD" status can only be re-confirmed by fetching the PDFs from a UAE network (manifest `manual_instructions`).

### 2.2 `clinical.rule_load`

One row per **successful** execution of the loader (a failed load writes nothing to `clinical`; see CU-13).

| Destination | Source | Rule |
|---|---|---|
| `load_id` | — | identity |
| `loaded_at` | clock | `now()` (UTC) |
| `loader_version` | loader constant | TEXT |
| `bundle_sha256` | the five YAML files | SHA-256 of the text `"<relative_path>\t<sha256-of-file-bytes>\n"` for the five files, **sorted by path** (so comment/whitespace edits change the bundle hash but not any `content_sha256`) |
| `file_hashes` | same | JSONB `{relative_path: sha256}` for the five files |
| `config_versions` | each file | JSONB `{"ifhas": "1.0.0", "well_child": "1.0.0", "status_definitions": "1.0.0", "open_questions": "1.0.0"}`. **`sources.yaml` has no `config_version`** — the design's "config_version of … files" cannot include it; its hash is in `file_hashes` (discrepancy C-3) |
| `git_commit` | `git rev-parse HEAD` | `NULL` if the working tree is dirty (any uncommitted change) |
| `clinical_review_status` | `config.clinical_review_status` of both rule files | verbatim; **the two files must agree** (one column) — a mismatch fails the load. Today `not_reviewed` |
| `rules_loaded` | count | 54 |
| `rules_added` | count | rule versions newly inserted in this run (54 on the first load, 0 on an identical re-run) |

### 2.3 `clinical.verification_status`

**Source:** `status_definitions.yaml → verification_statuses[]` (3). Lookup table, not an enum.

| Destination | YAML | Note |
|---|---|---|
| `code` (PK) | `id` | `verified`, `reported`, `unresolved` — must equal the loader's `ALLOWED_VERIFICATION_STATUSES` (existing loader asserts) |
| `definition` | `definition` | verbatim. *"verified … is NOT clinical validation"* is part of the text and is kept |
| `may_drive_decisions` | `may_drive_decisions` | `true` / `false` / `false`; must be a real boolean |

### 2.4 `clinical.evaluation_status`

**Source:** `evaluation_statuses[]` (9; **no `refused`, and none may be added — D2**).

| Destination | YAML | Rule |
|---|---|---|
| `code` (PK) | `id` | `eligible, not_eligible, due, upcoming, overdue, completed, unknown, insufficient_information, requires_clinical_review` — must equal the loader's `EVALUATION_STATUSES` |
| `definition` | `definition` | verbatim |
| `requires_text` | `requires` | present on `due`, `upcoming`, `overdue` only; absent → `NULL` |
| `never_inferred_from` | `never_inferred_from` | `TEXT[]` verbatim (present on `eligible`, `not_eligible`, `due`, `completed`); **absent → `NULL`** (= none stated; not an empty array) |
| `sort_order` | — | **derived**: 1-based position in the YAML list. Not a YAML field and has **no clinical meaning**; document it as such |

**Content with no column** (kept only in YAML; see CU-7): the per-status `note` on `overdue`, `unknown`, `insufficient_information`, and the file-level `deterministic_evaluation_policy`, `last_reviewed`. The `overdue` note is the statement that **`overdue` cannot be produced for Well-Child visits until `OQ-WCV-DUE-WINDOW` is resolved**; the relational copy does not carry it.

### 2.5 `clinical.reason_code`

**Source:** `reason_codes[]` (9 plain strings). `code` ← the string verbatim; `description` ← **`NULL`** (the YAML lists codes only — a description is never invented). Observed: `rule_reported_not_verified` exists but **no guard emits it** (CU-6).

### 2.6 `clinical.guard`

**Source:** `guards[]` (7).

| Destination | YAML | Rule |
|---|---|---|
| `guard_id` (PK) | `id` | `GUARD-MISSING-DOB`, `-MISSING-ATTRIBUTE`, `-MISSING-HISTORY`, `-CONFLICTING-RECORDS`, `-RULE-NOT-VERIFIED`, `-RULE-REVIEW-FLAG`, `-ITEM-UNRESOLVED` |
| `when_text` | `when` | verbatim |
| `result_status` | `result` | FK → `evaluation_status.code`; **must exist** |
| `reason_code` | `reason_code` | FK → `reason_code.code`; **must exist** |
| `note` | `note` | only `GUARD-CONFLICTING-RECORDS` has one; else `NULL` |

**No precedence is stored and none may be inferred from list order (D17).** The YAML's "guards take precedence over any status-specific logic" concerns guards vs statuses, not guards among themselves. All 7 guards carry both `result` and `reason_code`, so the FKs are `NOT NULL` in practice (ERD §9 #2 — nullability not stated in the design; confirm, CU-18).
**Semantics preserved verbatim (not interpreted):** missing DOB / attribute → `insufficient_information`; **eligibility established but history missing → `unknown`, never "not completed"** (`GUARD-MISSING-HISTORY`; also in `completed`'s and `due`'s `never_inferred_from`); conflicting records → `requires_clinical_review`; a non-`verified` rule, a flagged rule, an unresolved item → `requires_clinical_review`. These are data the engine reads; the **database enforces none of them** (R-C6).

**Lookup-table versioning.** The four vocabulary tables are **replaced, not appended**, and only when `status_definitions.yaml → config_version` changed since the previous load (read from the latest `rule_load.config_versions`). If the content differs but `config_version` did not, the load **fails** ("edited without a version bump"). A code still referenced (by `rule`, `guard`, or later `synthetic`) cannot be removed (`ON DELETE RESTRICT`).

### 2.7 `clinical.open_question`

**Source:** `open_questions.yaml → questions[]` (23: 19 interpretation, 2 governance, 1 data-model, 1 architecture; **all `status: open`** — verified).

| Destination | YAML | Rule |
|---|---|---|
| `oq_id` (PK) | `id` | unique (existing loader checks) |
| `category`, `status` | `category`, `status` | plain `TEXT`, YAML-owned vocabularies. **Loader validation:** `status = 'resolved'` ⇒ `resolution` and `resolved_on` present; `open` ⇒ both absent |
| `title`, `detail` | same | verbatim, required |
| `affects_raw` | `affects` | `TEXT[]` **verbatim and heterogeneous** — pathways (`ifhas`, `well_child`), rule ids (e.g. `IFHAS-PKG-LUNG-LDCT-55-75`), or `architecture`. **Never used as an FK and never used to derive association rows** |
| `resolve_via` | `resolve_via` | verbatim (present on all 23) |
| `resolution`, `resolved_on` | `resolution`, `resolved_on` | **absent today → `NULL`**; `resolved_on` is a `DATE` and requires `resolution` (CHECK) |
| `first_load_id` | — | the load that first inserted the id |
| `last_changed_load_id` | — | updated **only if any mapped column differs**; otherwise unchanged |

`sources_in_conflict` (present on `OQ-IFHAS-AGE-CEILING`) has **no column** (CU-7); the same conflict list is also in `spec.sources_in_conflict` of rule `IFHAS-PROG-AGE-CEILING`, which *is* kept verbatim.
**Upsert, not append** (design): current state, not evidence. Rules cite rule *versions*, not questions. A question removed from the YAML but referenced by an association row fails the load (RESTRICT). Editing a question's text without bumping `open_questions.yaml → config_version` is **reported** (not failed) because the file's own header says a resolution is recorded in place.
**Four questions are referenced by no rule or item** (verified): `OQ-IFHAS-EXPANSION-2025`, `OQ-WCV-CCHD-VISIT`, `OQ-GOV-DATA-RESIDENCY`, `OQ-GOV-CLINICAL-VALIDATION`. They load normally; the absence of association rows is correct, not an error.

### 2.8 `clinical.rule`

**Source:** each element of `rules[]` in the two rule files (29 + 25). PK `(rule_id, rule_version)`; rows are inserted once and never updated.

| Destination | YAML path | Conversion | Null / invalid |
|---|---|---|---|
| `rule_id` | `rule_id` | verbatim; unique across **both** files (existing loader) | required |
| `rule_version` | `rule_version` | verbatim text; `CHECK ~ '^\d+\.\d+\.\d+$'` | required. **Never** compared as text (`1.10.0 < 1.9.0`) |
| `ver_major/minor/patch` | — | generated from `rule_version` | never written |
| `pathway` | `pathway` | `ifhas` / `well_child`; **must equal** the file's pathway and `config.pathway` | required |
| `rule_type` | `rule_type` | verbatim, not CHECKed (YAML-extensible); 10 observed | `NULL` allowed (none today) |
| `standard_id` | `source_name` + `source_version` | resolve to `standard`; unresolved ⇒ reject | required |
| `source_reference` | `source_reference` | verbatim (document, section/appendix, PDF page) | required |
| `verification_status` | `verification_status` | FK; `verified`/`reported`/`unresolved` | required |
| `requires_clinical_review` | `requires_clinical_review` | **must be a real YAML boolean.** The existing loader does `bool(raw.get(...))`, so the string `"false"` would become `True` — the database loader must reject every non-boolean (CU-15): `"false"`/`"no"`/`"0"` become `True` (over-flags, safe), but **`null`, empty, `0`, `""` and an absent key become `False` — fail-open, the rule silently becomes authoritative** | **mandatory, no default** (the existing loader defaults an absent key to `false`; the database loader must not) | only if the key is absent (it is present on all 54) |
| `is_authoritative` | — | **generated** `verification_status = 'verified' AND NOT requires_clinical_review` | never written |
| `effective_date_text` / `_precision` / `_from` / `_note` | `effective_date`, `effective_date_note` | §3.1 triple. **IFHAS: `2025-07` → `month` (all 29). Well-Child: `null` ×25 → `unknown` with the mandatory note** (the same text on all 25) | note mandatory when `unknown` |
| `last_reviewed` | `last_reviewed` | `DATE`, strict `YYYY-MM-DD` (`2026-11-14`) | required |
| `description` | `description` | verbatim | required |
| `notes` | `notes` | verbatim | `NULL` (23 of 54) |
| `spec` | `spec` | **JSONB, the verbatim parsed mapping** (all nested keys incl. `as_printed`, `timing`, items, `engine_handling`, `sources_in_conflict`) | key absent/null ⇒ `{}` and a report `spec_absent` (none today) |
| `history` | `history` | JSONB verbatim; **`[]` is stored as `[]` (54 of 54), not `NULL`**; `NULL` only if the key is absent | — |
| `content_sha256` | whole rule mapping | §3.3 | required |
| `yaml_path` | file | repo-relative path of the YAML file | required |
| `load_id` | — | the load that first inserted this version | required |
| *projections* | `spec.*` | §2.8.1 | `NULL` unless the type defines them |

**Rejection conditions (database loader, in addition to everything the existing loader already rejects — see §6):** unknown top-level key (typo), **`authoritative`** key, missing mandatory metadata, non-boolean `requires_clinical_review`, `unresolved` without an open question, `requires_clinical_review` without an open question, version not semver, `last_reviewed` not a real date, `effective_date` not `YYYY-MM-DD`/`YYYY-MM`/`null`, null `effective_date` without a note.

#### 2.8.1 Typed projections (convenience copies; R-C4)

Each projection is **asserted equal to `spec`** by a load test, and **must be `NULL` for any rule type that does not define it**.

| `rule_type` (count) | Column ← YAML path | Notes |
|---|---|---|
| `screening_package` (20) | `package_name` ← `spec.package_name`; `package_group` ← `spec.package_group`; `age_min_years` ← `spec.eligibility.age.min_years`; `age_max_years` ← `…max_years`; `age_as_printed` ← `…as_printed`; `sexes` ← `spec.eligibility.sex` (order kept); `frequency_type` ← `spec.frequency.type`; `interval_value` ← `spec.frequency.interval.value`; `interval_unit` ← `…interval.unit` | `once_per_lifetime` (`IFHAS-PKG-AAA-M-65-75`) has `interval: null` → both interval columns `NULL`. Assert `spec.one_time == (frequency_type = 'once_per_lifetime')`. Boundary semantics of the printed band are **unresolved (`OQ-COMMON-AGE-CALC`)** — the integers are the printed numbers, not a clinical interpretation |
| `visit_schedule` (14) | `visit_number` ← `spec.visit_number`; `visit_id` ← `spec.visit_id`; `recommended_age_months` ← `spec.timing.recommended_age.value`; `age_band` ← `spec.timing.age_band` | **Assert `recommended_age.unit == 'months'`** (all 14 are; a different unit fails rather than converting silently). `spec.timing.due_window` is `null` in all 14 and **is not projected** |
| `developmental_screening_tier` (4) | `instrument` ← `spec.instrument`; `score_min` ← `spec.score.min`; `score_max` ← `spec.score.max` | M-CHAT-R LOW 0–2, MODERATE 3–7, HIGH **8–`null` (open: "8 or above")**. **`WCV-IDAQ-REFERRAL` has no `score` key** → `score_min` and `score_max` both `NULL`. Because `score_max NULL` means "open", the loader asserts **`score_min IS NULL ⇒ score_max IS NULL`** so "no score range" and "open upper bound" stay distinguishable (CU-9). Tier rules are screening-result tiers, not diagnoses: assert `spec.is_diagnosis == false` and `spec.is_screening_result_only == true` |
| `workflow_timing` (5), `follow_up_window` (2) | `timing_value` ← `spec.timing.value`; `timing_unit` ← `spec.timing.unit`; `timing_reference_event` ← `spec.timing.reference_event` | Verbatim units: `days`, **`working_days`** (`IFHAS-WF-REFERRAL-15WD`; computing a deadline needs the unresolved calendar, D12 — no weekend/holiday assumption is made). `IFHAS-WF-INVITATION-SYSTEM` has no `timing` → all three `NULL`. **`WCV-FU-SPECIALIST-EVALUATION-2-4W` has a *range* (`min_value 2`, `max_value 4`, `unit weeks`, `reference_event null`) and no `value` → the whole group stays `NULL`** and the range lives only in `spec` (CU-8). Deadlines are computed by the engine from these; they are not stored on referrals |
| `programme_eligibility` (4) | `gate_attribute` ← `spec.attribute` | `thiqa_member`, `age_years`, `sex`; **`NULL` for `IFHAS-PROG-AGE-CEILING`** (its spec has no `attribute`). `spec.required_value`, `min_years: 18`, `max_years: null` stay in `spec` only (the age projection columns belong to packages) |
| `programme_scope`, `programme_status`, `visit_timing`, `policy` | none | `WCV-PROG-SCOPE`'s age range is 1 **month** – 6 years and cannot be stored in the `*_years` columns; it stays in `spec` |

### 2.9 `clinical.rule_condition`

**Source:** `spec.eligibility.conditions[]` of `screening_package` rules. **Verified: 8 rows over 3 rules** — `IFHAS-PKG-LIQUID-BIOPSY-40-75` (4), `IFHAS-PKG-LUNG-LDCT-55-75` (3), `IFHAS-PKG-AAA-M-65-75` (1); the other 17 packages have `conditions: []` (no rows). The existing loader **does not validate conditions at all**, so these checks are new.

| Destination | YAML | Rule |
|---|---|---|
| `rule_id`, `rule_version` | parent | composite FK |
| `condition_ordinal` | position | **1-based** position in the list |
| `kind` | `kind` | verbatim. **Observed: `inclusion` ×5 and `exclusion` ×3** (design wording corrected in rev 2.5, C-1). **`CHECK (kind IN ('inclusion','exclusion'))`** (CD-4); the loader **rejects** (not warns) any other value, e.g. `exclude`, `Exclusion` |
| `as_printed` | `as_printed` | verbatim (including stray spacing, e.g. `"…one additional risk factor ."`) |
| `machine_evaluable` | `machine_evaluable` | **real boolean required**. 7 `false`, 1 `true` |
| `attribute` | `attribute` | `NULL` when absent; e.g. `smoking_history.ever_smoked` (AAA only) |
| `required_value` | `required_value` | JSONB; `true` for AAA; `NULL` when absent |

**Checks.** `CHECK (NOT machine_evaluable OR (attribute IS NOT NULL AND required_value IS NOT NULL))` — **test `is not None`, never truthiness** (`required_value: false` is a valid value). **Cross-table loader validation (and deferred trigger, design §6.3 #3):** a rule with any `machine_evaluable = false` condition has `requires_clinical_review = true` (holds today: LIQUID-BIOPSY and LUNG-LDCT are flagged). Lung (`OQ-IFHAS-LUNG-CRITERIA`: pack-years, cessation, shisha/dokha) and liquid-biopsy criteria stay free text, **never machine-flagged**. Smoking/risk criteria here are **inclusion/exclusion conditions of a package**, not risk scores.

**Counts and where the exclusions are (CT-1).** `IFHAS-PKG-LIQUID-BIOPSY-40-75` (verified, **flagged**): 1 `inclusion` (`Unwilling to have a colonoscopy or FIT`) + **3 `exclusion`** (`Personal history of colorectal cancer.`; `Genetic disorders: Known hereditary / germline risk…`; `Inflammatory Bowel Diseases Diagnosis.`), all `machine_evaluable: false`. `IFHAS-PKG-LUNG-LDCT-55-75` (verified, flagged): 3 `inclusion`, all `false`. `IFHAS-PKG-AAA-M-65-75` (verified, not flagged): 1 `inclusion` (`ever_smoked`), `machine_evaluable: true`. All 3 exclusions sit in one rule that is not authoritative. All 8 load as rows; nothing is discarded.

**Exclusion semantics are not defined and are pending clinical approval (MC-7; OC-4).** Storage and validation support both kinds; **evaluation semantics are not approved and must not be assumed:** (1) for an `exclusion`, whether `attribute` + `required_value` means the value that *triggers* exclusion or the value *required to avoid* it is undefined (irrelevant today — no exclusion is machine-evaluable); (2) how conditions combine is undefined — liquid biopsy reads *inclusion AND NOT (any exclusion)*, lung uses `and/or` inside the printed text, and **`condition_ordinal` is a position, not logic**; (3) **absence is not "no exclusions"**: 17 packages have `conditions: []`, but the later Cervical Cancer Screening Standard states exclusions (hysterectomy; over 65 with three negative tests) that Appendix 7 omits, so an empty list means *none printed in Appendix 7*. Until approved the loader **rejects `machine_evaluable: true` on an `exclusion`** (LV-6), so no machine-evaluable exclusion can be loaded.

### 2.10 `clinical.rule_item`

Two sources feed one table, distinguished by `category`. Verified total: **249 rows = 174 Well-Child + 75 IFHAS**.

**(a) Well-Child assessment/follow-up items** — `spec.preventive_assessments[]`, `spec.developmental_assessments[]`, `spec.follow_up_requirements[]` of the 14 `visit_schedule` rules (the same three keys the existing loader's `ITEM_LIST_KEYS` parses). **Verified: 103 / 31 / 40 = 174; 21 distinct codes; 165 `verified`, 9 `unresolved`.**

| Destination | YAML | Rule |
|---|---|---|
| `category` | list key | `preventive_assessments` / `developmental_assessments` / `follow_up_requirements` |
| `code` | `code` | verbatim; PK part. Unique within `(rule, category)` and (verified) not reused across categories within a visit |
| `code_origin` | — | `'yaml'` |
| `text_verbatim` | — | `NULL` (only required for derived slugs) |
| `ordinal` | position | 1-based within its list |
| `description` | `description` | verbatim |
| `source_reference` | `source_reference` | verbatim |
| `inherited_from_rule` | — | `false` |
| `verification_status` | `verification_status` | FK. The item's **own** status; it does **not** by itself make the item authoritative |
| `status_is_verified` | — | generated `verification_status = 'verified'`. **Own status only — not authority** (renamed from `is_authoritative`, CD-1). Effective authority is in the view (below) |
| `condition_text` | `condition` | verbatim (7 items) |
| `components_text` | `components` | `TEXT[]` verbatim (28 items) |
| `rule_refs` | `rule_refs` | `TEXT[]` verbatim (17 items, e.g. `WCV-FU-REFERRAL-INITIATION-7D`). **Soft reference** to a `rule_id`; validated against the bundle, **no FK** (it names no version) |
| `notes` | `notes` | verbatim (17 items) |

The 9 unresolved items: `oral_examination` @15M (`OQ-WCV-ORAL-15M`); `head_circumference` @30M/36M/48M/60M/72M (`OQ-WCV-HEAD-CIRC`); `developmental_milestones` @48M/60M/72M (`OQ-WCV-MILESTONES-4-6Y`). **An unresolved item blocks that item, not the visit.**

**(b) IFHAS package components** — `spec.components[]` of the 20 `screening_package` rules (plain strings; **75 rows, 37 distinct strings**).

| Destination | Rule |
|---|---|
| `category` | `package_component` |
| `code` | `slug(text)` — **provisional, D10** (below) |
| `code_origin` | `derived_slug` |
| `text_verbatim` | the component string, **verbatim** (required by CHECK for `derived_slug`) |
| `ordinal` | 1-based position in `spec.components` |
| `description` | = `text_verbatim` (the only description the YAML offers; none is invented) |
| `source_reference` | the **package rule's** `source_reference`; `inherited_from_rule = true` |
| `verification_status` | the **package rule's** `verification_status` (inherited) |
| `condition_text`, `components_text`, `rule_refs`, `notes` | `NULL` |

**Slug function (proposed; D10 is not approved).** NFKD-normalise → drop combining marks → lower-case → replace every run of characters outside `[a-z0-9]` with `_` → strip leading/trailing `_`. Examples: `Body Mass Index (BMI)` → `body_mass_index_bmi`; **`Anti- Müllerian testing (AMH Testing)` → `anti_mullerian_testing_amh_testing`** (a naive ASCII-only regex would give `anti_m_llerian…` — the `ü` case is why NFKD is specified). **Verified: 75 strings → 37 distinct slugs, 0 collisions inside any package.** A collision inside a package **rejects** the load; the loader never appends `_2`-style suffixes (that would invent identifiers). A later move to explicit YAML codes is a data migration of `code`, which also sits in the `rule_item_open_question` key (CU-2).

**Item authority is parent-aware (CU-11; MC-6; CD-1).** An item inherited from a package carries **no independent authority**: a component copies only the parent's *verification status*, not its `requires_clinical_review` flag. As previously designed, the 6 `package_component` rows under the 4 verified-but-flagged packages (cervical Pap ×2, cervical HPV ×2, liquid biopsy ×1, lung LDCT ×1) would have been `is_authoritative = true` while their rule is not authoritative. The earlier remedy — "consumers AND the two values" — is **withdrawn**: a column named `is_authoritative` that is wrong by construction invites misuse. Replaced by:

```
item.effective_authority =
      item.status_is_verified
  AND parent_rule.is_authoritative
```

exposed by view `clinical.v_rule_item_effective_authority` (a generated column cannot reference another table). **Loader assertion (LV-2):** after load, recompute every rule's authority and every item's effective authority, compare with the database, and assert `effective_authority ⇒ parent.is_authoritative`. An item never becomes authoritative on its own when its parent is not. In the *existing* loader the defect is **not reproducible**: `RuleItem.is_authoritative` has no parent reference, but items are produced only from the 14 Well-Child `visit_schedule` rules (all authoritative), so **0 authoritative items sit under a non-authoritative rule** across the 174 visit items; the 4 flagged packages' `spec.components` are not turned into items by the existing loader. The defect appears only with the database design's 75 `package_component` rows, and "the day one of the 14 visit rules is flagged".

**Content in `spec` that is *not* an item (CU-17).** Each visit also carries `history_components` and `counselling_elements` (`{source_reference, items[], notes}`), present on all 14 visits. They have no code and no per-item verification status, so they stay in `spec` JSONB only.

**Keys.** PK `(rule_id, rule_version, category, code)`; composite FK to `rule`. **Validation.** *Loader:* existing item checks (code, description, source_reference, valid status, unknown OQ id, unresolved ⇒ ≥ 1 OQ, `rule_refs` exist); duplicate `(rule, category, code)`; slug collisions; `components` is a list of strings. *DB:* PK, FK, `code_origin`/`text_verbatim` CHECK, generated `status_is_verified`; the effective-authority view.

### 2.11 `clinical.rule_open_question`

One row per entry of each rule's **own** `open_question_ids[]`. **Verified: 69 rows; 37 of 54 rules have ≥ 1.** Constraints: each id exists in `open_question` (existing loader), no duplicate id within a rule's list (new assertion; the PK would reject it). **Never derived from `open_question.affects`.** `spec.timing.open_question_ids` (present on the 14 visits, **14 entries, all already in the rule-level list** — verified) is **asserted to be a subset** of the rule-level list and is not a second source. Every `unresolved` rule and every `requires_clinical_review` rule has ≥ 1 row (verified; also a loader rule).

### 2.12 `clinical.rule_item_open_question`

One row per entry of each **item's** `open_question_ids[]` (Well-Child items only). **Verified: 15 rows**, 9 rows from the 9 unresolved items (one question each) and 6 rows from 4 verified items that also cite a question. IFHAS components have none (they inherit nothing question-wise; the parent rule's questions are in `rule_open_question`). Unresolved items must have ≥ 1 row (loader rule + deferred trigger).

---

## 3. Versioning, effective dates, hashing

### 3.1 Partial-date triple (design §2.3) — rules

| YAML value | `_text` | `_precision` | `_from` |
|---|---|---|---|
| `YYYY-MM-DD` (valid calendar date) | as written | `day` | that date |
| `YYYY-MM` (month 01–12) | as written | `month` | **`NULL` — never the first of the month** |
| `null` / absent | `NULL` | `unknown` | `NULL` |
| anything else | — | — | **reject** |

Checks: `(precision = 'unknown') = (text IS NULL)`; `(precision = 'day') = (from IS NOT NULL)`. **No effective date is ever invented**: `2025-07` is not stored as `2025-07-01`; the Well-Child "TBD" is not stored as a date and is carried by the **mandatory note** and by the unresolved rule `WCV-PROG-EFFECTIVE-DATE-TBD` (`OQ-WCV-EFFECTIVE-DATE`, ADPHC). A rule's effective date is its **own** field; it is not inherited from or reconciled with the standard's.

### 3.2 Version rules (R-C2, F-25)

- **Append-only.** A `(rule_id, rule_version)` that does not exist is inserted with its conditions, items and associations in one transaction. `rule`, `rule_condition`, `rule_item` and both association tables are never updated or deleted (role privileges + trigger).
- **Same key, different `content_sha256` ⇒ the load fails** ("YAML edited without a version bump"). Because the hash covers *all* metadata (not only `spec`), flipping `verification_status` or `requires_clinical_review` without a bump is caught — the review's `spec_sha256` would miss it.
- **Same key, same hash ⇒ no-op** (idempotent).
- **A YAML `rule_version` lower than the highest version already loaded for that `rule_id` ⇒ reject** (a rollback would silently stop being "current" in `v_rule_current`). Version ordering uses the generated numeric columns.
- **A rule id in the database but absent from the YAML ⇒ the load fails** (no YAML mechanism and no column to retire a rule; **CU-12**). Nothing is deleted.
- **History.** The YAML `history[]` never keeps an old `spec`; the database is therefore the only place old versions survive. `history` is stored verbatim (all `[]` today). The existing loader rejects a history entry equal to the current version.

### 3.3 `content_sha256` — canonicalisation (to be implemented identically everywhere)

SHA-256 (hex, lower-case) of the UTF-8 bytes of `json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)` where `obj` is the **whole rule mapping** as parsed by `yaml.safe_load` after: (1) `date`/`datetime` scalars → ISO-8601 date text; (2) all mapping keys are strings; (3) `None` → `null`; (4) numbers kept as parsed (`18` stays integer). Comments, key order and whitespace of the YAML text do **not** affect it. `bundle_sha256` and `file_hashes` use raw **file bytes** (§2.2).

---

## 4. Authority, verification and clinical review

| Question | Answer in the data (verified) |
|---|---|
| Which rules may drive an authoritative decision? | **47** = `verified` **and** not flagged (IFHAS 24, WCV 23) |
| Which may not? | **7**: `IFHAS-PROG-AGE-CEILING` (unresolved, flagged); `IFHAS-PKG-CERVICAL-PAP-25-29`, `IFHAS-PKG-CERVICAL-HPV-30-65`, `IFHAS-PKG-LIQUID-BIOPSY-40-75`, `IFHAS-PKG-LUNG-LDCT-55-75` (verified **but flagged**); `WCV-PROG-EFFECTIVE-DATE-TBD`, `WCV-TIMING-DUE-WINDOW` (unresolved, flagged) |
| Is `verified` clinical validation? | **No.** `verification_status` means "transcribed from the standard and checked against its text"; `clinical_review_status` is `not_reviewed` for the whole bundle |
| Is `authoritative` approval, or "in force"? | **No to both** (design R-C8). Authoritative = source-verified and not flagged. `OQ-GOV-CLINICAL-VALIDATION` states no rule is clinically validated; **23 of the 47 authoritative rules (every authoritative Well-Child rule) have `effective_date = null`** ("TBD"), so none may be shown as in force |
| Can `is_authoritative` be set? | **No** — generated; the loader never writes it; `authoritative:` in YAML is rejected |
| Is an item authoritative? | Only if the item's own status is verified **and** its parent rule is authoritative (view `v_rule_item_effective_authority`) |
| Must unresolved items/rules carry questions? | Yes — `unresolved` ⇒ ≥ 1 OQ; flagged ⇒ ≥ 1 OQ; unresolved item ⇒ ≥ 1 OQ (loader + `CHECK (verification_status <> 'unresolved' OR requires_clinical_review)`) |

**Caution (CU-10).** "Authoritative" is a transcription-and-flag status, not "free of open questions": **30 of the 47 authoritative rules still cite ≥ 1 open question** (e.g. all 14 visit rules cite `OQ-WCV-DUE-WINDOW`; several packages cite `OQ-COMMON-AGE-CALC`; `IFHAS-PKG-AAA-M-65-75` cites `OQ-IFHAS-AAA-SMOKING-DEFINITION`). The mapping follows the derived formula exactly as instructed; the open questions are loaded and exposed so the application can show them. Whether any should demote a rule is a clinical/rules-owner decision.

**Open-question citations are not exhaustive (CA-4; MC-8).** For each question the YAML `affects` names a wider scope than the rules that cite it: `OQ-COMMON-AGE-CALC` is declared for 54 rules but cited by 16 (38 in scope, not cited); `OQ-COMMON-SEX-ATTRIBUTE` 29 / 1; `OQ-IFHAS-FREQUENCY-ANCHOR` 29 / 2; `OQ-IFHAS-AGE-CEILING` 29 / 2; `OQ-IFHAS-KPI-TARGET` 29 / 1; `OQ-WCV-EFFECTIVE-DATE` 25 / 15; `OQ-WCV-DUE-WINDOW` 25 / 16; `OQ-GOV-CLINICAL-VALIDATION` 54 / **0**. 17 authoritative rules cite no question although most are IFHAS packages to which the age, sex and frequency questions plainly apply. **"Cites no open question" therefore does not mean "has no applicable open question"**, and authority must never be computed from citations alone. Mechanical remedy: expand pathway-level `affects` into per-rule links at load time, recorded as **derived** links distinct from **cited** links (LV-4; needs no clinical judgement — which questions should apply to which rules does).

**Proposed per-link effect model — NOT approved (CD-2; OC-1).** Blocking is a property of the *(rule, question) link*, not of the question: `OQ-IFHAS-AGE-CEILING` blocks `IFHAS-PROG-AGE-CEILING` but is informational on `IFHAS-PROG-ELIG-MIN-AGE`. Proposed classes: `blocks_rule` (rule content contested or incomplete → non-authoritative while open), `gates_outputs` (faithful transcription; named outputs cannot be produced until answered), `informational` (shown, blocks nothing). Under the proposal 0 of the 30 would be demoted automatically, 28 carry a `gates_outputs` link, 2 only `informational` links; three rule decisions are left to the owner (`IFHAS-PKG-AAA-M-65-75`'s undefined "ever smoked", FIT/colonoscopy flagging consistent with liquid biopsy, `IFHAS-PROG-ELIG-SEX-BY-PACKAGE`). **Interim representation until decided:** the formula is unchanged (conservative — it never promotes anything); every citation is loaded; "authoritative" is read as "verified transcription, not flagged"; every consumer surfaces the cited open questions beside the rule; the 30 are not described as "clean". No `effect` column exists and no table is added.

---

## 5. Semantics the mapping must not break

These are **data contracts for the future engine**; none is enforced by a foreign key or `CHECK` (R-C6), and each needs an engine test.

| Concept | Where it lives | What the mapping guarantees |
|---|---|---|
| **Programme eligibility** | `rule_type ∈ {programme_eligibility, programme_scope}` (gates) **and** the age/sex/conditions of a package | Loaded verbatim. `IFHAS-PROG-AGE-CEILING` stays `unresolved` — no universal ceiling is encoded; people above the printed bands get no package result and require review (`OQ-IFHAS-AGE-CEILING`) |
| **Care gap** | `synthetic.care_gap` only | `clinical` stores *rules*, never gaps. Gap-yielding evaluation statuses are an engine decision (design §7 step 7); no `clinical` column or row says "gap" |
| **Elevated health risk** | **not represented in `clinical`** | There is no risk score or risk rule in the YAML. Smoking history / pack-years are **package inclusion conditions** (§2.9); M-CHAT-R / IDAQ tiers are **screening-result tiers, `is_diagnosis: false`**. The loader asserts this and adds no risk field |
| **Missing patient history** | `guard GUARD-MISSING-HISTORY → unknown`; `never_inferred_from` on `due`, `completed`, `not_eligible` | Loaded verbatim. **Missing history is never stored or implied as "not screened"/"not completed"** |
| **Overdue** | `evaluation_status.overdue` (+ `requires_text`); `WCV-TIMING-DUE-WINDOW` unresolved; all 14 visits `due_window: null`, `due_window_status: not_specified_by_standard` | No due window is projected or invented. **Loader rule:** any Well-Child visit with a non-null `due_window` is accepted only if `WCV-TIMING-DUE-WINDOW` is `verified` and not flagged, otherwise the load fails — so an authoritative `overdue` can never be supported by database content while the window is unresolved. (The `overdue` *note* is not in a column — CU-7.) |
| **Refusal** | not an evaluation status (D2 provisional) | `refused` is **not** added to `evaluation_status`; `WCV-POLICY-PARENTAL-REFUSAL` is an ordinary `policy` rule; `OQ-WCV-REFUSAL-STATE` stays open |
| **Look-ahead for `upcoming`** | `requires_text` on `upcoming` | No value is stored; it is product configuration (D17) |

---

## 6. Validation and rejection conditions

**Already enforced by the existing loader** (kept; the database loader calls it first): YAML parse; file present; `config.pathway` matches; non-empty `rules[]`; all mandatory metadata present; unknown rule key rejected; `authoritative` rejected; `verification_status` ∈ 3; pathway matches the file; semver; `effective_date` ∈ {date, `YYYY-MM`, null-with-note}; `last_reviewed` a date; `(source_name, source_version)` registered; `open_question_ids` exist; `unresolved`/flagged ⇒ ≥ 1 OQ; `screening_package` has `age{min_years,max_years,as_printed}`, `sex ⊆ {female,male}`, `frequency{type,as_printed}` (+ interval for `recurring`); item `code`/`description`/`source_reference`/valid status/known OQ/unresolved ⇒ OQ; `history` well-formed and ≠ current version; duplicate `rule_id`; `rule_refs` exist; the 9 evaluation statuses and 3 verification statuses defined. (Collects *all* problems and raises one `RuleConfigError`.)

**Additional database-loader assertions (new):**

| # | Assertion | Why |
|---|---|---|
| 1 | `requires_clinical_review` is **mandatory** on every rule and `machine_evaluable`, `one_time`, `is_diagnosis`, `is_screening_result_only`, `may_drive_decisions` are present where defined; each must satisfy `isinstance(v, bool)` — reject `null`, `""`, `0`, strings and an absent key; never coerce (LV-1) | the existing `bool(raw.get(..., False))` fails **open** for `null`, `""`, `0` and an absent key |
| 2 | Both rule files' `clinical_review_status` equal; `config.pathway` consistent | single `rule_load` column |
| 3 | `sources.yaml` ↔ manifest by `document_reference`; manifest state ∈ {`blocked`,`document_obtained`} | `standard.acquisition_state` CHECK |
| 4 | Every guard's `result`/`reason_code` exists; evaluation/verification vocabularies equal the loader's constants | FK resolution |
| 5 | Conditions: required keys/types; **`kind ∈ {inclusion, exclusion}`**; **`machine_evaluable: true` rejected on an `exclusion`**; `machine_evaluable = false` ⇒ parent flagged; `true` ⇒ `attribute` and `required_value` not `None` (LV-6, LV-7) | cross-table rule; CT-1 |
| 6 | Projections equal `spec`; stray projections `NULL`; `recommended_age.unit == months`; `one_time` ↔ `frequency_type`; tier invariants; `score_min NULL ⇒ score_max NULL` | R-C4 |
| 7 | Item uniqueness and slug-collision rejection; `spec.timing.open_question_ids ⊆ rule-level` | keys |
| 8 | Well-Child non-null `due_window` only with a verified, unflagged `WCV-TIMING-DUE-WINDOW` | no authoritative `overdue` |
| 9 | Hash guard; no version downgrade; no rule vanishing from YAML | append-only |
| 10 | `verification_status = 'unresolved'` ⇒ `requires_clinical_review` reported by the loader (not only by the insert-time `CHECK`) (LV-3) | the existing loader enforces only `unresolved ⇒ ≥ 1 question` |
| 11 | After load, every rule's authority and every item's `effective_authority` is recomputed and compared with the database; `effective_authority ⇒ parent.is_authoritative` (LV-2) | CD-1 |
| 12 | Pathway-level `affects` expanded into derived per-rule links stored apart from cited links; rules in scope of an open question but citing none are reported (LV-4). Once CD-2 is approved: reject a link without an `effect` (LV-5) | CA-4, CA-1 |
| 13 | Exact counts reported (54 rules, 47/7 authority, 8 conditions of which 5 `inclusion` / 3 `exclusion`, 249 items, 69 + 15 association rows, 23 OQs, 2 standards, 3/9/9/7 vocabulary rows) and compared to the previous load | reconciliation |

**What belongs where.** *Database constraints:* PKs, composite FKs, lookups, partial-date CHECKs, `NOT machine_evaluable OR (...)`, `verification_status <> 'unresolved' OR requires_clinical_review`, `code_origin` ↔ `text_verbatim`, generated authority, semver, append-only trigger. *Loader assertions:* everything in the two tables above. *Deferred constraint triggers (optional):* "non-machine-evaluable condition ⇒ rule flagged", "unresolved ⇒ ≥ 1 OQ". *Application:* surfacing open questions beside authoritative rules; engine tests for §5. *Manual/external:* the PDFs' content, the "TBD" status, due window, every open question, clinical review.

---

## 7. Unresolved issues (clinical)

| ID | Unresolved | Why it matters | Blocks | Who | Safe interim |
|---|---|---|---|---|---|
| **CU-1 / D2** | Refusal representation — **provisional; clinical approval required (S2–S5)** | prevents inventing a `refused` status; affects synthetic design | **Later** (synthetic/engine); **not** this mapping | **Clinical** (S2–S5), product (S1/S4), governance/legal (S5); **ADPHC** for `OQ-WCV-REFUSAL-STATE` | `evaluation_status` keeps 9 values; nothing refusal-related in `clinical` |
| **CU-2 / D10** | IFHAS component codes (slug vs YAML codes) — recommendation, **not approved** | `code` is part of two composite keys | **Later** — rule loader behaviour for 75 rows | Project owner; **rules owner** for YAML codes | derived NFKD slug, `code_origin = derived_slug`, `text_verbatim` retained |
| **CU-3 / D11** | Evaluation history — recommendation, **not approved** | reshapes one synthetic table if reversed | Later (synthetic) | Project owner | none needed here |
| **CU-4 / D14** | Rule applicability policy | decides who is shown as eligible | **Later** — engine | **Clinical** | no DB restriction on which rule type an evaluation cites |
| **CU-5 / D17** | Guard precedence, `partial` history, age convention (`OQ-COMMON-AGE-CALC`), look-ahead | engine would invent behaviour | Later — engine | **Clinical** (1,2,4); owner (3) | no precedence stored; all fired guards recorded downstream |
| **CU-6** | `rule_reported_not_verified` is emitted by no guard; `GUARD-RULE-NOT-VERIFIED` maps *every* non-`verified` status (incl. `reported`) to `rule_unresolved` | `reported` rules would be mislabelled | Later — engine | Rules owner | loaded verbatim; no `reported` rule exists today |
| **CU-7** | YAML content with no column: `evaluation_status.note` (`overdue`, `unknown`, `insufficient_information`), `deterministic_evaluation_policy`, status/OQ-file `last_reviewed`, `open_question.sources_in_conflict`, rule files' `config.disclaimer`/`publication_status`/`effective_date_as_printed` | the **`overdue` note carries a safety rule** that is absent from the relational copy | Later — any consumer reading only the DB | Owner (design review: e.g. a `note` column) | content stays in YAML, bound to the load by `file_hashes`; the loader report echoes it; engine tests read the YAML |
| **CU-8** | `WCV-FU-SPECIALIST-EVALUATION-2-4W` is a 2–4 **week range**; `timing_value` is single-valued | a one-sided projection would mislead | Later — referral deadlines | Owner / **clinical** | `timing_*` all `NULL`; range in `spec` only |
| **CU-9** | `WCV-IDAQ-REFERRAL` has no score; `score_max NULL` also means "open" | ambiguity | None | Owner | `score_min NULL ⇒ no range`, asserted |
| **CU-10** | 30 authoritative rules cite open questions; `OQ-IFHAS-AAA-SMOKING-DEFINITION` sits on a verified, unflagged rule; citations are not exhaustive versus `affects` (§4); per-link `effect` model proposed, **not approved** (CD-2, OC-1 … OC-5) | "authoritative" may overstate | Later — UI/engine; **authoritative evaluation** | **Clinical / rules owner** | formula applied exactly; questions exposed; authoritative = verified transcription, not approval, not in force (R-C8) |
| **CU-11** | Items inherited from a verified-but-flagged package (6 rows) would show authority from their own status alone | wrong by construction | **Models/migrations on `rule_item`** | Owner (names to confirm) | **design corrected (CD-1):** `status_is_verified` + parent-aware view + LV-2 assertion; implementation not started |
| **CU-12** | No way to retire a rule / OQ in YAML or DB | a vanished rule would still be "current" | Loading edge case | Owner | load fails; nothing deleted |
| **CU-13** | A no-op re-run still writes a `rule_load` row; failed loads leave **no** database trace | audit of failures | None | Owner | failures logged to the loader report/quarantine file (strategy §9) |
| **CU-14** | Standards PDFs not held; clinical review `not_reviewed`; `source_reference` pages unverifiable here | every rule is a transcription | **Later** — any clinical claim | **Clinical reviewer**; owner to fetch PDFs from a UAE network | `acquisition_state = blocked`; no validation claimed |
| **CU-15** | Existing loader coerces `requires_clinical_review` with `bool()`; `null`, `""`, `0` and an absent key give `False` (**fail-open**); the key is in `OPTIONAL_RULE_KEYS`; no test covers a non-boolean | silent mis-parse; a rule silently becomes authoritative | Loading | Owner | database loader requires a mandatory, real boolean (LV-1); all 54 current values are real booleans |
| **CU-16** | WCV effective date TBD (`OQ-WCV-EFFECTIVE-DATE`); no due/overdue window (`OQ-WCV-DUE-WINDOW`) | Well-Child outputs cannot be called in force or overdue | Later | **ADPHC** (`WCV.Support@adphc.gov.ae`) | `unknown` precision + note; `due_window` null; `overdue` unproducible |
| **CU-17** | `history_components`, `counselling_elements` not mapped to items | no per-item verification exists | None | Owner | kept in `spec` |
| **CU-18** | `guard.result_status`/`reason_code` nullability not stated (ERD §9 #2) | FK strictness | None | Owner | `NOT NULL` (all 7 guards supply both) |

---

## 8. Discrepancies between this mapping, the canonical design and the ERD

| # | Finding | Handling |
|---|---|---|
| C-1 | Design §4.2: condition `kind` "`inclusion` observed"; data has **`inclusion` ×5 and `exclusion` ×3** | design wording corrected in rev 2.5 (`inclusion` and `exclusion`); `CHECK (kind IN ('inclusion','exclusion'))` added to the design (CD-4) |
| C-2 | ERD/design: `rule_load.config_versions` "of IFHAS, WCV, status, open-question files"; **`sources.yaml` has no `config_version`** | 4 keys only; sources hashed in `file_hashes` |
| C-3 | Design says `evaluation_status` carries `definition, requires_text, never_inferred_from, sort_order`; YAML also has `note`, plus file-level policy/`last_reviewed` | CU-7 (design review requested; **not** changed here) |
| C-4 | `open_question` has no column for `sources_in_conflict` (1 question) | CU-7 |
| C-5 | Design projection `timing_value NUMERIC` cannot hold a range | CU-8 |
| C-6 | Design: `score_max NULL` = open; IDAQ has no score at all | CU-9 |
| C-7 | Design: item authority = item status; inherited component status ignores the parent's review flag | CU-11; **design corrected in rev 2.5 (CD-1)** |
| C-8 | Design "unresolved … `OQ-IFHAS-AAA-SMOKING-DEFINITION`" noted as inconsistency #12 | CU-10 (unchanged) |
| C-9 | Existing loader's `bool()` coercion (fail-open for `null`/`""`/`0`/absent, not only the string case) | CU-15 |
| C-10 | `standard.manifest_source_id` match: manifest `version` for SRC-03 is `V10 (Revised)` vs `V10` | match on `document_ref` ↔ `document_reference` |
| C-11 | ERD `never_inferred_from` shown as `text_array` with no nullability | absent → `NULL` (§2.4) |

**No table was added, removed or re-keyed; the approved table inventory (12) and architecture are unchanged.** C-3/C-4 (and CU-7) are the only items that could justify an additive column; **none is made — review requested.**
