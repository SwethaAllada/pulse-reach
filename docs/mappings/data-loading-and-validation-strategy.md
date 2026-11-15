# PulseReach — data loading and validation strategy (`official` and `clinical`)

**Phase 3, Step 3 (design only).** No loader, script, SQL, model or migration was written. This document specifies *how* the two mapping documents are executed: order, transactions, validation placement, reconciliation, error handling, idempotency and audit.

**Date:** 2026-11-15
**Canonical design:** [`../phase-3-database-design.md`](../phase-3-database-design.md) revision 2.5. **Mappings:** [`official-source-to-table-mapping.md`](official-source-to-table-mapping.md) ("OFF"), [`clinical-yaml-to-database-mapping.md`](clinical-yaml-to-database-mapping.md) ("CLIN"). Item ids `OU-n` / `CU-n` refer to the unresolved registers in those documents.
**Status:** **DRAFT for review.** No clinical, legal, governance or publisher approval is claimed. **D6, D7, D11 are recommendations awaiting owner confirmation (not approved); D2 is provisional (clinical approval required); D3–D5 and D13 need external clarification; D10, D12, D14, D15, D17 are open.** This strategy is neutral to all of them (§11).

---

## 1. Principles

1. **Raw files and YAML are immutable inputs.** The loader reads `data/raw/**` and `data-pipeline/rules/**`; it never edits them and never writes under `data/raw/`.
2. **Verify, then validate, then write.** All parsing, classification and checking happens **in memory** and produces a *load plan* and a *load report* before the first database write. The databases are not used as a staging area (no permanent staging tables exist in the approved architecture; if a temporary table is useful it must be a session `TEMP … ON COMMIT DROP`).
3. **A unit is all-or-nothing.** The unit of work is defined per schema (§6). A unit that fails validation writes **nothing**.
4. **Never repair, deduplicate, reinterpret or fabricate.** Ambiguity is preserved (a flag, a `pending` state, a `NULL`, a raw column) and reported. The only "corrections" permitted are the ones the design already names, each recorded in a column (`geo_quality`, `correction_state`, `quality_flag`).
5. **The loader owns writes; the application is read-only.** The loader role has `INSERT` (and the narrowly specified `UPDATE`s below); the application role has `SELECT` only on `official` and `clinical`; only the generator/engine writes `synthetic` (design §2.1).
6. **Same input, same output.** Re-running with identical inputs creates no duplicate and no change (data-idempotent). Time-stamped audit rows may be added (§9).

---

## 2. Overall sequence

`official` and `clinical` have **no foreign keys between them** and are loadable independently, in either order, or one without the other. The recommended order follows the migration order (official → clinical → synthetic).

```
 P0  Preflight            (both)   environment, versions, locks, DB state
 P1  Extract              (both)   enumerate inputs; read bytes
 P2  Verify checksums     (both)   raw files vs raw_checksums.sha256 · YAML vs file hash record
 P3  Parse + validate     (both)   in memory; build load plan + report; STOP on FATAL
 P4  Reference data       (both)   official: source, source_file, region, license_status_map
                                   clinical: standard, vocabularies, rule_load, open_question
 P5  Definitions          (both)   official: indicator, indicator_dimension, dimension_member
                                   clinical: rule, rule_condition, rule_item
 P6  Facts / associations (both)   official: observation, facility
                                   clinical: rule_open_question, rule_item_open_question
 P7  Post-load checks     (both)   FK/orphan queries, soft references, counts
 P8  Reconciliation       (both)   known-answer and cross-source checks (classified, not asserted)
 P9  Report + audit       (both)   immutable load report; rule_load row (clinical)
```

### 2.1 `official` — table order and unit of work

| Step | Table | Depends on | Unit of work / transaction |
|---|---|---|---|
| 1 | `source` | — | one transaction **O-A** (steps 1–3, with `region`, `license_status_map` seed) |
| 2 | `source_file` | `source` | O-A |
| 3 | `region` | — (labels read from data) | O-A |
| 4 | `indicator` | `source_file` (metadata workbook) | one transaction **O-B** per indicator file (86): `indicator`, `indicator_dimension`, new `dimension_member`s |
| 5 | `indicator_dimension` | `indicator` | O-B |
| 6 | `dimension_member` | `region` | O-B |
| 7 | `observation` | `indicator`, `source_file`, `dimension_member` | **O-B (same transaction as its indicator)** — all rows of that file or none |
| 8 | `license_status_map` | — | one transaction **O-C** (facilities): unseen raw statuses inserted first |
| 9 | `facility` | `region`, `source_file`, `license_status_map` | O-C — **all 9 layers in one transaction** (5,339 rows) so the register is never half-loaded |

`dimension_member` rows are shared between indicators: O-B inserts only the members it needs (`ON CONFLICT DO NOTHING` + compare). Because members never change after insertion, O-B transactions are independent and can be retried individually.

### 2.2 `clinical` — table order and unit of work

One transaction **C-A** for the whole bundle (54 rules is small; a half-loaded rule set is never acceptable):

1. Take the loader advisory lock; read the previous `rule_load` (for `config_versions` comparison).
2. `standard` (upsert by `document_ref`).
3. `verification_status`, `evaluation_status`, `reason_code` (replace only if `status_definitions.yaml → config_version` changed), then `guard` (FKs to the previous two).
4. `rule_load` (insert; counts known from the P3 plan — no later UPDATE).
5. `open_question` (upsert; `first_load_id`/`last_changed_load_id`).
6. `rule` (insert new versions), then `rule_condition`, `rule_item`.
7. `rule_open_question`, `rule_item_open_question`.
8. P7 checks inside the transaction (deferred constraints are evaluated at commit); commit.

---

## 3. Source extraction

| Source | Enumerated by | Notes |
|---|---|---|
| Raw files | the 215 non-comment lines of `data/reference/raw_checksums.sha256` **and** a directory walk of `data/raw/`; the two sets must be equal | a file on disk but not in the checksum list (or vice-versa) is FATAL |
| Manifest | `data/reference/source_manifest.yaml` | its own SHA-256 is recorded in the report (it is not in the checksum list) |
| Rules | the five YAML files: `rules/{ifhas,well_child,common}/*.yaml` | loaded through the existing `load_rules()` first (CLIN §1) |
| Facility properties | GeoJSON `features[].properties`, `geometry.coordinates` | **never** `data/processed/` |
| API values | `$.Data.Data[]` parsed with `parse_float=Decimal` | no binary-float round trip |

**Not extracted:** workbooks (`raw/scad/*.xlsx`) — provenance only (D9); the DoH/Gov-Digital files; contact fields of the facility register (excluded permanently).

---

## 4. Raw-file checksum verification

1. For every one of the 215 files: compute SHA-256 from the bytes; compare with the checksum list. **Any mismatch, missing or extra file is FATAL for `official`** (the files are the evidence; nothing downstream may run on bytes that differ from what was recorded). Re-verified in this step: **215 / 215 `OK`**.
2. The recomputed value (not the list value) is what is written to `source_file.sha256`; they are equal by construction once step 1 passes.
3. YAML: compute each file's SHA-256 (feeds `rule_load.file_hashes` / `bundle_sha256`). There is no pre-recorded YAML checksum list; the git commit (when the tree is clean) plus `rule_load` is the record.
4. **No hash is trusted from `acquisition_log.json`** — its paths are absolute temp paths and not portable (OFF §3); it is read only for informational fields.
5. A file that is **already registered** must have the same `sha256` for the same `relative_path`; otherwise FATAL (raw is immutable; a new vintage needs a new path — OFF §3).

---

## 5. Staging, validation and transformation

All in memory, in this order, per input:

1. **Parse** (JSON/GeoJSON/YAML/XLSX-metadata). Syntax error ⇒ the unit fails.
2. **Shape checks** — keys and types expected by the mapping (e.g. indicator rows have only the known dimension columns; each facility feature is a `Point`).
3. **Normalisation exactly as specified in the mappings** — no other. (E.g. `''` → `NULL` for the three composite facility strings, `Yes/No → boolean`, partial-date triples.)
4. **Classification** — member roles, `row_role`, `geo_quality`, duplicate groups, leaf/aggregate reconciliation class.
5. **Plan** — compare with what is already in the database (read-only) and compute, per table: *insert*, *identical (skip)*, *conflict (fail)*.
6. **Report** — everything above, plus every assertion's result, written before any write.

The transformation code that already exists (`build_facilities.py`) is **not reused as is** (its repair logic is inside `main()`); the loader re-implements the same procedure and is gated by an **equivalence test** against `data/processed/facilities/abu_dhabi_health_facilities.csv` (OFF §9.1, OU-8). Extracting the function into an importable module is a separate task.

---

## 6. Reference data, fact and rule loading; idempotency

### 6.1 How reruns avoid duplicates — table by table

| Table | Natural/identifying key | Rerun with identical input | Rerun with different input |
|---|---|---|---|
| `official.source` | `source_id` | compare → skip | update **only** if `manifest_version` changed; same version + different content ⇒ FATAL |
| `official.source_file` | `relative_path` (UNIQUE) | same sha → skip | different sha for the same path ⇒ FATAL (immutable raw); new vintage = new path |
| `official.region` | `region_code` | skip | any label change ⇒ FATAL |
| `official.indicator` | `indicator_id` | skip | any mapped column differs ⇒ unit fails with a column diff |
| `official.indicator_dimension` | `(indicator_id, dimension_type)` | skip | differs ⇒ unit fails |
| `official.dimension_member` | `UNIQUE NULLS NOT DISTINCT (type, en, ar)` | `ON CONFLICT DO NOTHING`, then compare role/bounds/`region_id` | role change ⇒ unit fails (only the reviewed correction path may change `correction_state`) |
| `official.observation` | **file-level**: `source_file_id` | if rows exist for the file: count and content hash equal ⇒ skip | rows exist but differ ⇒ unit fails; **never** a partial insert, **never** delete-and-reload |
| `official.license_status_map` | `raw_value` | `ON CONFLICT DO NOTHING` | **never** updates a reviewed row |
| `official.facility` | `(source_layer, source_object_id)` | compare → skip | changed row ⇒ FATAL; second register vintage refused (OU-17) |
| `clinical.standard` | `document_ref` | skip | upsert; change recorded by the new `rule_load` |
| vocabularies / `guard` | `code` / `guard_id` | skip | replace **only** with a `config_version` change |
| `clinical.rule_load` | `load_id` (identity) | **adds one audit row per successful run**, `rules_added = 0` | — |
| `clinical.open_question` | `oq_id` | skip | upsert; `last_changed_load_id` set only on a real change |
| `clinical.rule` | `(rule_id, rule_version)` | same `content_sha256` ⇒ skip | different hash ⇒ FATAL; lower version ⇒ FATAL; vanished rule ⇒ FATAL |
| `rule_condition`, `rule_item`, association tables | inherited composite keys | inserted only with a *new* rule version | never touched for an existing version |

**Why observation needs file-level idempotency.** The design's uniqueness is a partial index `WHERE quality_flag IS NULL`; the two flagged 3422 rows are outside it, so `ON CONFLICT` cannot protect them. Skipping a whole file whose rows are already present — and refusing a partial match — closes the gap without any schema change. A `UNIQUE (source_file_id, source_row_ordinal)` would make it structural (OU-17, **proposed, not applied**).

### 6.2 Locking and concurrency

A session advisory lock per schema (`official`, `clinical`) is taken at P0; a second loader run for the same schema waits or exits (configurable). Within a unit the load uses one transaction; no `autocommit` row-by-row writes.

### 6.3 Bulk method

`COPY` through `psycopg` (already a dependency; design §2.2) into the target — **not** `pandas.to_sql`. For tables with identity keys the loader obtains ids via `INSERT … RETURNING` / re-select by natural key before loading dependents. Generated columns (`is_additive`, `is_authoritative`, `ver_*`) are never named.

---

## 7. Foreign-key validation (P7)

| Check | Mechanism |
|---|---|
| Every declared FK | the database (constraints) — a failure aborts the transaction |
| Every observation's ten `*_member_id` points at a member of the **matching** `dimension_type` | loader assertion (plan time) **and** a post-load query (design §6.3 #1) |
| Every observation's `source_file_id` is a detail file **of its indicator** | loader assertion + post-load query |
| `indicator_dimension` rows ↔ non-null member columns of its observations | post-load query (both directions) |
| `facility.license_status_raw` / `region_id` resolve | FK; plus "no unseen raw status left unreviewed-and-missing" |
| `clinical.standard.manifest_source_id` exists in `official.source` | **soft reference**, loader test, run **only when `official` is loaded**; `clinical` is loadable alone |
| `rule_item.rule_refs[]` name existing `rule_id`s | loader assertion (no FK; names no version) |
| `spec.timing.open_question_ids ⊆ rule-level` | loader assertion |
| **No FK crosses the one-way dependency** (`official`/`clinical` → `synthetic`; `official` ↔ `clinical`) | schema test over `pg_constraint` / `pg_depend` after every migration and load (design §2.1) |

---

## 8. Reconciliation checks (P8)

**Count reconciliation** — the loader compares inserted-or-already-present counts with these expected values (all recomputed from the files in this step; a different value is reported and, where marked, blocks):

| Table | Expected | Blocks if different? |
|---|---|---|
| `official.source` | 24 | yes |
| `official.source_file` | 215 (**214 until OU-14 is resolved**) | yes (except the known OU-14 file) |
| `official.region` | 3 | yes |
| `official.indicator` | 86 (71 with workbook, 15 without) | yes |
| `official.indicator_dimension` | 87 rows (17 indicators none, 55 × 1, 10 × 2, 4 × 3) | yes |
| `official.dimension_member` | 195 (incl. 2 `(unlabelled)`) | report |
| `official.observation` | 14,913 (leaf 9,912 / aggregate 5,001; 2 flagged `duplicate_key_conflict`) | yes (unflagged duplicates ⇒ unit fails) |
| `official.facility` | 5,339 (identified 4,905 / unidentified 434); per layer 1,250 / 87 / 13 / 1,290 / 114 / 49 / 1,715 / 387 / 434 | yes |
| `official.facility` by `geo_quality` | ok 5,299 · swapped_repaired 31 · missing_placeholder 6 · out_of_bounds 3 | yes (equivalence test) |
| `official.license_status_map` | 14 raw values, all `unreviewed` | report |
| `clinical.standard` | 2 | yes |
| `clinical.verification_status` / `evaluation_status` / `reason_code` / `guard` | 3 / 9 / 9 / 7 | yes |
| `clinical.open_question` | 23 (all `open`) | yes |
| `clinical.rule` | 54 (IFHAS 29, WCV 25); authoritative 47 / not 7 | yes |
| `clinical.rule_condition` | 8 (7 not machine-evaluable) | yes |
| `clinical.rule_item` | 249 = 174 WCV (103/31/40; 9 unresolved) + 75 IFHAS components | yes |
| `clinical.rule_open_question` / `rule_item_open_question` | 69 / 15 | yes |

(*Expected* values describe today's inputs; a legitimately changed input needs the expected-values file updated in the same reviewed change.)

**Content reconciliation** (classified, never "fixed"):

- **Leaf vs aggregate** — per (indicator, year, dimension): `reconciles` / `no_aggregate` / `aggregate_only` / `mismatch`, and **every `mismatch` carries a `mismatch_class`** (`RC-ZERO-LEAVES`, `RC-PROJ-ROUNDING`, `RC-RESIDUAL-BELOW`, `RC-LEAVES-ABOVE`, `RC-UNEXPLAINED`, `RC-HIERARCHY`; tests in design §3.3). Today (single-dimension counts): 486 / 141 / 11 / **42**, the 42 being **33 `RC-ZERO-LEAVES`, 4 `RC-PROJ-ROUNDING`, 4 `RC-RESIDUAL-BELOW`, 1 `RC-UNEXPLAINED`** (a *proposal*; the publisher has confirmed none). **Multi-dimension cubes (screening, not classification):** 4,858 slices tested, 4,379 reconcile, **479 do not** (299 all-zero leaves, 128 leaves below, 52 above), 432 not testable. The mismatches are *reported* (OU-16), never failures and never corrected — the design's premise that leaves always sum to the aggregate is false (OFF §8.2). `mismatch` cells and projected series are excluded from derived totals.
- **Known answers** (cross-source, verified in this step; these are named checks and do **not** imply that every cell reconciles — see the leaf-vs-aggregate result above): births 2025 = **41,235** in all three cuts (3463 leaves 167 + 24,760 + 16,308; 3465 leaves 2 + 28,822 + 100 + 11,246 + 1,065; 3466 `Total` 41,235 = 21,471 + 19,762 + 2); population 2025 = **4,358,921** (3916; and 3175's emirate member = 3,008,513 + 1,003,647 + 346,761).
- **Register vs statistics — never reconciled by the database** (R-O4): SDI active-licence figures (71 hospitals / 8,828 licensed beds) and SCAD (75 / 8,082 operational) are **not** compared or merged by any loader check; they are recorded as a *documented non-reconciliation*.
- **YAML ↔ database round trip (clinical)**: for every rule, `content_sha256` recomputed from the stored `spec`/metadata equals the stored hash; typed projections equal `spec`; `count(items) = Σ items in YAML`.

---

## 9. Error handling, quarantine, audit and provenance

### 9.1 Severity classes

| Class | Examples | Effect |
|---|---|---|
| **FATAL (run)** | checksum mismatch / unmapped or extra raw file; `RuleConfigError`; manifest invalid; DB role or schema-boundary test fails; hash-guard violation; rule vanished; clinical review status disagreement | nothing is written for that schema |
| **UNIT-FAIL** | one indicator file fails a shape/assertion (unexpected dimension column, unexpected duplicate group, unclassifiable date-like label on a non-age dimension, null `VALUE`); facility register fails an assertion (unknown region, bad boolean, `null_geometry`, equivalence test) | that unit is **quarantined** (nothing written); other units may proceed (`official` indicators are independent; the facility register and the clinical bundle are single units) |
| **FLAGGED LOAD** | `duplicate_key_conflict` (3422) | rows **are** loaded with the flag, excluded from default views, listed for the publisher |
| **REPORT** | reconciliation `mismatch`; `retrieved_at` `NULL`; `unmapped_file`; `Not applicable` role effect; YAML content with no column | load continues; entry in the report |

### 9.2 Quarantine

There is no quarantine *table* in the approved design and none is added. **Quarantine = a unit that is not written**, represented by a **quarantine record in the load report**: unit id, input path + SHA-256, rule violated, row references (`$.Data.Data[i]`, `OBJECTID`/layer), expected vs found, and the date. Quarantined inputs are never auto-retried with different logic, and **never** repaired in `raw/`. A quarantined unit is released only by (a) a corrected loader/mapping, (b) a recorded owner/publisher decision, or (c) a new, separately checksummed raw vintage. **The one in-database quarantine is the `quality_flag` mechanism** (D5).

### 9.3 Audit and provenance

| Item | Official | Clinical |
|---|---|---|
| Input identity | `source_file(relative_path, sha256, byte_size)` for all inputs; manifest hash in the report | `rule_load.file_hashes`, `bundle_sha256`, `git_commit` |
| Code identity | `source_file.loader_version`, `observation.loader_version`, `facility.transform_version` | `rule_load.loader_version` |
| Per-row lineage | `observation.source_file_id` + `source_row_ordinal`; `facility.source_file_id` + `(source_layer, source_object_id)` | `rule.load_id`, `yaml_path`, `content_sha256`; `open_question.first_load_id/last_changed_load_id` |
| Time | `source_file.retrieved_at` is **retrieval** only (often `NULL`); load time is `registered_at`; **publisher dates are text only** (`source_effective_note`) | `rule_load.loaded_at` |
| Per-run record | the **load report** (JSON/markdown, content-hashed, kept outside `data/raw/`) | `rule_load` row **plus** the load report |

**Load report contents:** run id and UTC time; loader and mapping versions; input hashes; per-table inserted / skipped / quarantined counts; every assertion result; reconciliation classes; the discrepancy list; the OU/CU items that fired. **A failed clinical load leaves no database trace** (CU-13) — the report is the only record; this is deliberate (writing a failure row would need a table or a nullable-everything `rule_load`) and is flagged for review.

---

## 10. Where each validation belongs

Legend: **DB** = database constraint (CHECK / FK / UNIQUE / generated column / trigger); **LOAD** = loader assertion (fails or reports at load); **APP** = application/engine/UI validation; **EXT** = manual or external confirmation.

| Rule | DB | LOAD | APP | EXT |
|---|:-:|:-:|:-:|:-:|
| PK/FK/UNIQUE integrity; `sha256` format; enumerated `CHECK`s; coordinate ranges; `value ↔ marker` pairing; bed ≥ 0; `license_no <> ''`; partial-date triples; semver; `is_authoritative`, `is_additive`, `ver_*` generated | ✔ | | | |
| Facility CHECKs: usable coordinates only when `ok`/`swapped_repaired`; identity nulls; `license_status_map` review CHECKs | ✔ | | | |
| Partial unique index on clean observations | ✔ | | | |
| Append-only `rule`/`rule_condition`/`rule_item` and association tables | ✔ (privilege + trigger) | hash guard | | |
| Member `dimension_type` matches its observation column | optional composite FK | ✔ | | |
| Observation `source_file` is a detail file of its indicator | | ✔ | | |
| Aggregate/leaf classification; `row_role` derivation | | ✔ | | |
| Leaf-sum reconciliation (single- and multi-dimension) | | report with `mismatch_class` | derived views exclude `mismatch` and projected series | SCAD (OU-16; OP-S1, OP-S2, OP-S4) |
| Duplicate-group detection and flagging (3422); unexpected duplicates | | ✔ | | SCAD (D5) |
| Corrupted age-label detection; **applying** a correction | `correction_state` CHECK | detect → `pending` | unusable until applied | **SCAD confirmation** (D4) |
| Missing marker semantics (`-`, `:`) | column exists | raw stored | | **SCAD** (D3) |
| `measure_kind`, `region_basis` mappings | CHECKs | read reviewed seed | additive views | data steward / SCAD |
| Licence status → operating | `CHECK (confirmed ⇒ reviewed)` | insert `unreviewed` | `v_facility_usable` | **DoH licensing** (D13) |
| Geo repair equivalence with the validated transformation | | ✔ | | |
| Facility ↔ SCAD never joined (R-O4) | no FK exists | | no view/join | |
| `machine_evaluable = false` ⇒ rule flagged; unresolved ⇒ ≥ 1 open question | `CHECK` for the intra-table part; optional deferred trigger | ✔ | | |
| `authoritative:` rejected; `requires_clinical_review` real boolean | generated column | ✔ | | |
| Typed projections equal `spec` (R-C4) | type-conditional CHECKs | ✔ | | |
| **No `overdue` for Well-Child**; no authoritative result when due window unresolved | **not a constraint (R-C6)** | `due_window` gating | **engine + test** | ADPHC (`OQ-WCV-DUE-WINDOW`) |
| **Missing history ⇒ `unknown`, never "not completed"** | | guards loaded verbatim | **engine + test** | clinical (D17) |
| Guard precedence; `partial` history; age convention; applicability policy | none | none | engine (record, don't decide) | **clinical** (D14, D17) |
| Item authority AND parent rule authority | generated per table | | **consumer must AND** | |
| Clinical review of any rule/question | | `clinical_review_status = not_reviewed` | banner | **qualified clinician** |
| Standard document content / page references | `acquisition_state = blocked` | | | **fetch PDFs from a UAE network** |
| `refused` never an evaluation status | `evaluation_status` rows are the YAML's 9 | ✔ | engine | clinical (D2) |
| Schema-boundary (no FK across the one-way model) | | | schema test | |

**Not assumed enforceable by a foreign key or CHECK** (all appear above as LOAD/APP/EXT): cross-table implications (conditions ⇒ review; unresolved ⇒ OQ), reconciliation, aggregate semantics, Well-Child `overdue`, guard precedence, publisher meanings, licence operating status, clinical validity.

---

## 11. Cross-schema considerations

### 11.1 Dependencies

```
synthetic → official    patient.region_id → region ; facility_service_profile.facility_id → facility ; generation_run calibration provenance
synthetic → clinical    rule / rule_item versions, evaluation_status, reason_code, guard, verification_status, rule_load
official  ✗ synthetic   never          clinical ✗ synthetic   never          official ↔ clinical   no FK either way
clinical.standard.manifest_source_id  ···>  official.source.source_id      (soft text reference, loader test, no FK)
```

**Not done in this task:** no synthetic table, patient, generator output or ERD is created or implied; the `synthetic` schema stays unimplemented (D2 provisional; its ERD pending).

### 11.2 Reference records the future synthetic evaluation engine will need

| From | Records | Why / condition |
|---|---|---|
| `official.region` | all 3 | `patient.region_id`; region-shaped generation |
| `official.facility` | identified rows with usable coordinates | `facility_service_profile.facility_id`. **A profile also needs an *operating* licence — unavailable until D13 confirms any `license_status_map` row**, so **no profile can be created yet**. 434 unidentified rows and 9 non-usable-coordinate rows are never eligible |
| `official.observation` (+ `indicator`, `dimension_member`) | **leaf, clean, current-vintage rows only** (via `v_observation_leaf`) for *shape* calibration (population, births, capacity) | aggregates, `duplicate_key_conflict`, `pending` age members, projections and non-additive indicators are excluded or labelled; which indicators calibrate which attribute is a *synthetic-design* decision — **not specified here** (the synthetic spec names none) |
| `official.source`, `source_file` | rows behind every calibration input | `generation_run` provenance; attribution (OU-15) |
| `clinical.rule` (+ `rule_condition`, `rule_item`) | all 54 versions (authoritative **and** non-authoritative) | evaluations cite `(rule_id, rule_version)`; non-authoritative rules must be representable (`requires_clinical_review`) |
| `clinical.evaluation_status`, `reason_code`, `guard`, `verification_status` | all | evaluation FKs; guards are applied first by the engine |
| `clinical.rule_load` | the load the engine ran against | `rule_bundle_load_id` on `generation_run` / `evaluation_run` |
| `clinical.open_question` (+ association tables) | all 23 | "what does this question block?" and clinical-review routing |
| `clinical.standard` | 2 | citation and "document not held" state |

**Engine prerequisites that are *not* satisfied by loading:** D14 (applicability policy), D17 (guard precedence, `partial` history, age convention, look-ahead), D12 (working-day calendar for `IFHAS-WF-REFERRAL-15WD`; no weekend/holiday assumption exists), D2 (refusal), D11 (history confirmation).

### 11.3 Cross-schema test hooks

After each load: (1) the boundary test of §7; (2) if both schemas are loaded, every `standard.manifest_source_id` exists in `official.source` with `acquisition_state = 'blocked'`; (3) `official.source` rows `SRC-02-IFHAS` and `SRC-03-WCV` are `blocked` (the database must never suggest the standards' text is held).

---

## 12. Decisions and unresolved items (consolidated)

Detailed registers: OFF §11 (OU-1…21) and CLIN §7 (CU-1…18). **Statuses are exactly as recorded in the design — none is marked approved here.**

| Decision | Status (design rev 2.3) | Blocks mapping? | Blocks loading? | Blocks later implementation? | Who must approve / clarify | Safe interim approach |
|---|---|:-:|:-:|:-:|---|---|
| **D2** refusal | **Provisional** — clinical approval required (S2–S5; product S1/S4; governance/legal S5; ADPHC for `OQ-WCV-REFUSAL-STATE`) | no | no | **yes** — synthetic refusal triggers/generator/ERD | Clinical, product, governance/legal, ADPHC | 9 evaluation statuses only; no `refused` anywhere in `clinical` |
| **D3** `-` / `:` | Open | no | **workbook loading only** | no | **SCAD** | store raw marker, `value NULL`; API-only MVP |
| **D4** age labels | Open | no | no (`pending`) | **age-band use of 2584/3276/3535/4868** | **SCAD** (+ owner for the rule) | `pending`, bounds `NULL`, unusable as a band |
| **D5** 3422 | Open | no | no (flagged) | no | **SCAD** | `duplicate_key_conflict`, excluded from default views |
| **D6** coordinates | **Recommended — awaiting owner confirmation; not approved** | no | no | **yes — before the first migration** | Project owner | two `DOUBLE PRECISION` columns as designed |
| **D7** migrations | **Recommended — awaiting owner confirmation; not approved** | no | no | **yes — before the first migration** | Project owner | none; no tool installed or assumed |
| **D9** workbooks / re-fetch | Open | no | loader scope | no | Owner | API only; new vintage ⇒ new path |
| **D10** IFHAS codes | Open | **provisional rule** (slug) | rule-loader behaviour for 75 rows | later data migration if YAML codes added | Owner; **rules owner** for YAML | derived NFKD slug + `text_verbatim` |
| **D11** evaluation history | **Recommended — awaiting owner confirmation; not approved** | no | no | `synthetic.eligibility_evaluation` | Owner | design already assumes append-only |
| **D12** calendar | Open | no | no | referral deadlines; decides `working_calendar` | Owner + ADPHC | `working_days` stored verbatim; no assumption |
| **D13** licence statuses | Open — **external clarification (DoH licensing, advisable)** | no | **facility usability** | **blocks `facility_service_profile` creation** | Owner + DoH licensing | all 14 `unreviewed`; no operating facility |
| **D14** applicability | Open | no | no | **engine** | Owner + **clinical** | no DB restriction |
| **D15** facility vintage / as-published coordinates | Open | no | **facility loader prerequisite** (importable repair + equivalence) | no | Owner | read raw GeoJSON; reimplement + equivalence test; `source_effective_date NULL` |
| **D17** evaluation contract gaps | Open | no | no | **engine** | Owner + **clinical** | record, don't decide |
| OU-10, OU-11 (`measure_kind`, `region_basis`) | Unreviewed mappings | no | no | additive/region views | Data steward / SCAD | `unclassified` / `unspecified` |
| OU-13, OU-14, OU-15 (timestamps, orphan file, attribution) | Open | no | partial (1 of 215 files; second vintage) | attribution display | Owner / legal | `NULL`s and an `unmapped_file` report |
| OU-16, OU-18, OU-19 (reconciliation mismatches, null labels, label variants) | Open | no | no | derived totals / label merging | **SCAD** | verbatim + classified report |
| OU-17 (idempotency uniqueness; single-vintage facility) | Design observation | no | loading design | re-fetch of the register | Owner (design review) | file-level all-or-nothing; second register vintage refused |
| CU-6, CU-7, CU-8, CU-9 (loader/design gaps in the YAML-to-DB copy) | Open | no | no | engine / consumers | Owner; rules owner; clinical | verbatim YAML remains source of truth |
| CU-10, CU-11, CU-14, CU-16 (authority caveats, review, PDFs, WCV date/window) | Open | no | no | any clinical claim | **Clinical reviewer; ADPHC; owner to fetch PDFs** | `not_reviewed`; `blocked`; `overdue` unproducible |

**What blocks what, in one line each.** *Mapping:* nothing — every ambiguity has a preserved representation. *Loading `official`:* checksum/inventory integrity, the equivalence test (D15), D6/D7 (before the first migration, because the loader needs tables). *Loading `clinical`:* `load_rules()` passing and the new assertions; D7 as above. *Using the data:* D13 (operating facilities), D4/D3/D5 (the data they touch), D2/D14/D17/D12 (the engine and refusal), clinical review of everything.

---

## 13. Implementation checklist for the next step (not started)

1. Owner confirms or rejects **D6** and **D7** (recommendations only so far).
2. Owner reviews the design observations raised here/in the mappings (OFF D-1…D-12, OU-14/15/17; CLIN C-1…C-11, CU-7/8/9/11) — **additive changes are requested, none is made**.
3. Provide the two small reviewed seeds the loader reads: `unit_raw → measure_kind` (13 rows) and `region_basis` promotions (default empty).
4. Extract the facility repair function into an importable module and add the equivalence test (D15) — a transformation-code change, separate task.
5. Implement the loaders to these specifications, **starting with a dry-run mode that produces only the load report** (P0–P3), reviewed before any database write.
6. Do not implement refusal triggers, the engine or any synthetic table until D2 is clinically approved.
