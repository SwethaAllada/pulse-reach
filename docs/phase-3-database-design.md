# PulseReach — Phase 3 Consolidated Database Design

**Phase 3, Step 2.** Design only. No models, migrations, scripts, YAML, data or application code were created or changed. The only file written by this step is this document.

**Date:** 2026-11-15
**Status:** **DRAFT — partially approved.** Per the project owner's instruction recorded in revision 2.2: **D1, D8, D16 and D18 are APPROVED**; **D2 is PROVISIONAL — clinical approval required**; every other decision in §8 remains open. Nothing is clinically approved, and no external (clinical, legal, governance, SCAD, DoH) approval has been obtained.
**Revision:** 2.4 (2026-11-15) — source-to-database mapping specifications linked and their completion status recorded (§9.4); **no design content changed**. Revision 2.3 (2026-11-15) — D6, D7, D11 recommendations recorded (**pending owner confirmation, not approved**); `official` and `clinical` ERDs linked (§9.4). Revision 2.2 recorded owner decisions D1, D8, D16, D18 (D2 kept provisional; consent default applied, §5.2, §5.5). Revision 2.1 (final consistency corrections) is summarised in §12.
**Input verdict:** [`phase-3-database-design-review.md`](phase-3-database-design-review.md) — *APPROVED WITH CHANGES*.
**Canonical status:** once approved, this document supersedes the 11-table contract in [`../data/metadata/synthetic_data_spec.md`](../data/metadata/synthetic_data_spec.md) §3–4 as the database design. The spec's safety rules (§1), scenarios (§5) and generator prohibitions (§6) remain the contract the design must satisfy.

> **Convention used throughout.** Where a design element depends on a decision that is still open it is tagged **[PROVISIONAL: Dn]**. It is written as if the *recommended* option were chosen, so the design is reviewable, but it is **not** approved. Untagged elements are **[FINAL]** in the sense that they follow from data on disk, YAML on disk or a rule the review states unconditionally. "FINAL" here means "no open decision depends on it", not "owner-approved".

---

## 0. What was inspected, and what was not found

| Input | Result |
|---|---|
| `docs/phase-3-database-design-review.md` | Read in full (F-01 … F-29, D1 … D12, risks, discrepancies) |
| Earlier "Phase 3 database design proposal" | **Not present in the repository.** A filename search for `*database*design*` / `*schema*` found only the review itself. The review states the same and treats `synthetic_data_spec.md` §3–4 (11 tables, synthetic layer only) as the proposal. This design uses that spec **plus** the requirements in the review. If a separate proposal exists elsewhere, send it; §5 should be diffed against it. The 11 tables are **not** assumed to be the whole architecture — there was no proposal for the `official` or `clinical` layers. |
| `data/metadata/synthetic_data_spec.md` | Read in full (11 tables, 27 scenarios, safety rules) |
| `docs/data-acquisition-report.md`, `data/metadata/data_dictionary.md`, `data/metadata/data_quality_report.md` | Read (acquisition report: headline and structure; dictionary and quality report: in full) |
| `data/reference/source_manifest.yaml` | Read (header, source states for all 24 sources) |
| Rule YAML: `rules/ifhas/ifhas_rules.yaml`, `rules/well_child/well_child_rules.yaml`, `rules/common/{sources,open_questions,status_definitions}.yaml` | Loaded and profiled; representative rules read in full |
| Rule loader (`rule_loader/models.py`, `loader.py`) and `tests/test_rule_loader.py` | Read the data model and validators; the test file was **not** re-run in this step (the review reports 80 passing) |
| Backend / infrastructure | `infrastructure/docker-compose.yml` (`postgres:16-alpine`), `backend/requirements.txt` (SQLAlchemy 2.0.36, psycopg 3.2.3, pandas; **no Alembic, no PostGIS, no pytest**), `backend/app/core/config.py`; `backend/app/{db,models,schemas,services}` are empty packages |

**Independent spot-checks made in this step** (all consistent with the review): rule counts (IFHAS 29, WCV 25; verified+clean 47, verified+review-flagged 4, unresolved 3); 174 visit items (103 preventive / 31 developmental / 40 follow-up); 23 open questions; indicator 3422 duplicate key (`Non-Emirati / Male / Abu Dhabi Region / 2025` → values 1 and 1,708); date-corrupted age labels in indicators 2584, 3276, 3535, 4868 with labels `2026-05-09`, `2026-10-14`, `2026-01-04`. **New facts found while designing** (not in the review): the 20 IFHAS packages carry **75 component strings, 37 distinct** after slugging, with no collision inside any one package (relevant to D10); `IFHAS-WF-REFERRAL-15WD` and the WCV follow-up windows store their timing in `spec` with a `reference_event` (relevant to §4 projections and D12).

---

## 1. Architecture summary

Three PostgreSQL schemas, three independent concerns, **one-way dependencies**.

```
            ┌──────────────────────────┐
            │        synthetic         │   18 tables — fabricated individuals and events
            └───────┬───────────┬──────┘
        references  │           │  references
                    ▼           ▼
        ┌────────────────┐   ┌────────────────┐
        │    official    │   │    clinical    │
        │  9 tables      │   │  12 tables     │
        │  published     │   │  YAML-loaded   │
        │  aggregates +  │   │  rules,        │
        │  facility      │   │  vocabularies, │
        │  register      │   │  open questions│
        └────────────────┘   └────────────────┘
              (no dependency between official and clinical;
               neither may reference synthetic)
```

| Layer | What it is | Source of truth | Mutability |
|---|---|---|---|
| `official` | Published aggregate statistics (SCAD API: 86 indicators / 14,913 rows), the SDI facility register (5,339 points), and provenance for all 215 raw files | Files in `data/raw/` (+ `source_manifest.yaml`, `raw_checksums.sha256`); never edited by hand | Loaded by a loader role; a new vintage is a **new** `source_file` and new rows |
| `clinical` | The 54 IFHAS/Well-Child rules, 174 visit items, IFHAS components, 23 open questions, status vocabularies, standards registry | **YAML in `data-pipeline/rules/` — and only there.** The database is a *loaded, versioned copy*, never an authoring surface | **Append-only** rule versions; no UPDATE/DELETE on rules, conditions, items |
| `synthetic` | Fabricated patients and everything that happens to them | The generator (seeded, reproducible) and the deterministic engine; the database is a store | Event and evaluation tables append-only; a few lifecycle fields update (§5) |

**Table inventory (39 tables + 1 conditional):**

| Schema | Tables | Count |
|---|---|---|
| `official` | `source`, `source_file`, `region`, `indicator`, `indicator_dimension`, `dimension_member`, `observation`, `facility`, `license_status_map` (+ **conditional** `working_calendar` — only if D12 is decided that way) | 9 (+1) |
| `clinical` | `standard`, `rule_load`, `verification_status`, `evaluation_status`, `reason_code`, `guard`, `open_question`, `rule`, `rule_condition`, `rule_item`, `rule_open_question`, `rule_item_open_question` | 12 |
| `synthetic` | `generation_run`, `evaluation_run` (D16 — approved), `patient`, `guardian`, `consent`, `facility_service_profile`, `history_availability`, `eligibility_evaluation`, `evaluation_reason` (D16 — approved), `ifhas_screening`, `well_child_visit`, `component_result`, `assessment`, `referral`, `care_gap`, `care_gap_review`, `appointment`, `outreach_event` | 18 |

Versus the review's §8 list (9 / 8 / 16): `clinical` gains `rule_load`, `verification_status`, `guard`, `rule_item_open_question` (all required by findings F-25/F-26 and the loader's own model — see §10); `synthetic` gains `evaluation_run` and `evaluation_reason` **[APPROVED: D16]** (the review's F-03 references an `evaluation_run_id` that its own table list does not define).

Derived read objects (views, not tables, not counted): `official.v_observation_leaf`, `official.v_observation_current`, `official.v_derived_total_additive`, `official.v_indicator_year_shape`, `official.v_facility_usable`; `clinical.v_rule_current`, `clinical.v_rule_authority`; `synthetic.v_eligibility_current`, `synthetic.v_consent_current`, `synthetic.v_care_gap_effective_priority`, `synthetic.v_item_outstanding`.

### 1.1 Findings coverage

| Findings | Addressed in |
|---|---|
| F-11 (aggregates, year-dependent shape) | §3.3 `indicator`, `dimension_member`, `observation`, views |
| F-12 (value markers vs category members) | §3.3 `observation`, `dimension_member` |
| F-13 (unlabelled members) | §3.3 `dimension_member` |
| F-14 (duplicate key 3422) | §3.3 `observation` quality flag + partial unique index; D5 |
| F-15 (age-band corruption and schemes) | §3.3 `dimension_member`; D4 |
| F-16 (periods, projections, extrema) | §3.3 `indicator`, `observation` |
| F-17 (region is not one concept) | §3.3 `region`, `indicator.region_basis` |
| F-18 (wide observation shape) | §3.3 `observation`, `indicator_dimension` |
| F-19 (workbooks not loaded by default) | §3.2 `source_file`, §3.3; D9 |
| F-20 (real facilities + synthetic overlay) | §3.3 `facility`, §5 `facility_service_profile`; D1 |
| F-21 (identity, licences, sites) | §3.3 `facility`, `license_status_map`; D13 |
| F-22 (coordinates, corrections) | §3.3 `facility`; D6, D15 |
| F-23 (SDI vs SCAD separate) | §3.3 rule R-O4, §6 |
| F-24 (partial dates) | §2.3 partial-date convention, §4 `rule`, `standard` |
| F-25 (append-only versions) | §4 `rule`, `rule_load` |
| F-26 (derived authority) | §4 `rule`, `rule_item` |
| F-27 (IFHAS component identifiers) | §4 `rule_item`; D10 |
| F-28 (rules beyond packages) | §4.4, §5 `eligibility_evaluation` |
| F-01 … F-10, F-29 | §5 (each table cites its finding) |

---

## 2. Cross-cutting conventions

### 2.1 One-way dependency model

```
synthetic → official      (patient.region_id, facility_service_profile.facility_id, calibration provenance)
synthetic → clinical      (rule versions, rule items, status vocabularies, guards, rule_load)
official  ✗ synthetic     never
clinical  ✗ synthetic     never
official  ↔ clinical      no foreign keys either way
```

- **Why:** official and clinical data are reusable, publishable reference material; synthetic data is disposable and regenerable. If reference tables pointed at synthetic rows, deleting a synthetic run could damage reference data, and a real-data path could never be added without restructuring.
- **No FK from clinical to official.** `clinical.standard.manifest_source_id` is a *soft reference* (text) to `official.source.source_id`, validated by the loader test, not by a constraint. This keeps `clinical` loadable without any official data.
- **Enforcement (all three required, because a convention alone will rot):**
  1. *Privileges:* the application role has `SELECT` only on `official` and `clinical`; the loaders own them; only the generator/engine role writes `synthetic`.
  2. *Automated test:* a schema test queries `pg_constraint` and fails if any FK originates in `official` or `clinical` and targets `synthetic`, or links `official` ↔ `clinical`.
  3. *Search path:* `official` and `clinical` objects never reference `synthetic` in views or functions (same test over `pg_depend`).

### 2.2 Types, keys and naming (apply to every table)

| Concern | Rule |
|---|---|
| Surrogate keys, `official` | `BIGINT GENERATED ALWAYS AS IDENTITY`. Source-owned integer IDs (SCAD indicator ID) are used as-is where stable |
| Keys, `clinical` | Natural: `(rule_id, rule_version)`, OQ ID, etc. — the YAML already owns them |
| Keys, `synthetic` | **`TEXT` with a `SYNTH-<TYPE>-<digits>` pattern and a `CHECK`** on every table (spec §1.1: *every* primary key begins `SYNTH-`) |
| Timestamps | `TIMESTAMPTZ`, stored UTC, scheduled/displayed in `Asia/Dubai`. Day-precision facts are `DATE` |
| Measurements | `NUMERIC` (values are floats such as 6.0240963855; no float round-trip) |
| Vocabularies owned by YAML | **Lookup tables with FKs**, not PostgreSQL `ENUM` (an open question closing must not force `ALTER TYPE`) |
| Small closed vocabularies owned by this design | `TEXT` + `CHECK (… IN (…))` |
| Foreign keys | Indexed; `ON DELETE RESTRICT` / `ON UPDATE RESTRICT` everywhere. **No `CASCADE` anywhere** (audit tables must not vanish with a parent) |
| Constraint names | Shared SQLAlchemy `naming_convention`, so constraints are stable across migrations |
| Bulk load | `COPY` via psycopg (already a dependency), not `pandas.to_sql` |
| Nullability | `NULL` only where a *documented* state of "unknown/not applicable" exists. Every nullable column states what `NULL` means |

### 2.3 Partial-date convention (F-24)

IFHAS `effective_date` is `YYYY-MM`, every Well-Child `effective_date` is `null`, and the loader deliberately accepts `YYYY-MM`. A `DATE` column would force an invented day. For every such field the design stores a triple:

| Column | Type | Meaning |
|---|---|---|
| `<x>_text` | `TEXT NULL` | Exactly as in the YAML (`'2025-07'`, `'2025-12'`, or `NULL`) |
| `<x>_precision` | `TEXT NOT NULL CHECK IN ('day','month','unknown')` | `unknown` ⇔ `_text IS NULL` |
| `<x>_from` | `DATE NULL` | **Only** when precision = `day`. Never the first of the month |

`CHECK ((_precision = 'unknown') = (_text IS NULL))` and `CHECK ((_precision = 'day') = (_from IS NOT NULL))`.

### 2.4 Provenance, audit and versioning — the rules that hold everywhere

| # | Rule |
|---|---|
| P1 | Every `official` row traces to a `source_file` (path, SHA-256, retrieval timestamp) and carries a vintage (`period_year` or retrieval timestamp). **A retrieval timestamp is never presented as a source-effective date** |
| P2 | Every `clinical` row traces to a `rule_load` (bundle hash, loader version, timestamp) and the verbatim YAML mapping is retained |
| P3 | Every `synthetic` row carries `run_id` and `is_synthetic = true` |
| P4 | Anything a person or a model acted on is **append-only**: rules, evaluations, consent, reviews, outreach, referrals' history is never overwritten |
| P5 | A statement is only recorded if its source supports it: unknown stays `NULL`/`unknown`; no default is invented to satisfy `NOT NULL` |
| P6 | Derived values (authority, outstanding items, deadlines, `partial`) are **computed**, not stored as editable inputs |

---

### 2.5 Evidence-marker pattern (how a reference proves the *kind* of row it points at)

A plain foreign key proves that a row exists, not that it is the right kind of row (e.g. that a consent row *is* a valid refusal). The design uses one pattern wherever that matters:

1. The **referenced** table exposes a `GENERATED ALWAYS AS (…) STORED` boolean `<x>_valid` and a `UNIQUE (run_id, patient_id, <pk>, [rule_id, rule_version,] <x>_valid)` key.
2. The **referencing** table has a generated constant `<x>_marker BOOLEAN GENERATED ALWAYS AS (CASE WHEN <evidence ids> IS NOT NULL THEN TRUE END) STORED` that is part of the composite FK.
3. With `MATCH SIMPLE` the FK is skipped while the evidence id is `NULL`; once set, it can only resolve to a row whose `<x>_valid` is `TRUE`, for the **same run and same patient** (and the same rule, where stated).

Consequences: what counts as valid evidence is defined in **one generated expression**, so a clinical decision on D2 changes one expression and no relationship; a referenced row cannot later become invalid (the FK is `RESTRICT`, which blocks changing a referenced key column, and the evidence tables are append-only or immutable once referenced). Foreign keys on stored generated columns are supported by PostgreSQL provided no `CASCADE`/`SET NULL` action is used — consistent with §2.2.

## 3. Layer A — `official` schema

### 3.1 Design rules specific to this layer

| # | Rule | Finding |
|---|---|---|
| R-O1 | **Aggregate membership is a property of the dimension member and of each row, never of the indicator.** 37 of 86 indicators change cube shape across years; in 34 the only aggregate-free year is 2025 (e.g. 3549: 2024 sums to 8 × 39,333; 2025 sums to the correct 41,235) | F-11 |
| R-O2 | A **row** is `leaf` iff **none** of its dimension members is an aggregate; otherwise `aggregate`. Derived once at load, asserted by test | F-11 |
| R-O3 | Only `measure_kind = 'count'` is additive across leaf members. Rates, percentages, ratios and densities are never summed (e.g. 3280 under-five mortality: 2025 has only three region leaves; an emirate rate cannot be derived) | F-11 |
| R-O4 | **No foreign key, join or view between `official.facility` and SCAD observations.** SDI counts licences (71 hospitals / 8,828 licensed beds, active only); SCAD counts facilities (75 / 8,082 operational beds). A comparison is displayed side by side with both definitions, never merged | F-23 |
| R-O5 | The default read path is leaf-only. Totals for additive indicators are **derived in a view** and never stored as if they were source rows | F-11 |
| R-O6 | A **missing cell** (cube omitted a zero or unpublished combination) is *not published* — not zero, not missing-marker, not unknown | F-11 |
| R-O7 | `Not Stated`, `Missing/Unknown`, `Abroad`, `Other` are **dimension members that carry real numbers** and are summed with leaves. They are not null values and are never dropped or coerced | F-12 |
| R-O8 | Only the **API** is loaded into `observation` in the MVP. The five SCAD workbooks remain provenance and cross-check sources (the births-2025 Emirati/Non-Emirati split differs by 2 between API and XLSX) | F-19, D9 |
| R-O9 | Individual-level data never enters this schema | — |

### 3.2 Provenance tables

#### `official.source`  — **[FINAL]**
**Purpose.** One row per manifest source (24), mirroring `source_manifest.yaml`, so that "what we hold" and "what we only researched" are queryable.
**Source of truth.** `data/reference/source_manifest.yaml` (`manifest_version` 2.0.0).
**PK.** `source_id TEXT` (e.g. `SRC-17-SCAD-STATISTICS-API`).

| Column | Type | Null | Notes |
|---|---|---|---|
| `source_id` | TEXT | no | PK |
| `name`, `publisher` | TEXT | no | |
| `url` | TEXT | yes | |
| `licence_text`, `attribution_statement` | TEXT | yes | Verbatim; `NULL` = not recorded |
| `acquisition_state` | TEXT | no | `CHECK IN ('researched','document_obtained','dataset_obtained','blocked','excluded')` |
| `validation_state` | TEXT | yes | `CHECK IN ('none','structural','clinical')`; `NULL` for non-datasets. **No row may be `clinical`** until a qualified reviewer signs off |
| `fit_for_use` | BOOLEAN | yes | `NULL` = not assessed (e.g. MOHAP nurses: `false`) |
| `contains_data` | BOOLEAN | yes | `false` for the 5 Gov-Digital single-cell workbooks |
| `acquisition_reason` | TEXT | yes | Verbatim block reason for `blocked` |
| `manifest_version` | TEXT | no | |

**Checks.** `acquisition_state IN ('dataset_obtained','document_obtained')` ⇒ at least one `source_file` (enforced by a deferred constraint trigger and the loader test, since a `CHECK` cannot span tables). **`SRC-02-IFHAS` and `SRC-03-WCV` must load as `blocked`** — the database must never suggest the standards' text is held.
**Indexes.** PK only (24 rows).
**Relationships.** 1 ─ N `source_file`.

#### `official.source_file`  — **[FINAL]**
**Purpose.** One row per acquired file (215), mirroring `raw_checksums.sha256`; the anchor for every vintage and checksum.
**Source of truth.** `data/reference/raw_checksums.sha256` + each file's `_source` block / `acquisition_log.json`.
**PK.** `source_file_id BIGINT identity`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `source_id` | TEXT | no | FK → `source` |
| `relative_path` | TEXT | no | UNIQUE. Repo-relative (the acquisition log's absolute paths point into another session's temp directory and are **not portable**) |
| `sha256` | CHAR(64) | no | `CHECK (sha256 ~ '^[0-9a-f]{64}$')`. **Not unique** — identical bytes may legitimately appear twice |
| `byte_size` | BIGINT | no | |
| `file_role` | TEXT | no | `CHECK IN ('indicator_detail','indicator_metadata','publication_workbook','facility_geojson','catalogue','other')` |
| `retrieved_at` | TIMESTAMPTZ | yes | From the file's own `_source` block or the acquisition log. **`NULL` = not recorded. Never defaulted to load time** |
| `source_effective_note` | TEXT | yes | Free text only (e.g. the catalogue's "modified 2025-07-25/28"). Not a date column — see D15 |
| `contains_data` | BOOLEAN | no | |
| `fit_for_use` | BOOLEAN | yes | |
| `loader_version` | TEXT | no | Version of the loader that registered it |
| `registered_at` | TIMESTAMPTZ | no | `DEFAULT now()` |

**Indexes.** `UNIQUE(relative_path)`; `(source_id, file_role)`; `(sha256)`.
**Relationships.** 1 ─ N `indicator` (detail/metadata), `observation`, `facility`.

### 3.3 Statistics tables

#### `official.region`  — **[FINAL]**
**Purpose.** The three Abu Dhabi regions, as a stable target for SCAD members, facilities and patients (F-17).
**Source.** SCAD `REGION_EN` / SDI `REGION`; seeded by the loader (3 rows).
**PK.** `region_id SMALLINT`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `region_code` | TEXT | no | UNIQUE, `CHECK IN ('AD','AIN','DHF')` |
| `name_en`, `name_ar` | TEXT | no / yes | `name_ar` populated **from source labels only**; not invented |
| `scad_label` | TEXT | no | `Abu Dhabi Region` / `Al Ain Region` / `Al Dhafra Region` |
| `sdi_label` | TEXT | no | `Abu Dhabi` / `Al Ain` / `Al Dhafra` (no "Region" suffix) |

`Abroad`, `Not stated`, `Missing/Unknown`, `Other` and `Emirate of Abu Dhabi` are **not regions**; they are `dimension_member`s.

#### `official.indicator`  — **[FINAL]**
**Purpose.** The 86 SCAD indicators: definition, unit, measure kind and series kind.
**Source.** `indicator_detail/*.json` (`Metadata`, `Configuration[0]`) and, for 71, the metadata workbook. 15 indicators have no workbook; those columns are `NULL`, not blank.
**PK.** `indicator_id INTEGER` = SCAD numeric ID (source-owned, stable).

| Column | Type | Null | Notes |
|---|---|---|---|
| `slug` | TEXT | no | UNIQUE (file stem, e.g. `3463_births_by_citizenship`) |
| `title_en` | TEXT | no | |
| `definition_en` | TEXT | yes | `component_subtitle` |
| `unit_raw` | TEXT | no | Verbatim (13 distinct strings). **Never assumed** |
| `measure_kind` | TEXT | no | `CHECK IN ('count','rate','percentage','ratio','density','unclassified')`. Derived from `unit_raw` by a **reviewed mapping**; `unclassified` until reviewed. Anything not `count` is non-additive |
| `is_additive` | BOOLEAN | no | `GENERATED ALWAYS AS (measure_kind = 'count') STORED`. Additive **across leaf members at one period only** — never across periods (stock series such as population) |
| `series_kind` | TEXT | no | `CHECK IN ('observed','projected')`. 4868 is `projected` |
| `periodicity` | TEXT | no | `CHECK IN ('annual')` for the 86 acquired; widen only when a non-annual indicator is loaded |
| `region_basis` | TEXT | no | `CHECK IN ('residence','facility_location','unspecified')`. Derived from title, confirmed against the metadata "Geographic coverage" |
| `metadata_source_file_id` | BIGINT | yes | FK → `source_file` (current metadata workbook; `NULL` = none). There is deliberately **no** `detail_source_file_id`: several vintages of one indicator can coexist (D9), so the detail file is a property of each `observation` row. That an observation's `source_file_id` is a detail file *of the same indicator* is a loader assertion (§6.3) |
| `statistical_population`, `geographic_coverage`, `calculation_method`, `data_sources_text` | TEXT | yes | Metadata workbook; `NULL` = no workbook |
| `last_update_raw` | TEXT | yes | **Verbatim.** 4868 holds the sentinel `20400101`, which is not a date and must not be parsed |

**Indexes.** PK; `UNIQUE(slug)`; `(measure_kind)`.
**Relationships.** 1 ─ N `indicator_dimension`, `observation`.

#### `official.indicator_dimension`  — **[FINAL]**
**Purpose.** Which of the ten dimension types each indicator uses (0–3). Metadata the loader and tests assert against, because a `CHECK` cannot reference another table.
**PK.** `(indicator_id, dimension_type)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `indicator_id` | INTEGER | no | FK → `indicator` |
| `dimension_type` | TEXT | no | `CHECK IN ('region','citizenship','gender','age_group','cause_of_death','disease_type','measure_item','insurance_type','sector','bed_type')` |
| `source_column` | TEXT | no | Original (`REGION_EN`, … `INDICATOR_EN`, `TYPE_EN`). The source names `INDICATOR_EN`/`TYPE_EN` are misleading, hence `measure_item`/`insurance_type`; confirm `TYPE_EN` = insurance type per indicator before reuse |
| `ordinal` | SMALLINT | no | 1–3; `UNIQUE(indicator_id, ordinal)` |

17 indicators have no dimension rows (no dimensions); 55 have one; 10 two; 4 three.

#### `official.dimension_member`  — **[FINAL]**; age correction **[PROVISIONAL: D4]**
**Purpose.** Every distinct label of every dimension, with its *role* — the mechanism that separates "real category carrying a number" from "aggregate" from "label problem" (F-11, F-12, F-13, F-15).
**PK.** `member_id BIGINT identity`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `dimension_type` | TEXT | no | Same `CHECK` as `indicator_dimension` |
| `raw_label_en`, `raw_label_ar` | TEXT | no / yes | **Verbatim as published**, including corrupted age labels. A source `NULL` label is stored as the literal `'(unlabelled)'` with `member_role = 'unlabelled'` (F-13); SQL `NULL` in an *observation* dimension column always means "dimension not applicable to this indicator" |
| `canonical_key` | TEXT | no | Case-folded key (`abroad`/`Abroad`). Does **not** merge `Unknown` into `Missing/Unknown` — that needs publisher confirmation |
| `member_role` | TEXT | no | `CHECK IN ('leaf','aggregate','not_stated','missing_unknown','abroad','other','unlabelled')`. **`aggregate` is the only role excluded from sums** (R-O7) |
| `region_id` | SMALLINT | yes | FK → `region`. Set **only** where the member *is* one of the three regions: `CHECK (region_id IS NULL OR dimension_type = 'region')` |
| `scheme_code` | TEXT | yes | Age scheme (5-year, 10-year, custom sets, `Less than one year`); age members only |
| `age_min_months`, `age_max_months` | INTEGER | yes | `NULL` max = open-ended (`80+`). `CHECK (age_min_months <= age_max_months)`. `Less than one year` → 0–11. **`NULL` for any member whose label is unconfirmed (below)** |
| `correction_state` | TEXT | no | `CHECK IN ('none','pending','applied')`. Default `none` |
| `label_corrected_en` | TEXT | yes | `CHECK ((correction_state = 'applied') = (label_corrected_en IS NOT NULL))` |
| `correction_basis` | TEXT | yes | Required when `applied` (the SCAD confirmation reference) |

**Age-label rule [PROVISIONAL: D4].** Four indicators (2584, 3276, 3535, 4868) return `2026-05-09`, `2026-10-14`, `2026-01-04` for `5-9`, `10-14`, `1-4`. The year (2026) is probably the extraction year, so a literal remap breaks on re-fetch. Design: the loader **detects by pattern** `^\d{4}-(\d{2})-(\d{2})$` **on `AGE_GROUP` members only**, records `correction_state = 'pending'` and **does not set bounds or a corrected label**; `applied` is reachable only after (a) the pattern matches, (b) the candidate band is contiguous with its neighbours in that indicator, **and** (c) SCAD's confirmation is recorded in `correction_basis`. Until then those members exist, carry real numbers, and are unusable as age bands. `2026-01-04 → 1-4` is an inference and is never auto-applied.

**Unique.** `UNIQUE NULLS NOT DISTINCT (dimension_type, raw_label_en, raw_label_ar)` (PostgreSQL 15+; compose pins 16).
**Indexes.** `(dimension_type, member_role)`; `(region_id)`.

#### `official.observation`  — **[FINAL]**
**Purpose.** One row per published SCAD data point (14,913 for the API set).
**Why wide, not EAV/JSONB:** ≤ 3 dimensions per indicator but 10 dimension types; a wide table with nullable typed FK columns keeps uniqueness enforceable and queries direct (F-18). ~15 k rows: no partitioning, no materialised views.
**Source.** `Data.Data[]` rows of the API files.
**PK.** `observation_id BIGINT identity`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `indicator_id` | INTEGER | no | FK → `indicator` |
| `source_file_id` | BIGINT | no | FK → `source_file`. **Part of row identity** so two vintages of one indicator can coexist (§D9) |
| `period_year` | SMALLINT | no | From `YEAR` (equals `OBS_DT` year for every row). `CHECK (period_year BETWEEN 1900 AND 2100)` |
| `period_type` | TEXT | no | `CHECK = 'year'` (all 86 are annual; `MONTH_*`/`QUARTER_*` are never populated) |
| `obs_date_raw` | TEXT | no | `OBS_DT` verbatim |
| `region_member_id`, `citizenship_member_id`, `gender_member_id`, `age_group_member_id`, `cause_of_death_member_id`, `disease_type_member_id`, `measure_item_member_id`, `insurance_type_member_id`, `sector_member_id`, `bed_type_member_id` | BIGINT | yes ×10 | FK → `dimension_member`. `NULL` = dimension does not apply. Each member's `dimension_type` must match its column (loader assertion + test; an optional generated-column composite FK can enforce it in-DB) |
| `value` | NUMERIC | yes | |
| `value_marker_raw` | TEXT | yes | Cell-level marker (`-`, `:`). **Unused by the MVP API load** (0 of 14,913 values are null); kept so loading a workbook later needs no migration. **Meaning unassigned — D3** |
| `row_role` | TEXT | no | `CHECK IN ('leaf','aggregate')` — R-O2, loader-derived |
| `source_row_ordinal` | INTEGER | no | Position in `Data.Data[]` |
| `quality_flag` | TEXT | yes | `CHECK IN ('duplicate_key_conflict')`; `NULL` = clean. Extendable by migration |
| `loader_version` | TEXT | no | |

**Checks.**
- `CHECK ((value IS NULL) = (value_marker_raw IS NOT NULL))` (F-12). Never coerce a marker to 0.
- No value-range `CHECK` is defined — units differ per indicator and none is invented.
- **Partial unique index:** `UNIQUE NULLS NOT DISTINCT (indicator_id, source_file_id, period_year, <10 member columns>) WHERE quality_flag IS NULL` (F-14, D5). Both 3422 rows load with `duplicate_key_conflict`, are excluded from every default view, and are listed for SCAD. **Neither is guessed correct.**
- Loader reconciliation test (not a DB constraint): wherever a row-set contains both an aggregate and its leaves, leaves sum to the aggregate (the quality report states they do).

**Indexes.** `(indicator_id, period_year)`; every member FK column; the partial unique index above.
**Views.**
- `v_observation_current` — latest `source_file` per indicator (by `retrieved_at`).
- `v_observation_leaf` — **default read path**: `row_role = 'leaf'` AND `quality_flag IS NULL`, current vintage.
- `v_derived_total_additive` — totals computed from leaves for `is_additive` indicators only, labelled *derived*.
- `v_indicator_year_shape` — per `(indicator, year)`: has-aggregate, leaf count, whether leaves reconcile. Makes year-dependent shape visible.

### 3.4 Facility register

#### `official.facility`  — **[FINAL]**; coordinate types **[PROVISIONAL: D6]**; vintage/provenance **[PROVISIONAL: D15]**
**Purpose.** The SDI health-facility register **as published**, one row per **licence-level** feature (5,339). It is *not* site-level: 24 co-located groups (50 rows) share name and coordinates with different licences; they are **not** de-duplicated.
**Source.** `raw/abudhabi_sdi/*.geojson` (43 attributes) — **not** `processed/` (which keeps 26 and only the corrected coordinates).
**PK.** `facility_id BIGINT identity`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `source_layer` | TEXT | no | `CHECK IN ('hospitals','health_centres','clinics','pharmacy','rehabilitation_center','provision_health_service','diagnostic_centers','mobile_health_unit','dialysis_centre')` |
| `source_object_id` | INTEGER | no | `OBJECTID`; unique **only within** a layer (1,715 distinct in 5,339). `UNIQUE (source_layer, source_object_id)` |
| `license_no` | TEXT | yes | `UNIQUE` (NULLs distinct); `CHECK (license_no <> '')`. Globally unique where present (4,905). The 434 blanks are `NULL`, never `''` |
| `identity_status` | TEXT | no | `CHECK IN ('identified','unidentified')`. The 434 `rehabilitation_center` rows carry **no** name, licence, status, region, city or type → `unidentified`. They can never be a registered facility or appear on a default view |
| `facility_name_en`, `facility_name_ar` | TEXT | yes | |
| `type`, `category`, `subtype` | TEXT | yes | As published |
| `region_id` | SMALLINT | yes | FK → `region` (`NULL` for the 434) |
| `city` | TEXT | yes | |
| `license_status_raw` | TEXT | yes | FK → `license_status_map(raw_value)`. 15 distinct values incl. the typo variant `Preliminary -Cancelled by Law` (×24) |
| `is_public_raw` | TEXT | yes | Verbatim (contains a stray `N` ×3) |
| `is_public` | BOOLEAN | yes | Normalised (`N` → false); derived |
| `has_insurance` | BOOLEAN | yes | `thiqa/basic/enhanced` are **not loaded** (constant `N/A` in all 4,905 rows; they look like data and are not) |
| `inpatient_bed_capacity` | INTEGER | yes | `CHECK (>= 0)`. The bed field. **Licensed capacity — not operational beds** |
| `beds_raw`, `specialities_raw`, `professionals_raw` | TEXT | yes | Verbatim composite strings. No child tables (no MVP consumer) |
| `emergency_department`, `pediatric_emergency_department`, `maternity_emergency_care`, `home_care_services` | BOOLEAN | yes | Loader fails on any value other than Yes/No |
| `source_longitude`, `source_latitude` | DOUBLE PRECISION | yes | **As published.** The `(0,0)` placeholders and out-of-bounds points are stored here exactly as given |
| `longitude`, `latitude` | DOUBLE PRECISION | yes | **Usable** coordinates; `NULL` unless `geo_quality IN ('ok','swapped_repaired')` |
| `geo_quality` | TEXT | no | `CHECK IN ('ok','swapped_repaired','missing_placeholder','out_of_bounds')` |
| `source_file_id` | BIGINT | no | FK → `source_file` (its `retrieved_at` is the **retrieval** timestamp) |
| `source_effective_date` | DATE | yes | **`NULL`** — the register has no publication date (quality report B6). Populated only if the publisher states one. Never the retrieval date and never the catalogue's modified date |
| `transform_version` | TEXT | no | Version of the repair/classification code |

**Checks.**
- `CHECK (geo_quality IN ('ok','swapped_repaired') OR (longitude IS NULL AND latitude IS NULL))` — the 3 `out_of_bounds` rows (one at 26.75 N / 37.76 E, another 18.10 N / 42.19 E, a third lon 34.45) keep their bad values **only** in `source_*`.
- `CHECK (longitude IS NULL OR longitude BETWEEN 51.0 AND 56.5)` and `CHECK (latitude IS NULL OR latitude BETWEEN 22.0 AND 25.5)`. **`ok` means "inside a deliberately generous box", not "inside the emirate"** (the box includes parts of neighbouring states).
- `CHECK ((longitude IS NULL) = (latitude IS NULL))`.
- `CHECK (identity_status = 'identified' OR (license_no IS NULL AND facility_name_en IS NULL))`.

**Do not load:** `FACILITYEMAIL/PHONE/FAX/POBOX` (the licence grants no right to use personal information; some name individuals).
**Do not "fix":** the lon 34.45 outlier (a typo for 54.45 is speculation).
**Prerequisite (separate task, not done here).** `processed/facilities/` cannot supply `source_*` for the 31 repaired rows. The loader must read the raw GeoJSON through the same repair function, or the transformation must emit the as-published pair — **D15**.
**Indexes.** `(source_layer)`; `(region_id)`; `(license_status_raw)`; `(latitude, longitude) WHERE latitude IS NOT NULL`.
**Views.** `v_facility_usable`: `identity_status = 'identified'` AND usable coordinates AND `license_status_map.is_operating IS TRUE` (so it returns **nothing operating** until D13 confirms any mapping — by design).
**Relationships.** N ─ 1 `region`, `source_file`, `license_status_map`; 1 ─ N `synthetic.facility_service_profile` (the only inbound reference, from `synthetic`).

#### `official.license_status_map`  — **[FINAL]**; content **[PROVISIONAL: D13]**
**Purpose.** Maps each raw licence-status string to a grouping and an *operating* flag **only after human review**. Operating status is **not inferred** from unreviewed values.
**PK.** `raw_value TEXT`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `raw_value` | TEXT | no | One row per distinct source string (15 today). The loader **inserts any unseen value as `unreviewed`** so the FK holds |
| `status_group` | TEXT | yes | e.g. active / cancelled / expired / preliminary / suspended — proposed, not yet reviewed |
| `is_operating` | BOOLEAN | yes | **`NULL` until confirmed** |
| `review_state` | TEXT | no | `CHECK IN ('unreviewed','proposed','confirmed')` |
| `reviewed_by`, `reviewed_on`, `note` | TEXT/DATE/TEXT | yes | Required when `confirmed` |

**Checks.** `CHECK (review_state = 'confirmed' OR is_operating IS NULL)` — an unreviewed value cannot carry an operating flag. `CHECK (review_state <> 'confirmed' OR (reviewed_by IS NOT NULL AND reviewed_on IS NOT NULL AND is_operating IS NOT NULL))`. Note: even `Active` stays `proposed` until reviewed — only 3,005 of 5,339 rows are `Active`, and the meaning of `About to Expire`, `Temporary Closed` etc. is not stated by the publisher.

#### `official.working_calendar`  — **CONDITIONAL on D12**
`(calendar_date DATE PK, is_working_day BOOLEAN NOT NULL, note TEXT, source TEXT NOT NULL)`. Needed by `IFHAS-WF-REFERRAL-15WD` ("15 **working** days"). No weekend or holiday assumption exists anywhere in the repository, so none is hard-coded. Not in the table count until D12 chooses a table over an engine setting.

---

## 4. Layer B — `clinical` schema

### 4.1 Design rules

| # | Rule | Finding |
|---|---|---|
| R-C1 | **YAML is the single source of truth.** The database is a loaded, hash-verified copy. There is no authoring path in the database, no admin screen, no UPDATE on a rule. A change is: edit YAML → bump `rule_version` → load. Two authoring systems would diverge | — |
| R-C2 | `(rule_id, rule_version)` is the primary key and rows are **append-only** (§4.2 `rule`). The YAML `history` block keeps no old `spec`, so the database must keep every version it has ever loaded | F-25 |
| R-C3 | **Authority is derived, never configured.** `is_authoritative = (verification_status = 'verified' AND NOT requires_clinical_review)`, a generated column. There is no column that can be set to make a rule authoritative; the loader rejects an `authoritative:` key and so does the schema | F-26 |
| R-C4 | The original YAML mapping is retained verbatim (`spec` JSONB, `history` JSONB, `content_sha256`). Typed projection columns are convenience copies, asserted equal to the JSONB by a load test | — |
| R-C5 | **Nothing clinical is invented to fit a column.** Unresolved rules and items load with their open questions; a `NOT NULL` is never satisfied with a made-up threshold. The three unresolved rules carry no threshold and cannot be evaluated | — |
| R-C6 | No `CHECK` bakes in the outcome of an open question. In particular "no `overdue` for Well-Child" is **not** a constraint (it would hard-code `OQ-WCV-DUE-WINDOW`); the engine enforces it and a test proves it | F-28 |
| R-C7 | The `clinical` schema states plainly that **nothing in it is clinically validated** (`clinical_review_status = 'not_reviewed'` in both YAML configs). The standards' PDFs are **not held** | — |

### 4.2 Tables

#### `clinical.standard`  — **[FINAL]**
**Purpose.** The two source standards, with explicit "not held" state.
**Source.** `rules/common/sources.yaml`. **PK.** `standard_id SMALLINT`; `UNIQUE (source_name, source_version)`; `UNIQUE (document_ref)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `source_name`, `source_version`, `document_ref`, `publisher` | TEXT | no | |
| `publication_date_*` | partial-date triple (§2.3) | — | IFHAS `2025-07`, WCV `2025-12` → month precision |
| `effective_date_*` | partial-date triple | — | IFHAS `2025-07`; **WCV `NULL`** ("TBD") |
| `effective_date_note` | TEXT | yes | Mandatory when effective date is unknown |
| `revision_date_text` | TEXT | yes | `2028-07`, `2029-12` |
| `pdf_pages` | SMALLINT | yes | |
| `url`, `contact`, `status_note` | TEXT | yes | |
| `manifest_source_id` | TEXT | yes | **Soft reference** to `official.source` (`SRC-02-IFHAS`, `SRC-03-WCV`); no FK (§2.1) |
| `acquisition_state` | TEXT | no | `CHECK IN ('blocked','document_obtained')`; currently `blocked` for both |
| `local_copy_sha256` | CHAR(64) | yes | `CHECK (local_copy_sha256 IS NULL OR acquisition_state = 'document_obtained')` |

#### `clinical.rule_load`  — **[FINAL]**
**Purpose.** One row per execution of the YAML loader: what was loaded, from which files, by which code.
**PK.** `load_id BIGINT identity`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `loaded_at` | TIMESTAMPTZ | no | |
| `loader_version` | TEXT | no | |
| `bundle_sha256` | CHAR(64) | no | Hash over the canonicalised bundle |
| `file_hashes` | JSONB | no | `{path: sha256}` for each YAML file |
| `config_versions` | JSONB | no | `config_version` of IFHAS, WCV, status, open-question files |
| `git_commit` | TEXT | yes | `NULL` if loaded from a dirty tree |
| `clinical_review_status` | TEXT | no | Verbatim (`not_reviewed`) |
| `rules_loaded`, `rules_added` | INTEGER | no | |

#### `clinical.verification_status`, `clinical.evaluation_status`, `clinical.reason_code`, `clinical.guard`  — **[FINAL]**
**Purpose.** The vocabularies of `status_definitions.yaml` as **lookup tables with FKs, not ENUMs**. **Source.** that file (`config_version 1.0.0`).

| Table | PK | Rows | Columns |
|---|---|---|---|
| `verification_status` | `code` | 3 (`verified`, `reported`, `unresolved`) | `definition`, `may_drive_decisions BOOLEAN` |
| `evaluation_status` | `code` | 9 (`eligible`, `not_eligible`, `due`, `upcoming`, `overdue`, `completed`, `unknown`, `insufficient_information`, `requires_clinical_review`) | `definition`, `requires_text`, `never_inferred_from TEXT[]`, `sort_order` |
| `reason_code` | `code` | 9 | `description NULL` (the YAML lists codes only) |
| `guard` | `guard_id` | 7 (`GUARD-MISSING-DOB` … `GUARD-ITEM-UNRESOLVED`) | `when_text`, `result_status` FK → `evaluation_status`, `reason_code` FK → `reason_code`, `note` |

These are **replaced, not appended,** on each load only if the YAML `config_version` changes; evaluations reference codes, never definitions. **`refused` is not, and must not be added as, an `evaluation_status`** — see D2.
**No guard-precedence column exists** because the YAML defines none — see D17.

#### `clinical.open_question`  — **[FINAL]**
**Purpose.** The 23 open questions (19 interpretation, 2 governance, 1 data-model, 1 architecture — per the review), all `open`.
**Source.** `rules/common/open_questions.yaml`. **PK.** `oq_id TEXT`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `category`, `status` | TEXT | no | **Plain `TEXT`** (YAML-owned vocabularies; loader validates) |
| `title`, `detail` | TEXT | no | |
| `affects_raw` | TEXT[] | yes | Verbatim `affects`. **Never used as a FK** — it is heterogeneous (`[ifhas, well_child]` vs `[IFHAS-WF-INVITATION-SYSTEM]`) |
| `resolve_via` | TEXT | yes | |
| `resolution`, `resolved_on` | TEXT/DATE | yes | Added on resolution, per the YAML header. `CHECK (resolved_on IS NULL OR resolution IS NOT NULL)` |
| `first_load_id`, `last_changed_load_id` | BIGINT | no | FK → `rule_load` |

Upserted per load (this is current state, not evaluation evidence — evaluations cite rule versions, not questions).

#### `clinical.rule`  — **[FINAL]**
**Purpose.** Every versioned rule: 54 today (IFHAS 29 / WCV 25; 10 rule types). **Append-only.**
**Source.** YAML rule mappings. **PK.** `(rule_id, rule_version)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `rule_id` | TEXT | no | e.g. `IFHAS-PKG-MAMMOGRAPHY-40-75` |
| `rule_version` | TEXT | no | `CHECK ~ '^\d+\.\d+\.\d+$'` |
| `ver_major/minor/patch` | INTEGER | no | `GENERATED … STORED` from `rule_version`; **text order is not version order** (`1.10.0 < 1.9.0`) |
| `pathway` | TEXT | no | `CHECK IN ('ifhas','well_child')` |
| `rule_type` | TEXT | yes | Verbatim; the 10 types are `screening_package`, `programme_eligibility`, `workflow_timing`, `visit_schedule`, `developmental_screening_tier`, `follow_up_window`, `policy`, `programme_scope`, `programme_status`, `visit_timing`. Not `CHECK`ed (YAML-extensible); loader validates package specs |
| `standard_id` | SMALLINT | no | FK → `standard` (resolved from `source_name` + `source_version`) |
| `source_reference` | TEXT | no | Document, section/appendix, PDF page |
| `verification_status` | TEXT | no | FK → `verification_status` |
| `requires_clinical_review` | BOOLEAN | no | DEFAULT false |
| `is_authoritative` | BOOLEAN | no | **`GENERATED ALWAYS AS (verification_status = 'verified' AND NOT requires_clinical_review) STORED`** (R-C3). Today 47 true / 7 false |
| `effective_date_*`, `effective_date_note` | partial-date triple + TEXT | — | IFHAS `2025-07`; **all 25 WCV `NULL` with a mandatory note** |
| `last_reviewed` | DATE | no | |
| `description`, `notes` | TEXT | no / yes | |
| `spec` | JSONB | no | **Verbatim** |
| `history` | JSONB | yes | Verbatim (empty for all 54; present for fidelity) |
| `content_sha256` | CHAR(64) | no | Hash of the **whole canonicalised rule mapping** — metadata *and* spec |
| `yaml_path` | TEXT | no | |
| `load_id` | BIGINT | no | FK → `rule_load` (the load that first inserted this version) |
| *Projections (nullable, populated only for the types that define them):* | | | |
| `package_name`, `package_group` | TEXT | yes | `screening_package` |
| `age_min_years`, `age_max_years` | INTEGER | yes | |
| `age_as_printed` | TEXT | yes | The printed band — boundary semantics unresolved (`OQ-COMMON-AGE-CALC`) |
| `sexes` | TEXT[] | yes | `CHECK (sexes <@ ARRAY['female','male'])` |
| `frequency_type` | TEXT | yes | `CHECK IN ('recurring','once_per_lifetime')` |
| `interval_value`, `interval_unit` | INTEGER, TEXT | yes | |
| `visit_number`, `visit_id`, `recommended_age_months`, `age_band` | | yes | `visit_schedule` (`recommended_age` is stored in `spec.timing`; unit converted by the loader and asserted) |
| `instrument`, `score_min`, `score_max` | TEXT, NUMERIC | yes | `developmental_screening_tier`; `score_max NULL` = open ("8 or above") |
| `timing_value`, `timing_unit`, `timing_reference_event` | NUMERIC, TEXT, TEXT | yes | `workflow_timing`, `follow_up_window` — e.g. `15 / working_days / release of results`. **Deadlines are computed from these; they are not stored on referrals** |
| `gate_attribute` | TEXT | yes | `programme_eligibility` rules that name a patient attribute (e.g. `thiqa_member`) |

**Checks.**
- `CHECK (verification_status <> 'unresolved' OR requires_clinical_review)` — all 3 unresolved rules satisfy it today.
- Type-conditional `CHECK`s on the projections, e.g. `rule_type <> 'screening_package' OR (age_as_printed IS NOT NULL AND frequency_type IS NOT NULL AND sexes IS NOT NULL)` (mirrors the loader's package validation).
- **Append-only:** the loader role has `INSERT` only; a trigger rejects `UPDATE`/`DELETE`.
- **Hash guard (loader contract, F-25):** if `(rule_id, rule_version)` exists with a different `content_sha256`, **the load fails** (YAML was edited without a version bump). Because the hash covers metadata, flipping `verification_status` without a bump is also caught — the review proposed `spec_sha256`, which would miss that case (§10).

**Indexes.** PK; `(pathway, rule_type)`; `(rule_id, ver_major DESC, ver_minor DESC, ver_patch DESC)`; `(is_authoritative)`; GIN on `spec` only if a query needs it (not assumed).
**Views.** `v_rule_current` (highest version per `rule_id`); `v_rule_authority` (the 7 non-authoritative rules with their open questions).
**Relationships.** N ─ 1 `standard`, `rule_load`, `verification_status`; 1 ─ N `rule_condition`, `rule_item`, `rule_open_question`; 1 ─ N (from `synthetic`) evaluations, referrals, consent scope, assessments.

#### `clinical.rule_condition`  — **[FINAL]**
**Purpose.** Eligibility conditions (8 today, **7 not machine-evaluable**). Needed because `machine_evaluable = false` must force `requires_clinical_review`.
**PK.** `(rule_id, rule_version, condition_ordinal)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `kind` | TEXT | no | Verbatim (`inclusion` observed) |
| `as_printed` | TEXT | no | |
| `machine_evaluable` | BOOLEAN | no | |
| `attribute` | TEXT | yes | e.g. `smoking_history.ever_smoked` |
| `required_value` | JSONB | yes | |

`CHECK (NOT machine_evaluable OR (attribute IS NOT NULL AND required_value IS NOT NULL))`. "A rule with a non-machine-evaluable condition has `requires_clinical_review`" is a **loader validation + test** (it spans two tables), with an optional deferred constraint trigger. Lung (`OQ-IFHAS-LUNG-CRITERIA`) and liquid-biopsy criteria stay free text and are never machine-flagged.

#### `clinical.rule_item`  — **[FINAL]**; IFHAS codes **[PROVISIONAL: D10]**
**Purpose.** Assessment/follow-up items inside a rule (**174** across 14 WCV visits, 21 distinct codes; **9 unresolved**) **and the IFHAS package components** (75 strings, 37 distinct) — so results can be recorded per item and an unresolved item blocks *one item*, not the visit (scenario 25).
**PK.** `(rule_id, rule_version, category, code)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `category` | TEXT | no | `CHECK IN ('preventive_assessments','developmental_assessments','follow_up_requirements','package_component')` |
| `code` | TEXT | no | WCV: the YAML `code`. IFHAS: **derived** `slug(text)` — `Body Mass Index (BMI)` → `body_mass_index_bmi` |
| `code_origin` | TEXT | no | `CHECK IN ('yaml','derived_slug')` |
| `text_verbatim` | TEXT | yes | Required for `derived_slug`: `CHECK (code_origin = 'yaml' OR text_verbatim IS NOT NULL)`. **The raw string is never the key** |
| `ordinal` | SMALLINT | no | Position in the YAML list |
| `description` | TEXT | no | |
| `source_reference` | TEXT | no | IFHAS components inherit the package's; `inherited_from_rule BOOLEAN` records that |
| `verification_status` | TEXT | no | FK → `verification_status`. **Item-level authority is the item's own status.** IFHAS components inherit the rule's |
| `is_authoritative` | BOOLEAN | no | `GENERATED ALWAYS AS (verification_status = 'verified') STORED` |
| `condition_text` | TEXT | yes | |
| `components_text` | TEXT[] | yes | WCV nested `components`, verbatim |
| `rule_refs` | TEXT[] | yes | Verbatim |
| `notes` | TEXT | yes | |

**Checks.** "Unresolved items must reference ≥ 1 open question" spans two tables, so it is a loader rule plus a deferred constraint trigger against `rule_item_open_question`, not a `CHECK`.
**Unique.** Verified on disk: no duplicate `(rule, code)`, no code in two categories within a visit, no slug collision inside any one IFHAS package.
**Indexes.** `(rule_id, rule_version)`; `(verification_status)`.

#### `clinical.rule_open_question` and `clinical.rule_item_open_question`  — **[FINAL]**
**Purpose.** Rule-to-question relationships, derived from each rule's / item's `open_question_ids` (validated by the loader). **Not** derived from the YAML `affects` field.
- `rule_open_question`: PK `(rule_id, rule_version, oq_id)`; FKs → `rule`, `open_question`.
- `rule_item_open_question`: PK `(rule_id, rule_version, category, code, oq_id)`; FKs → `rule_item`, `open_question`.
**Indexes.** `(oq_id)` — "what does this question block?" is the main query.

### 4.3 Attribute contract (what the engine may read from a patient)

`clinical` names the attributes rules depend on; `synthetic.patient` must supply them. Nothing else may drive an eligibility result.

| Rule attribute (verbatim in YAML) | Provided by | If `NULL` |
|---|---|---|
| `date_of_birth` (every age rule; `GUARD-MISSING-DOB`) | `patient.date_of_birth` | `insufficient_information` / `missing_date_of_birth` |
| `sex` (sex-specific packages; `OQ-COMMON-SEX-ATTRIBUTE` — meaning undefined) | `patient.sex` | `insufficient_information` / `missing_sex` |
| `thiqa_member` (`IFHAS-PROG-ELIG-THIQA`) | `patient.thiqa_member` | `insufficient_information` / `missing_required_attribute` |
| `smoking_history.ever_smoked` (`IFHAS-PKG-AAA-M-65-75`) | `patient.ever_smoked` | `insufficient_information` / `missing_required_attribute` |
| *(pack-years, lung and liquid-biopsy criteria)* | **none — not machine-evaluable** | `requires_clinical_review` |

### 4.4 Rule applicability — defined before evaluation  **[PROVISIONAL: D14]**

A rule's *content* is in the YAML; **which rules are evaluated for which patient** is not, and it must be fixed *before* any evaluation exists, or "not evaluated" and "not eligible" become indistinguishable.

1. **Structural classes (from `rule_type`, deterministic).** *Gate/scope* rules (`programme_eligibility`, `programme_scope`) produce a patient-level result. *Schedulable* rules (`screening_package`, `visit_schedule`) produce a patient-level status. *Tier* rules (`developmental_screening_tier`) apply to an **assessment**, not a patient. *Timing/policy/status* rules (`workflow_timing`, `follow_up_window`, `visit_timing`, `policy`, `programme_status`) apply to **events** (results release, referral, refusal) and to engine behaviour.
2. **The database does not restrict which rule types an evaluation may cite.** `evaluation_status` must be recordable against any rule (F-28): scenario 4 (age 78) is only representable as a row against `IFHAS-PROG-AGE-CEILING` with `requires_clinical_review`. Recording `not_eligible` against every package would contradict `OQ-IFHAS-AGE-CEILING`.
3. **Absence is meaningful.** A rule that was *not applicable to a patient under the candidate policy* produces **no row**; "evaluated and not eligible" is a row with `not_eligible`. Therefore each `synthetic.evaluation_run` records the **applicability policy** it used (§5 `evaluation_run.applicability_policy`), so a run is reproducible and reviewable.
4. **Pending:** the candidate-set policy itself (gates first? which pathway is a patient a candidate for?) — D14. The design is neutral to its answer.

---

## 5. Layer C — `synthetic` schema

### 5.0 Rules for the whole layer

| # | Rule | Finding / spec |
|---|---|---|
| R-S1 | **Every row is fabricated.** `is_synthetic BOOLEAN NOT NULL DEFAULT true CHECK (is_synthetic)` on **all 18 tables including `generation_run`**; every PK matches its own table's prefix pattern (§5.6 registry) by `CHECK` | spec §1.1 |
| R-S2 | **Same-run and same-patient integrity.** Every table has `run_id` (for `generation_run` it *is* the PK) and every reference from one synthetic row to another is a **composite FK that includes `run_id`**, and — for patient-owned rows — also `patient_id` (e.g. a screening's appointment must be *that patient's* appointment in *that run*). Each referenced parent therefore carries `UNIQUE (run_id, [patient_id,] <pk>)`. The full catalogue is §5.6 | D8 |
| R-S3 | **Unknown ≠ not done.** Absence of a row never means "no screening". `history_availability` is the explicit statement of whether absence is evidence (§5, F-02) | F-02 |
| R-S4 | **Eligibility ≠ care gap.** An `eligibility_evaluation` is a rule result; a `care_gap` is a *consequence* of one (FK to it). A gap never exists without the evaluation that produced it | F-03/F-04 |
| R-S5 | **Completion ≠ refusal.** Refusal is a *documented fact with a scope*, never an evaluation status and never a completion status **[D2]** | F-05 |
| R-S6 | **Rule result ≠ AI score.** Eligibility, status, reasons and gap identity are deterministic and live on `eligibility_evaluation`/`care_gap` (rule columns). The model's `priority_score` and explanation are a separate, clearly-labelled column group with their own provenance; a model may only **order** gaps the rules already identified | F-04, RAI §3.1.6.3 |
| R-S7 | **AI recommendation ≠ human decision.** Overrides are rows in `care_gap_review`, never an edit of the score | F-04, §3.1.7.2.3 |
| R-S8 | **Booking ≠ completed care.** `appointment.status = 'attended'` does not close anything. Care is complete only when a screening/visit event row exists, linked to the appointment, with `performed_date` | F-09 |
| R-S9 | **Nothing here is a diagnosis.** There is no diagnosis column anywhere. `assessment` stores structured scores; PHQ-9/GAD-7 are stored with **no severity band** (the bands are not in the rules) | spec §3.7 |
| R-S10 | Contact data uses only fabricated values: `@example.invalid` emails, a reserved non-routable phone pattern, names suffixed `(synthetic)`, no real address | spec §1.1 |
| R-S11 | **One refusal, one place.** A refusal is recorded **once**, at the narrowest place it happened: an item refused inside a screening/visit that occurred → `component_result`; a refusal with no event (whole screening, pathway or rule) → `consent`. A care gap closed as refused cites **exactly one** of the two, and the cited row must pass its `refusal_evidence_valid` test (§2.5, §5.4–5.5). `refused` is not an evaluation, completion or attendance status | F-05 **[D2]** |

### 5.1 Provenance and runs

#### `synthetic.generation_run`  — **[APPROVED: D8]**
**Purpose.** One row per generator execution: the **single home of generator metadata and the seed**. Replaces the four per-row columns (`is_synthetic` stays per row; `generator_version`, `generation_seed`, `clinically_validated` move here) that spec §1.1 repeats on all 11 tables. **This amends spec §1.1 — see §12.2. Owner sign-off required.**
**PK.** `run_id TEXT` — `CHECK (run_id ~ '^SYNTH-RUN-[0-9]{4,}$')`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id` | TEXT | no | PK. For this table `run_id` *is* the provenance key |
| `is_synthetic` | BOOLEAN | no | `DEFAULT true CHECK (is_synthetic)` — enforced here too |
| `generator_version` | TEXT | no | Semantic version of the PulseReach generator |
| `generator_commit` | TEXT | yes | `NULL` = built from an uncommitted tree (recorded, never invented) |
| `spec_version` | TEXT | no | Version of `synthetic_data_spec.md` the run implemented (currently 0.1.0) |
| `generation_seed` | BIGINT | no | Reproducibility |
| `started_at`, `finished_at` | TIMESTAMPTZ | no / yes | `CHECK (finished_at IS NULL OR finished_at >= started_at)` |
| `rule_bundle_load_id` | BIGINT | no | FK → `clinical.rule_load` — the exact rules the run read |
| `parameters` | JSONB | no | Demographic profile and every `param_abnormal_rate_*` (arbitrary, **named as having no clinical meaning**) |
| `calibration_inputs` | JSONB | no | `[{source_file_id, sha256}]` of official files used for **shape only**. No FK (JSONB); loader validates against `official.source_file` |
| `population_profile` | TEXT | no | `CHECK IN ('mirror_scad','labelled_alternative')` — the 67/33 sex-skew choice (spec §8 item 4) |
| `n_adults`, `n_children` | INTEGER | no | `CHECK (>= 0)` |
| `clinically_validated` | BOOLEAN | no | `CHECK (NOT clinically_validated)` |
| `data_card_path` | TEXT | no | A run without a data card is incomplete (RAI §3.2.5) |

**Immutability.** After `finished_at` is set, a trigger rejects **any** `UPDATE` (the row is frozen): seed, versions, parameters and inputs can never change under data that was generated from them. The reproducibility tuple is `(generator_version, generator_commit, spec_version, generation_seed, parameters, rule_bundle_load_id)`; that equal tuples yield equal data is a **generator test**, not a database guarantee.
**Relationships.** 1 ─ N every other `synthetic` table (via `run_id`); N ─ 1 `clinical.rule_load`.
*D8 approved.* (Considered and not adopted: keeping the four columns on every table, which would let them disagree within a run.)

#### `synthetic.evaluation_run`  — **[APPROVED: D16]**
**Purpose.** One execution of the deterministic engine over a population. The review's F-03 uses `evaluation_run_id` but defines no table for it.
**PK.** `evaluation_run_id TEXT` — `CHECK (~ '^SYNTH-EVR-[0-9]{6,}$')`; `UNIQUE (run_id, evaluation_run_id)` (parent key for same-run FKs).

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id` | TEXT | no | FK → `generation_run`; `is_synthetic` as R-S1 |
| `rule_bundle_load_id` | BIGINT | no | FK → `clinical.rule_load`. May differ from the generation run's load (the engine can run later against newer rules) — both are recorded |
| `reference_date` | DATE | no | The date age is computed against (`OQ-COMMON-AGE-CALC` leaves it unspecified, so it is recorded, not assumed) |
| `age_convention` | TEXT | no | DEFAULT `'unspecified'` — stays `unspecified` while the question is open |
| `look_ahead_days` | INTEGER | yes | The `upcoming` look-ahead is "a product configuration value with no clinical meaning"; `NULL` ⇒ `upcoming` is not produced |
| `applicability_policy` | TEXT | no | Name/version of the candidate-set policy (§4.4, D14) |
| `engine_version` | TEXT | no | |
| `started_at` | TIMESTAMPTZ | no | |

Immutable once written (insert-only).

### 5.2 People, consent, facilities

#### `synthetic.patient`  — **[APPROVED: D1; PROVISIONAL: D2]** (facility FK / refusal)
**Purpose.** A fabricated person; adults and children alike (a child is a patient whose age is in `WCV-PROG-SCOPE`, linked to a guardian — not a separate table).
**Source.** Generator. **PK.** `patient_id` (`^SYNTH-PAT-[0-9]{6}$`); `UNIQUE (run_id, patient_id)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id` | TEXT | no | FK |
| `emirates_id_synthetic` | TEXT | no | `UNIQUE`; `CHECK (~ '^SYNTH-EID-')` **and** `CHECK (!~ '^784-?[0-9]{4}-?[0-9]{7}-?[0-9]$')`. **Never a structurally valid Emirates ID.** The column is never named `emirates_id` |
| `given_name`, `family_name` | TEXT | no | `CHECK (family_name ~ '\(synthetic\)$')` |
| `date_of_birth` | DATE | **yes** | `NULL` = **unknown** (scenario 6 → `insufficient_information`). Never defaulted |
| `sex` | TEXT | **yes** | `CHECK IN ('male','female')` as the standards print it (`OQ-COMMON-SEX-ATTRIBUTE`); `NULL` = unknown |
| `nationality_group` | TEXT | yes | `CHECK IN ('emirati','non_emirati','not_stated')` |
| `region_id` | SMALLINT | no | FK → `official.region` |
| `district_label` | TEXT | yes | Fictional |
| `thiqa_member` | BOOLEAN | **yes** | `NULL` is meaningful → `insufficient_information` (scenario 5) |
| `ever_smoked` | BOOLEAN | **yes** | F-07. `NULL` → `insufficient_information` for AAA. Pack-years deliberately not modelled |
| `preferred_language` | TEXT | no | `CHECK IN ('ar','en')` |
| `preferred_channel` | TEXT | no | `CHECK IN ('sms','phone','email','app')` |
| `phone_synthetic`, `email_synthetic` | TEXT | yes | `CHECK (email_synthetic ~ '@example\.invalid$')`; phone pattern fixed at implementation (non-blocking) |
| `contact_status` | TEXT | no | `CHECK IN ('valid','wrong','unverified')` (scenario 23) |
| `registered_profile_id` | TEXT | yes | Composite FK `(run_id, registered_profile_id)` → `facility_service_profile`. `NULL` = unregistered (not invented) |
| `date_of_death` | DATE | yes | `CHECK (date_of_death IS NULL OR date_of_birth IS NULL OR date_of_death >= date_of_birth)` |

**Indexes.** `(run_id)`; `(region_id)`; `(registered_profile_id)`; `(date_of_birth)`. Age is derived at evaluation time; no `age` column is stored.
**Relationships.** 1 ─ N almost everything in §5; 1 ─ N `guardian`.

#### `synthetic.guardian`  — **[FINAL]**
**Purpose.** Guardian of a child patient; child outreach addresses the guardian, never the child (scenario 19). Siblings duplicate guardian rows — accepted at ~2,000 children; **no link table**.
**PK.** `guardian_id` — `CHECK (~ '^SYNTH-GDN-[0-9]{6,}$')`. **Parent keys:** `UNIQUE (run_id, guardian_id)` and **`UNIQUE (run_id, patient_id, guardian_id)`** — the second is the one every guardian reference uses, so a guardian can only ever be cited *for the child they belong to*.

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK `(run_id, patient_id)` → `patient` (the **child**) |
| `relationship` | TEXT | no | `CHECK IN ('mother','father','legal_guardian')` |
| `given_name`, `family_name` | TEXT | no | `(synthetic)` suffix |
| `phone_synthetic`, `email_synthetic` | TEXT | yes | As patient |
| `preferred_language`, `preferred_channel` | TEXT | no | As patient |
| `contact_status` | TEXT | no | `CHECK IN ('valid','wrong','unverified')` |

**Not a constraint:** that `patient_id` is actually a child (a Well-Child-scope age, `WCV-PROG-SCOPE`). That depends on a date computed against a reference date, so it is an engine/generator test (§6.3).
**Removed vs spec §3.2:** `consent_to_contact` — it duplicated `consent`; a guardian's consent is a `consent` row with `guardian_id` (F-29).

#### `synthetic.consent`  — **[PROVISIONAL: D2]**
**Purpose.** First-class, **append-only** consent and refusal facts, and the **only** place a refusal is recorded when *no screening or visit event occurred* (whole-screening, rule- or pathway-level refusal). **AI opt-out is separate from contact opt-out** (scenario 20).
**PK.** `consent_id` — `CHECK (~ '^SYNTH-CNS-[0-9]{6,}$')`. **Parent keys:** `UNIQUE (run_id, patient_id, consent_id)`; `UNIQUE (run_id, patient_id, consent_id, refusal_evidence_valid)`; `UNIQUE (run_id, patient_id, consent_id, grants_contact)`; `UNIQUE (run_id, patient_id, consent_id, grants_ai_scoring)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK → `patient` |
| `guardian_id` | TEXT | yes | Composite FK `(run_id, patient_id, guardian_id)` → `guardian` — the guardian **of this child**. `CHECK ((applies_to = 'child_by_guardian') = (guardian_id IS NOT NULL))` |
| `consent_type` | TEXT | no | `CHECK IN ('contact','data_processing','ai_assisted_prioritisation','screening_participation')` |
| `state` | TEXT | no | `CHECK IN ('granted','withdrawn','refused')`. **`never_requested` is not a value** — absence of a row means never requested (F-29) |
| `applies_to` | TEXT | no | `CHECK IN ('self','child_by_guardian')` |
| `scope_pathway` | TEXT | yes | `CHECK IN ('ifhas','well_child')`; `NULL` = patient-wide |
| `scope_rule_id`, `scope_rule_version` | TEXT | yes | Composite FK → `clinical.rule`; both or neither: `CHECK (num_nonnulls(scope_rule_id, scope_rule_version) <> 1)`. `CHECK (scope_rule_id IS NULL OR scope_pathway IS NOT NULL)`. That the rule's `pathway` equals `scope_pathway` is a constraint trigger |
| `recorded_at` | TIMESTAMPTZ | no | |
| `recorded_by` | TEXT | no | A synthetic staff token |
| `documented_in_record`, `signature_on_file` | BOOLEAN | yes | `NULL` = not recorded (never defaulted). The evidence the refusal policy asks for |
| `refusal_reason` | TEXT | yes | `CHECK (state = 'refused' OR refusal_reason IS NULL)` |
| `refusal_evidence_valid` | BOOLEAN | no | **Generated.** `consent_type = 'screening_participation' AND state = 'refused' AND scope_pathway IS NOT NULL AND documented_in_record IS TRUE AND signature_on_file IS TRUE AND (scope_pathway <> 'well_child' OR (applies_to = 'child_by_guardian'))`. **[PROVISIONAL: D2]** — a patient-wide refusal (`scope_pathway IS NULL`) is *not* valid closing evidence for any gap; it must name a pathway or rule |
| `grants_contact` | BOOLEAN | no | **Generated.** `consent_type = 'contact' AND state = 'granted'` |
| `grants_ai_scoring` | BOOLEAN | no | **Generated.** `consent_type = 'ai_assisted_prioritisation' AND state = 'granted'` |

**Append-only** (no `UPDATE`/`DELETE`); current state = latest per `(patient, consent_type, scope_pathway, scope_rule_id)` via `v_consent_current`. A later `granted` or `withdrawn` row supersedes an earlier refusal; the earlier row is never edited.
**Provisional evidence standard (D2).** The only refusal rule encoded in the YAML is `WCV-POLICY-PARENTAL-REFUSAL` ("officially documented … including their signature"). **No IFHAS refusal rule is encoded** — the 29 IFHAS rules contain none — so applying the same documented+signature test to the IFHAS pathway is a provisional engineering choice, not a clinical fact; it lives in the one generated expression above and its twin on `component_result`.
**Indexes.** `(patient_id, consent_type, recorded_at DESC)`.
**Consent default (D18, approved — safest default).** *Unless an explicit, valid and applicable permission exists: contact is **not** permitted and person-level AI scoring is **not** run.* Three states are kept **distinct and never collapsed**: **no row** (never requested / not recorded), **`withdrawn`**, **`refused`** — all three block, but they carry different suppression reasons (§5.5) so absence is never reported as a refusal. *Valid* = a `granted` row not superseded by a later `withdrawn`/`refused` row; *applicable* = its `scope_pathway`/`scope_rule` covers the gap's pathway/rule (patient-wide `NULL` scope covers all), and for a child it is given by the child's guardian (`applies_to = 'child_by_guardian'`). Validity and applicability are time- and scope-dependent, so they are constraint triggers (§6.3); *existence and kind* of the cited row are foreign keys (§5.5). **This is a data-model default, not a statement that consent is legally required or sufficient** in any context — governance and legal review remain outstanding. The deterministic rule evaluation (`eligibility_evaluation`) is **not** gated on consent by this design; whether `data_processing` consent should gate it is a governance question not decided here.

#### `synthetic.facility_service_profile`  — **[APPROVED: D1]**
**Purpose.** A **simulated capability overlay on a real official facility** (F-20). Real facility, real coordinates; *simulated* `offers_*` flags — because no official source gives IFHAS/WCV capability (the `THIQA/BASIC/ENHANCED` columns are `N/A` in all 4,905 populated rows). **Not** a facility register.
**PK.** `profile_id` — `CHECK (~ '^SYNTH-FSP-[0-9]{6,}$')`; `UNIQUE (run_id, profile_id)`; `UNIQUE (run_id, facility_id)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id` | TEXT | no | FK |
| `facility_id` | BIGINT | no | FK → `official.facility` |
| `offers_ifhas`, `offers_wcv`, `evening_hours`, `weekend_hours` | BOOLEAN | no | **Simulated.** The UI must label them so |
| `capability_basis` | TEXT | no | `CHECK = 'simulated'` — a constant that survives export |

**Eligibility of the underlying facility** (identified, usable coordinates, operating licence, plausible kind: hospital / health centre / clinic — not pharmacy, mobile blood unit, dialysis) is enforced by the generator and a constraint trigger against `official.v_facility_usable`. **"Operating licence" is unavailable until D13 confirms the status mapping** (§3.4); until then no profile can be created that claims an operating facility.
**Open sub-question (D1):** real names beside synthetic patients, or pseudonymised names in synthetic views. Recommended: real names + a persistent "capabilities and patients are simulated" banner.

#### `synthetic.history_availability`  — **[FINAL]**
**Purpose.** The explicit statement that makes `due` and `unknown` distinguishable (F-02). Scenario 1 (no mammography on record, interval elapsed → `due`) and scenario 7 (no history at all → `unknown`) are otherwise **both zero rows**.
**PK.** `history_id` — `CHECK (~ '^SYNTH-HST-[0-9]{6,}$')`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK |
| `pathway` | TEXT | no | `CHECK IN ('ifhas','well_child')` |
| `history_status` | TEXT | no | `CHECK IN ('available','partial','not_available')` |
| `as_of_date` | DATE | no | |
| `note` | TEXT | yes | |

**Semantics.** `due` and `no_documented_screening` require `available`; `not_available` ⇒ `unknown`. **How `partial` is evaluated is unspecified** by the status definitions — D17; the engine must return `requires_clinical_review` or `unknown`, not guess. Append-only; latest `as_of_date` wins. **Unique** `UNIQUE (run_id, patient_id, pathway, as_of_date)`. **Index** `(patient_id, pathway, as_of_date DESC)`.

### 5.3 Evaluation

#### `synthetic.eligibility_evaluation`  — **[PROVISIONAL: D11 (history), D14]**
**Purpose.** **Append-only** result of applying one rule version to one patient. The deterministic engine's output — **never** an ML output. Traceable to `rule_id` + `rule_version` (status YAML: "deterministic and traceable"). The review's F-03 replaces the spec's "regenerated on evaluation".
**PK.** `evaluation_id` — `CHECK (~ '^SYNTH-EVL-[0-9]{6,}$')`. **Parent keys:** `UNIQUE (run_id, patient_id, evaluation_id)`; **`UNIQUE (run_id, patient_id, evaluation_id, rule_id, rule_version)`** (used by `care_gap` and `evaluation_reason` so they can only carry the evaluation's own rule). **Append-only** (no `UPDATE`/`DELETE`).

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK |
| `evaluation_run_id` | TEXT | no | Composite FK `(run_id, evaluation_run_id)` → `evaluation_run` (carries `reference_date`; not duplicated here, so the two cannot disagree) |
| `rule_id`, `rule_version` | TEXT | no | **Composite FK → `clinical.rule`**. Any rule type is allowed (F-28) |
| `evaluated_at` | TIMESTAMPTZ | no | |
| `evaluation_status` | TEXT | no | FK → `clinical.evaluation_status` |
| `reason_code` | TEXT | yes | FK → `clinical.reason_code`. The *reported* reason |
| `next_due_date` | DATE | yes | |

**Checks.** `CHECK (evaluation_status NOT IN ('unknown','insufficient_information','requires_clinical_review') OR reason_code IS NOT NULL)`. **No `requires_clinical_review` column** — it is exactly `evaluation_status = 'requires_clinical_review'`.
**Unique.** `UNIQUE (evaluation_run_id, patient_id, rule_id, rule_version)`.
**Indexes.** `(patient_id, rule_id, evaluated_at DESC)`; `(evaluation_status)`; `(rule_id, rule_version)`.
**View.** `v_eligibility_current` = latest per `(patient, rule_id)`.
**Volume.** ≈ 7,000 patients × ~34 rules ≈ 240 k rows per run — trivial.
**Stores `not_eligible` rows too** (evaluated, failed) so "not eligible" ≠ "never evaluated".
**Never produced:** `overdue` for any Well-Child rule while `OQ-WCV-DUE-WINDOW` is open (engine rule + test, not a `CHECK` — R-C6).

#### `synthetic.evaluation_reason`  — **[APPROVED: D16; OPEN: D17]**
**Purpose.** *All* guards that fired for an evaluation, plus item-level blocks. The status YAML defines 7 guards and **no precedence among them**; collapsing them to one `reason_code` would invent one. This table records every fired guard and lets the engine report one.
**PK.** `reason_id` — `CHECK (~ '^SYNTH-ERS-[0-9]{6,}$')` (a surrogate, so the key follows the `SYNTH-` convention); `UNIQUE (evaluation_id, reason_ordinal)`. **Append-only.**

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | |
| `evaluation_id` | TEXT | no | |
| `rule_id`, `rule_version` | TEXT | no | **Carried copy of the evaluation's rule.** Composite FK `(run_id, patient_id, evaluation_id, rule_id, rule_version)` → `eligibility_evaluation` — a reason can only cite its own evaluation's rule |
| `reason_ordinal` | SMALLINT | no | |
| `guard_id` | TEXT | yes | FK → `clinical.guard` (`NULL` for a reason with no guard, e.g. `rule_reported_not_verified`) |
| `reason_code` | TEXT | no | FK → `clinical.reason_code` |
| `item_category`, `item_code` | TEXT | yes | Composite FK `(rule_id, rule_version, item_category, item_code)` → `clinical.rule_item`; both or neither. Item-level `rule_item_unresolved` (scenario 25) |

`UNIQUE NULLS NOT DISTINCT (evaluation_id, guard_id, reason_code, item_category, item_code)` — the same reason is not recorded twice.
*D16 approved.* `evaluation_reason` records every fired guard; **guard precedence is still undefined (D17)**, so the engine's reported `reason_code` must not rely on one.

### 5.4 Care events

#### `synthetic.ifhas_screening`  — **[PROVISIONAL: D2]**
**Purpose.** An IFHAS screening **event** for one package. A row exists only for a screening that was booked/attempted; a refusal where **no screening event occurred** is *not* represented here (it is a `consent` row, R-S11).
**PK.** `screening_id` — `CHECK (~ '^SYNTH-SCR-[0-9]{6,}$')`. **Parent keys:** `UNIQUE (run_id, patient_id, screening_id)` (used by `assessment`, `referral`, `care_gap` subject); `UNIQUE (run_id, patient_id, screening_id, rule_id, rule_version)` (used by `component_result`); `UNIQUE (run_id, patient_id, screening_id, has_performed, rule_id, rule_version)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK → `patient` |
| `profile_id` | TEXT | no | Composite FK `(run_id, profile_id)` → `facility_service_profile` |
| `rule_id`, `rule_version` | TEXT | no | FK → `clinical.rule`; must be a `screening_package` (constraint trigger). A screening that cannot name its rule is invalid (spec §1.3) |
| `appointment_id` | TEXT | yes | Composite FK **`(run_id, patient_id, appointment_id, profile_id)`** → `appointment` — the booking must be *this patient's*, at *this facility profile*. `UNIQUE (appointment_id)` — one event per appointment. **Replaces `scheduled_date`** (F-09). That the appointment's `appointment_type` is `ifhas_screening` is a trigger/test |
| `performed_date` | DATE | yes | |
| `completion_status` | TEXT | no | `CHECK IN ('complete','partial','not_attended')`. **`refused` removed** — one source of truth **[D2]** |
| `results_communicated_date` | DATE | yes | §4.9.2.1: within 10 days of the initial visit |
| `journey_reported_date` | DATE | yes | §4.11.4.3: within 15 days |
| `has_abnormal_finding` | BOOLEAN | yes | From `param_abnormal_rate_*` — arbitrary, no clinical meaning |
| `has_performed` | BOOLEAN | no | **Generated** `performed_date IS NOT NULL` — the marker closing gaps may cite (§2.5) |

`CHECK (completion_status <> 'not_attended' OR performed_date IS NULL)`; `CHECK (completion_status = 'not_attended' OR performed_date IS NOT NULL)`. **`package_name` dropped** (derivable from the rule). `partial` is **derivable** from `component_result` (IFHAS §4.11.4.3); the stored status must match it (test). A screening in which every item was refused keeps whatever `completion_status` the generator assigns from what was done; refusal itself lives only on the `component_result` rows.
**Indexes.** `(patient_id, rule_id, performed_date DESC)`; `(appointment_id)`.

#### `synthetic.well_child_visit`  — **[PROVISIONAL: D2]**
**Purpose.** A Well-Child visit **event**. Non-attendance is an **event fact**, never `overdue` (scenario 17, `OQ-WCV-DUE-WINDOW`). As with screenings, a guardian's refusal where **no visit occurred** is a `consent` row (R-S11).
**PK.** `visit_id` — `CHECK (~ '^SYNTH-VIS-[0-9]{6,}$')`. **Parent keys:** `UNIQUE (run_id, patient_id, visit_id)`; `UNIQUE (run_id, patient_id, visit_id, rule_id, rule_version)`; `UNIQUE (run_id, patient_id, visit_id, has_performed, rule_id, rule_version)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK → `patient` (the child) |
| `guardian_id` | TEXT | no | Composite FK `(run_id, patient_id, guardian_id)` → `guardian` — **the child's own guardian** |
| `profile_id` | TEXT | no | Composite FK → `facility_service_profile` |
| `rule_id`, `rule_version` | TEXT | no | FK → `clinical.rule` (`WCV-VISIT-01M` … `WCV-VISIT-72M`; `visit_schedule`, constraint trigger) |
| `appointment_id` | TEXT | yes | Composite FK `(run_id, patient_id, appointment_id, profile_id)` → `appointment`; `UNIQUE` |
| `performed_date` | DATE | yes | |
| `attendance_status` | TEXT | no | `CHECK IN ('attended','not_attended')`. **`refused` and `catch_up` removed** — refusal is **[D2]**; catch-up was a status *and* a boolean |
| `is_catch_up_visit` | BOOLEAN | no | `WCV-POLICY-CATCHUP-ELIGIBILITY` §3.10.1.3 (scenario 18) |
| `has_performed` | BOOLEAN | no | **Generated** `performed_date IS NOT NULL` |

`CHECK ((attendance_status = 'attended') = (performed_date IS NOT NULL))`. **Dropped:** `scheduled_age_months` (it is the rule's recommended age), `scheduled_date` (the appointment), `assessments_completed/outstanding` (derived from `component_result`). **No `overdue` field or value.**

#### `synthetic.component_result`  — **[PROVISIONAL: D2, D10]**
**Purpose.** Per-item result for a screening or visit that **occurred** — replaces the free-text `components_*` arrays (F-06) — and the place an **item-level refusal** is recorded, with its evidence.
**PK.** `component_result_id` — `CHECK (~ '^SYNTH-CMP-[0-9]{6,}$')`. **Parent keys:** `UNIQUE (run_id, patient_id, component_result_id)`; **`UNIQUE (run_id, patient_id, component_result_id, rule_id, rule_version, refusal_evidence_valid)`** (the key `care_gap.closed_by_component_result_id` references).

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | |
| `ifhas_screening_id`, `well_child_visit_id` | TEXT | yes | `CHECK (num_nonnulls(ifhas_screening_id, well_child_visit_id) = 1)`. Composite FKs `(run_id, patient_id, ifhas_screening_id, rule_id, rule_version)` → `ifhas_screening` and `(run_id, patient_id, well_child_visit_id, rule_id, rule_version)` → `well_child_visit` — a result carries its **parent event's own rule** and patient |
| `rule_id`, `rule_version` | TEXT | no | |
| `item_category`, `item_code` | TEXT | no | Composite FK `(rule_id, rule_version, item_category, item_code)` → `clinical.rule_item` — the item must belong to that rule version |
| `result_status` | TEXT | no | `CHECK IN ('completed','refused','not_done','not_applicable')` |
| `performed_date` | DATE | yes | `CHECK (result_status <> 'completed' OR performed_date IS NOT NULL)`; `CHECK (result_status <> 'refused' OR performed_date IS NULL)` |
| `documented_in_record`, `signature_on_file` | BOOLEAN | yes | `NULL` = not recorded. `CHECK (result_status = 'refused' OR (documented_in_record IS NULL AND signature_on_file IS NULL))` — evidence flags exist only on refusals, so they cannot contradict a completed item |
| `refused_by_guardian_id` | TEXT | yes | Composite FK `(run_id, patient_id, guardian_id)` → `guardian`. **Parent/guardian refusal for a child.** `CHECK (refused_by_guardian_id IS NULL OR result_status = 'refused')`. For a Well-Child visit parent, a refusal *without* a guardian is legal data but **not valid closing evidence** (below). For an IFHAS parent it must be `NULL` (`CHECK (ifhas_screening_id IS NULL OR refused_by_guardian_id IS NULL)`) |
| `refusal_reason` | TEXT | yes | `CHECK (result_status = 'refused' OR refusal_reason IS NULL)` |
| `refusal_evidence_valid` | BOOLEAN | no | **Generated.** `result_status = 'refused' AND documented_in_record IS TRUE AND signature_on_file IS TRUE AND (well_child_visit_id IS NULL OR refused_by_guardian_id IS NOT NULL)`. **[PROVISIONAL: D2]** — same provisional evidence standard as `consent` |

**Unique.** `UNIQUE (ifhas_screening_id, item_category, item_code)` and `UNIQUE (well_child_visit_id, item_category, item_code)` (each ignores rows whose other parent is `NULL`) — one result per item per event.
**"Outstanding" is derived** (`v_item_outstanding` = rule items − recorded results, **excluding** items whose `verification_status <> 'verified'`, which are unresolved, not outstanding). **Measured values are not stored in the MVP.**
**Contradiction rule (constraint trigger or engine test):** a `refused` result for rule R is rejected if the patient's *current* `consent` for the same rule/pathway scope is also `refused` (the refusal would be recorded twice — R-S11); and a `completed` result is flagged if a current valid refusal consent for the same scope precedes it with no later `granted`/`withdrawn` row.

#### `synthetic.assessment`  — **[FINAL]**
**Purpose.** Scored instruments as structured results (M-CHAT-R, IDAQ, PHQ-9, GAD-7).
**PK.** `assessment_id` — `CHECK (~ '^SYNTH-ASM-[0-9]{6,}$')`. **Parent key:** `UNIQUE (run_id, patient_id, assessment_id)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | |
| `ifhas_screening_id`, `well_child_visit_id` | TEXT | yes | `CHECK (num_nonnulls(…) = 1)` — two FKs, **not** a polymorphic `encounter_id`, and no `encounter` supertype (F-08). Composite FKs `(run_id, patient_id, <event id>)` → the event, so an assessment belongs to *its patient's* event |
| `instrument` | TEXT | no | `CHECK IN ('M-CHAT-R','IDAQ','PHQ-9','GAD-7')` |
| `instrument_version` | TEXT | yes | |
| `administered_date` | DATE | no | |
| `raw_score` | NUMERIC | yes | |
| `item_responses` | JSONB | yes | Item-level answers; IDAQ's referral logic needs them |
| `rule_id`, `rule_version` | TEXT | yes | Composite FK → `clinical.rule`: the tier/referral rule applied (`WCV-MCHATR-LOW/MODERATE/HIGH`, `WCV-IDAQ-REFERRAL`). **`NULL` for PHQ-9/GAD-7.** `CHECK (num_nonnulls(rule_id, rule_version) <> 1)` |

**Checks.** `CHECK (instrument NOT IN ('PHQ-9','GAD-7') OR rule_id IS NULL)` — no severity band is ever assigned. The band is **derived** from the rule (not stored). There is **no `is_diagnosis` column**; there is no diagnosis anywhere (R-S9). That the rule's `instrument` matches the assessment's `instrument` is a loader/engine test (uses the rule's `instrument` projection).

#### `synthetic.referral`  — **[FINAL]**
**Purpose.** The first-class, time-bounded referral obligation the rules define (`WCV-MCHATR-HIGH` 2 weeks + PHC follow-up after 1 month; `WCV-IDAQ-REFERRAL`; `WCV-FU-REFERRAL-INITIATION-7D`; `WCV-FU-SPECIALIST-EVALUATION-2-4W`; `IFHAS-WF-REFERRAL-15WD`). Without it `referral_not_initiated` cannot be computed (F-01; scenarios 9, 13, 14, 16).
**PK.** `referral_id` — `CHECK (~ '^SYNTH-REF-[0-9]{6,}$')`. **Parent keys:** `UNIQUE (run_id, patient_id, referral_id)`; `UNIQUE (run_id, patient_id, referral_id, is_initiated)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | |
| `ifhas_screening_id`, `well_child_visit_id`, `assessment_id` | TEXT | yes | `CHECK (num_nonnulls(…) = 1)`. Composite FKs `(run_id, patient_id, <id>)` → the source row — **the referral's patient is its source's patient** |
| `trigger_rule_id`, `trigger_rule_version` | TEXT | no | Composite FK → `clinical.rule`. That this rule actually defines a referral action or window (its `spec.actions` or `timing_*` projection) is a loader/engine test — **no referral-rule type list is hard-coded** |
| `rule_action_ordinal` | SMALLINT | yes | Which `spec.actions[n]` (a high M-CHAT-R yields **two** referrals). `UNIQUE NULLS NOT DISTINCT (ifhas_screening_id, well_child_visit_id, assessment_id, trigger_rule_id, trigger_rule_version, rule_action_ordinal)` |
| `referral_target` | TEXT | no | **As printed.** The Appendix 8 mapping is not encoded and not invented |
| `target_profile_id` | TEXT | yes | Composite FK `(run_id, profile_id)` → `facility_service_profile` |
| `trigger_date` | DATE | no | The rule's `reference_event` (results release / assessment) |
| `initiated_date`, `completed_date` | DATE | yes | |
| `status` | TEXT | no | `CHECK IN ('pending','initiated','completed','declined','cancelled')` |
| `is_initiated` | BOOLEAN | no | **Generated** `initiated_date IS NOT NULL` — the marker a closing gap may cite |

**Checks.** `CHECK (initiated_date IS NULL OR initiated_date >= trigger_date)`; `CHECK (completed_date IS NULL OR (initiated_date IS NOT NULL AND completed_date >= initiated_date))`; `CHECK (status NOT IN ('initiated','completed') OR initiated_date IS NOT NULL)`; `CHECK (status <> 'completed' OR completed_date IS NOT NULL)`.
**Deadlines are derived** from `rule.timing_*` / `spec.actions` and, for working days, the calendar (D12); never stored. **`declined` is a referral outcome, not a documented refusal** — whether a declined referral is a "refusal" needing evidence is a **D2 sub-question** and `care_gap` therefore forbids `closed_refused` for referral gaps (§5.5).

### 5.5 Care gaps, review, booking, outreach

#### `synthetic.care_gap`  — **[PROVISIONAL: D2]**
**Purpose.** The prioritisation surface. **A care gap is produced by rules, never by a model** (spec §3.8). Three separated column groups on one row — **(1) rule fact, (2) lifecycle with closing evidence, (3) AI scoring** — so the distinction survives in the data. Human overrides are *not* here; they are rows in `care_gap_review`.
**PK.** `care_gap_id` — `CHECK (~ '^SYNTH-GAP-[0-9]{6,}$')`. **Parent keys:** `UNIQUE (run_id, care_gap_id)`; `UNIQUE (run_id, patient_id, care_gap_id)`.

**Group 1 — rule fact**

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK → `patient` |
| `evaluation_id` | TEXT | no | **A gap cannot exist without the evaluation that produced it** (R-S4) |
| `rule_id`, `rule_version` | TEXT | no | **Carried copy of the evaluation's rule.** Composite FK `(run_id, patient_id, evaluation_id, rule_id, rule_version)` → `eligibility_evaluation`. It exists so every closing-evidence FK below can prove *same rule* |
| `gap_type` | TEXT | no | `CHECK IN ('no_documented_screening','interval_elapsed','partial_completion','referral_not_initiated','visit_not_attended')`. `never_screened` is renamed; `no_documented_screening` is permitted only where history is `available` (test) |
| `subject_ifhas_screening_id`, `subject_well_child_visit_id`, `subject_referral_id` | TEXT | yes | `CHECK (num_nonnulls(…) <= 1)`; `partial_completion` ⇔ screening subject; `visit_not_attended` ⇔ visit subject; `referral_not_initiated` ⇔ referral subject (`CHECK`s). Composite FKs `(run_id, patient_id, <id>)` → the subject |
| `identified_date` | DATE | no | |

`UNIQUE NULLS NOT DISTINCT (evaluation_id, gap_type, subject_ifhas_screening_id, subject_well_child_visit_id, subject_referral_id)` — the same gap is not identified twice.

**Group 2 — lifecycle and closing evidence**

| Column | Type | Null | Notes |
|---|---|---|---|
| `status` | TEXT | no | `CHECK IN ('open','closed_completed','closed_refused','suppressed','superseded')` |
| `closed_date` | DATE | yes | `CHECK ((status IN ('closed_completed','closed_refused')) = (closed_date IS NOT NULL))` |
| `suppression_reason` | TEXT | yes | `CHECK ((status = 'suppressed') = (suppression_reason IS NOT NULL))` |
| `closed_by_ifhas_screening_id` | TEXT | yes | **Completion evidence** |
| `closed_by_well_child_visit_id` | TEXT | yes | Completion evidence |
| `closed_by_referral_id` | TEXT | yes | Completion evidence |
| `closed_by_component_result_id` | TEXT | yes | **Refusal evidence — item level:** *exactly which* component result caused the closure |
| `closed_by_consent_id` | TEXT | yes | **Refusal evidence — no event:** whole-screening, rule- or pathway-level refusal, including a guardian's refusal for a child |
| `completion_evidence_marker` | BOOLEAN | no | **Generated** `CASE WHEN num_nonnulls(closed_by_ifhas_screening_id, closed_by_well_child_visit_id, closed_by_referral_id) > 0 THEN TRUE END` |
| `refusal_evidence_marker` | BOOLEAN | no | **Generated** `CASE WHEN num_nonnulls(closed_by_component_result_id, closed_by_consent_id) > 0 THEN TRUE END` |

*Closing-evidence rules (all `CHECK`/FK, none behavioural):*
1. `CHECK ((status = 'closed_completed' AND num_nonnulls(closed_by_ifhas_screening_id, closed_by_well_child_visit_id, closed_by_referral_id) = 1) OR (status <> 'closed_completed' AND num_nonnulls(closed_by_ifhas_screening_id, closed_by_well_child_visit_id, closed_by_referral_id) = 0))`
2. `CHECK ((status = 'closed_refused' AND num_nonnulls(closed_by_component_result_id, closed_by_consent_id) = 1) OR (status <> 'closed_refused' AND num_nonnulls(closed_by_component_result_id, closed_by_consent_id) = 0))` — **a gap cannot be closed as refused without exactly one piece of refusal evidence, and cannot carry refusal evidence while open.**
3. Composite FKs (evidence-marker pattern, §2.5) — each resolves only to the **same run, same patient, same rule**, and only to a *valid* row:
   - `(run_id, patient_id, closed_by_ifhas_screening_id, completion_evidence_marker, rule_id, rule_version)` → `ifhas_screening(run_id, patient_id, screening_id, has_performed, rule_id, rule_version)` — the screening was **performed**; likewise for `well_child_visit`.
   - `(run_id, patient_id, closed_by_referral_id, completion_evidence_marker)` → `referral(run_id, patient_id, referral_id, is_initiated)` — the referral was **initiated**.
   - `(run_id, patient_id, closed_by_component_result_id, rule_id, rule_version, refusal_evidence_marker)` → `component_result(run_id, patient_id, component_result_id, rule_id, rule_version, refusal_evidence_valid)` — a **refused, documented, signed** component of an event for **this gap's rule** (a guardian is required for a child's visit).
   - `(run_id, patient_id, closed_by_consent_id, refusal_evidence_marker)` → `consent(run_id, patient_id, consent_id, refusal_evidence_valid)` — a documented, signed, **pathway- or rule-scoped** refusal (child ⇒ by guardian). That the consent's scope covers *this gap's rule* (`scope_rule` = the gap's rule, or, if rule-less, `scope_pathway` = the rule's pathway) is a **constraint trigger**, because "rule-level or else pathway-level" is not expressible as one FK.
4. `UNIQUE (closed_by_component_result_id)` — one refused item closes at most one gap. (A consent may close several gaps: a pathway-level refusal legitimately covers several rules.)
5. `CHECK (status <> 'closed_refused' OR gap_type <> 'referral_not_initiated')` **[PROVISIONAL: D2 sub-question]** — until it is decided whether a declined referral is a refusal needing documented evidence, a referral gap cannot be closed as refused. This is a conservative gate, not a clinical rule.
6. `CHECK (status <> 'closed_completed' OR gap_type <> 'no_documented_screening' OR closed_by_ifhas_screening_id IS NOT NULL OR closed_by_well_child_visit_id IS NOT NULL)` is **not** used: which events close which gap type is engine behaviour and is not invented here.

**Group 3 — AI scoring (the model's output; never rule output)**

| Column | Type | Null | Notes |
|---|---|---|---|
| `priority_score` | NUMERIC | yes | `NULL` = not scored |
| `priority_explanation` | TEXT | yes | `CHECK (priority_score IS NULL OR priority_explanation IS NOT NULL)` (RAI §3.1.6.3) |
| `scored_by_model_version` | TEXT | yes | `CHECK ((priority_score IS NULL) = (scored_by_model_version IS NULL))` |
| `scored_at` | TIMESTAMPTZ | yes | `CHECK ((priority_score IS NULL) = (scored_at IS NULL))` |
| `scoring_consent_id` | TEXT | yes | **The permission relied on (D18).** Composite FK `(run_id, patient_id, scoring_consent_id, scoring_consent_marker)` → `consent(run_id, patient_id, consent_id, grants_ai_scoring)` — can only be an `ai_assisted_prioritisation` / `granted` row of this patient. **`CHECK (priority_score IS NULL OR scoring_consent_id IS NOT NULL)` — no score exists without explicit permission** |
| `scoring_consent_marker` | BOOLEAN | no | **Generated** `CASE WHEN scoring_consent_id IS NOT NULL THEN TRUE END` |
| `scoring_suppressed_reason` | TEXT | yes | Why a gap was **not** scored. Reserved values, each trigger-checked against the actual consent history: `'no_ai_permission_recorded'` (**no row** — the default), `'ai_consent_withdrawn'`, `'ai_consent_refused'`; other documented reasons allowed. `NULL` = simply not yet scored. `CHECK (scoring_suppressed_reason IS NULL OR priority_score IS NULL)`. Rule evaluation and gap identity are unaffected |

**AI/human separation (structural).** Group 3 columns are writable **only** by the scoring role (column-level `GRANT UPDATE`); clinicians have `INSERT` on `care_gap_review` and **no** `UPDATE` on `care_gap`; the engine role writes groups 1–2. A human override never edits the score, and a re-score never edits a review. Groups 1–2 never read Group 3.
**Dropped:** `pathway` (derivable from the rule); `clinician_reviewed`, `clinician_override`, `override_reason` (→ `care_gap_review`).
**Indexes.** `(status) WHERE status = 'open'`; `(patient_id)`; `(evaluation_id)`.
**View.** `v_care_gap_effective_priority`: latest human override if any, else the AI score — both visible, neither overwritten.
**Cross-table rules (constraint trigger or engine test):** the evaluation is in a gap-yielding status; the cited AI permission is still current and applicable (not superseded by a later `withdrawn`/`refused`; scope covers this gap) as of `scored_at`;
**Not modelled (unresolved issue U1):** the model's *previous* scores — a re-score overwrites Group 3.

#### `synthetic.care_gap_review`  — **[FINAL]**
**Purpose.** **Append-only** human decisions and overrides: the audit trail (§3.1.7.2.3; scenario 27). One nullable override column records only the *last* override.
**PK.** `review_id` — `CHECK (~ '^SYNTH-REV-[0-9]{6,}$')`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `care_gap_id` | | no | Composite FK |
| `reviewer` | TEXT | no | A synthetic clinician token |
| `action` | TEXT | no | `CHECK IN ('confirmed','priority_overridden','dismissed')` — illustrative vocabulary, to be fixed at implementation |
| `previous_priority`, `new_priority` | NUMERIC | yes | `CHECK (action <> 'priority_overridden' OR new_priority IS NOT NULL)` |
| `reason` | TEXT | no | `CHECK (length(btrim(reason)) > 0)` — an override without a reason is not an override |
| `reviewed_at` | TIMESTAMPTZ | no | |

**Index** `(care_gap_id, reviewed_at DESC)`. **Append-only** (no `UPDATE`/`DELETE`). Composite FK `(run_id, care_gap_id)` → `care_gap`. `previous_priority` is whatever the effective priority was when the human acted (the AI score or the prior override); it is a recorded fact, not a foreign key. Clinicians retain decision authority (RAI §3.1.7.2.2).

#### `synthetic.appointment`  — **[FINAL]**
**Purpose.** A booking. **A booking is not completed care** (R-S8): the screening/visit event row is the care; the appointment is the slot.
**PK.** `appointment_id` — `CHECK (~ '^SYNTH-APT-[0-9]{6,}$')`. **Parent keys:** `UNIQUE (run_id, patient_id, appointment_id)`; **`UNIQUE (run_id, patient_id, appointment_id, profile_id)`** (used by both event tables).

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK |
| `profile_id` | TEXT | no | Composite FK |
| `care_gap_id` | TEXT | yes | Composite FK `(run_id, patient_id, care_gap_id)` → `care_gap` — the gap must be this patient's; `NULL` for a booking that did not originate from a gap |
| `appointment_type` | TEXT | no | `CHECK IN ('ifhas_screening','well_child_visit','referral_visit','other')` |
| `scheduled_datetime` | TIMESTAMPTZ | no | Stored UTC; scheduled in `Asia/Dubai` |
| `slot_type` | TEXT | no | `CHECK IN ('weekday','evening','weekend')` (WCV §3.9.1.1). **Kept stored** — see §10: the review calls it derivable, but facility hours are not modelled and "weekend" is undefined (D12) |
| `status` | TEXT | no | `CHECK IN ('scheduled','attended','no_show','cancelled_by_patient','cancelled_by_facility','rescheduled')` |
| `booked_via` | TEXT | no | |

**Dropped:** `reminder_count` (a count of `outreach_event` rows). **Test:** `status = 'attended'` with no linked event row is a data-quality error. **Indexes.** `(patient_id, scheduled_datetime)`; `(care_gap_id)`; `(profile_id, scheduled_datetime)`.

#### `synthetic.outreach_event`  — **[APPROVED: D18]**
**Purpose.** Invitations, reminders, recalls (IFHAS §4.7.1: first screening, rescreening, **and recall for positive and insufficient results**). Outreach is attributable to the gap that justified it and, if it worked, to the booking it produced (the impact measure).
**PK.** `outreach_id` — `CHECK (~ '^SYNTH-OUT-[0-9]{6,}$')`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | |
| `care_gap_id` | TEXT | no | Composite FK `(run_id, patient_id, care_gap_id)` → `care_gap` — every contact traces to *this patient's* rule-identified need |
| `guardian_id` | TEXT | yes | Composite FK `(run_id, patient_id, guardian_id)` → `guardian` — **only the child's own guardian**. `CHECK ((recipient = 'guardian') = (guardian_id IS NOT NULL))` |
| `recipient` | TEXT | no | `CHECK IN ('patient','guardian')` |
| `event_type` | TEXT | no | `CHECK IN ('invitation','reminder','recall_positive_result','recall_insufficient_result','referral_follow_up')` |
| `channel` | TEXT | no | `CHECK IN ('sms','phone','email','app')` |
| `sent_datetime` | TIMESTAMPTZ | yes | `NULL` for suppressed events: `CHECK ((delivery_status = 'suppressed') = (sent_datetime IS NULL))` |
| `delivery_status` | TEXT | no | `CHECK IN ('queued','delivered','failed','suppressed')`. **No separate `suppressed` boolean** |
| `suppression_reason` | TEXT | yes | `CHECK ((delivery_status = 'suppressed') = (suppression_reason IS NOT NULL))`. Reserved consent values, trigger-checked against the actual history: **`'no_contact_permission_recorded'`** (no row — the default), `'contact_consent_withdrawn'`, `'contact_consent_refused'`; also `'patient_deceased'` and other documented reasons |
| `contact_consent_id` | TEXT | yes | **The permission relied on (D18).** Composite FK `(run_id, patient_id, contact_consent_id, contact_consent_marker)` → `consent(run_id, patient_id, consent_id, grants_contact)` — can only be a **`contact` / `granted`** row of this patient. **`CHECK (delivery_status = 'suppressed' OR contact_consent_id IS NOT NULL)` — an outreach event that is not suppressed must cite explicit permission.** `NULL` only on suppressed events |
| `contact_consent_marker` | BOOLEAN | no | **Generated** `CASE WHEN contact_consent_id IS NOT NULL THEN TRUE END` |
| `response` | TEXT | yes | `CHECK IN ('no_response','booked','declined','opted_out','wrong_contact')`. A `declined` **response** is *not* a documented refusal (D2); `wrong_contact` is delivery failure, **not** declined (scenario 23) |
| `appointment_id` | TEXT | yes | Composite FK `(run_id, patient_id, appointment_id)` → `appointment`. `CHECK (appointment_id IS NULL OR response = 'booked')` |
| `triggered_by_ai_score` | BOOLEAN | no | Lets outreach driven by a model score alone be found |
| `clinician_approved_by` | TEXT | yes | `NULL` is **representable** so the human-oversight requirement (§3.1.1.2) can be tested rather than assumed |
| `message_template_id` | TEXT | yes | |

**Consent-to-outreach enforcement — what is structural and what is not.**
- *Structural:* the consent row cited is a real, same-patient, `contact`/`granted` row; a guardian recipient is the child's own guardian; the contact traces to the patient's own gap.
- *Constraint trigger (time-dependent, so not an FK):* the cited consent is **current and applicable** as of `sent_datetime` — not superseded by a later `withdrawn`/`refused` row, scope covering the gap's pathway/rule, and, for a guardian recipient, `consent.guardian_id = outreach_event.guardian_id` with `applies_to = 'child_by_guardian'`; a suppression reason that names a consent state must match the real history; a deceased patient's events must be `suppressed`.
- *Default (D18, approved):* with **no** applicable permission the event is `suppressed` (`no_contact_permission_recorded`) — it is never sent and never silently dropped, and it is never reported as a refusal or withdrawal.

**Indexes.** `(care_gap_id)`; `(patient_id, sent_datetime)`; `(appointment_id)`; `(contact_consent_id)`.
Insert-only; `response`/`appointment_id` may be updated once by the response handler (the only mutable columns).

### 5.6 Key and reference catalogue (audit of all 18 synthetic tables)

**A. Identifier registry** — every PK has a `CHECK (<pk> ~ '^SYNTH-<CODE>-[0-9]{N,}$')`; `N` = 6 except `RUN` (4).

| Table | Code | Table | Code | Table | Code |
|---|---|---|---|---|---|
| `generation_run` | RUN | `eligibility_evaluation` | EVL | `referral` | REF |
| `evaluation_run` | EVR | `evaluation_reason` | ERS | `care_gap` | GAP |
| `patient` | PAT | `ifhas_screening` | SCR | `care_gap_review` | REV |
| `guardian` | GDN | `well_child_visit` | VIS | `appointment` | APT |
| `consent` | CNS | `component_result` | CMP | `outreach_event` | OUT |
| `facility_service_profile` | FSP | `assessment` | ASM | `history_availability` | HST |

All 18 also carry `run_id` (for `generation_run`, the PK) and `is_synthetic CHECK (is_synthetic)`.

**B. Synthetic → synthetic references** (every one includes `run_id`; patient-owned rows also include `patient_id`).

| Child (columns) | Parent | Parent key used |
|---|---|---|
| `evaluation_run.run_id` | `generation_run` | `run_id` |
| `facility_service_profile.run_id` | `generation_run` | `run_id` |
| `patient (run_id, registered_profile_id)` | `facility_service_profile` | `(run_id, profile_id)` |
| `guardian`, `consent`, `history_availability`, `eligibility_evaluation`, `ifhas_screening`, `well_child_visit`, `appointment`, `care_gap` — `(run_id, patient_id)` | `patient` | `(run_id, patient_id)` |
| `consent`, `well_child_visit`, `component_result.refused_by_guardian_id`, `outreach_event` — `(run_id, patient_id, guardian_id)` | `guardian` | `(run_id, patient_id, guardian_id)` |
| `eligibility_evaluation (run_id, evaluation_run_id)` | `evaluation_run` | `(run_id, evaluation_run_id)` |
| `evaluation_reason`, `care_gap` — `(run_id, patient_id, evaluation_id, rule_id, rule_version)` | `eligibility_evaluation` | same five |
| `ifhas_screening`, `well_child_visit` — `(run_id, patient_id, appointment_id, profile_id)` | `appointment` | same four |
| `appointment`, `ifhas_screening`, `well_child_visit`, `referral.target_profile_id` — `(run_id, profile_id)` | `facility_service_profile` | `(run_id, profile_id)` |
| `component_result`, `assessment`, `referral`, `care_gap` subject — event id with `(run_id, patient_id)` [+ `rule_id, rule_version` for `component_result`] | `ifhas_screening` / `well_child_visit` | `(run_id, patient_id, id[, rule_id, rule_version])` |
| `referral.assessment_id` | `assessment` | `(run_id, patient_id, assessment_id)` |
| `care_gap.scoring_consent_id` `(run_id, patient_id, scoring_consent_id, marker)` | `consent` | marker key (D18) |
| `care_gap` closing evidence (5 columns, §5.5)
| `appointment`, `outreach_event` — `(run_id, patient_id, care_gap_id)` | `care_gap` | `(run_id, patient_id, care_gap_id)` |
| `care_gap_review (run_id, care_gap_id)` | `care_gap` | `(run_id, care_gap_id)` |
| `outreach_event (run_id, patient_id, appointment_id)` / `(…, contact_consent_id, marker)` | `appointment` / `consent` | `(run_id, patient_id, appointment_id)` / marker key |

**C. Append-only or immutable tables** (no `UPDATE`/`DELETE` for any application role): `generation_run` (after `finished_at`), `evaluation_run`, `eligibility_evaluation`, `evaluation_reason`, `consent`, `history_availability`, `care_gap_review`, `outreach_event` (except the one-shot response columns). Mutable by design: `care_gap` (engine: groups 1–2; scoring role: group 3 only), `appointment` (status), `referral` (status and dates), `ifhas_screening` / `well_child_visit` / `component_result` (inserted by the generator; corrections are generator re-runs, not edits). `patient`, `guardian`, `facility_service_profile` are fixed per run.

**D. What `NULL` means** (so no `NULL` is ambiguous): `patient.date_of_birth`/`sex`/`thiqa_member`/`ever_smoked` = unknown; `registered_profile_id` = unregistered; `consent.documented_in_record`/`signature_on_file` = not recorded; `consent.scope_pathway` = patient-wide; `consent.guardian_id` = self; `outreach_event.contact_consent_id` = no consent row relied on; `care_gap.priority_score` = not scored; `referral.initiated_date` = not initiated; `appointment.care_gap_id` = not gap-driven; `ifhas_screening.appointment_id` = not booked through the system. No column uses a sentinel value.

---

## 6. Constraint, audit and safety summary

### 6.1 Synthetic-data safety — mechanically enforced

| Control | Mechanism |
|---|---|
| Every row marked | `is_synthetic CHECK (is_synthetic)` + `run_id` on all 18 tables |
| Unmistakable identifiers | `SYNTH-` PK `CHECK` on all tables; `emirates_id_synthetic` format check (must **fail** the real 784-… format); `@example.invalid`; `(synthetic)` name suffix |
| No clinical truth fabricated | Clinical thresholds are read only from `clinical.*` by FK; `CHECK` forbids a band on PHQ-9/GAD-7; no diagnosis column; `overdue` not produced for Well-Child (engine + test) |
| Unknown stays unknown | Nullable `date_of_birth`, `sex`, `thiqa_member`, `ever_smoked`, `registered_profile_id`; `history_availability`; no `NOT NULL DEFAULT` that invents a value |
| Facility overlay is labelled | `capability_basis = 'simulated'`; `official.facility` has no synthetic columns |
| Residency | `OQ-GOV-DATA-RESIDENCY` is open: no real patient data in any environment. `synthetic` is structurally separate; a real-data path would require a different schema, not a flag |
| Deletion safety | `ON DELETE RESTRICT` everywhere; synthetic runs removed by an explicit job in reverse-dependency order, never by cascade |

### 6.2 Audit and versioning

| Object | Audit mechanism |
|---|---|
| Rules | Append-only `(rule_id, rule_version)`; `content_sha256`; `rule_load` |
| Evaluations | Append-only; `evaluation_run` (reference date, rule bundle, policy, engine) |
| Consent | Append-only; current by view |
| Care-gap overrides | Append-only `care_gap_review`, reason mandatory |
| AI scores | `scored_by_model_version`, `scored_at`, explanation, on the gap; overrides never edit them |
| Outreach | Per-event rows; approval and AI trigger recorded |
| Official data | `source_file` SHA-256 + retrieval; `observation.source_file_id`; `quality_flag` |

### 6.3 Where integrity is *not* a database constraint

These need a loader validation, constraint trigger or engine test — stated so nothing is assumed enforced. **Triggers are used only where a rule is time-dependent or spans an either/or scope that no FK can express.**

| # | Rule | Mechanism |
|---|---|---|
| 1 | A member's `dimension_type` matches its observation column; an observation's `source_file` is a detail file of its indicator | Loader assertion + test |
| 2 | Leaves reconcile to aggregates (R-O2) | Loader test |
| 3 | `machine_evaluable = false` ⇒ parent rule `requires_clinical_review`; unresolved rules/items cite ≥ 1 open question | Loader validation + deferred trigger |
| 4 | `ifhas_screening.rule` is a `screening_package`; `well_child_visit.rule` is a `visit_schedule`; the appointment's `appointment_type` matches the event | Constraint trigger |
| 5 | Facility-profile eligibility (identified, usable coordinates, **operating licence — unavailable until D13**, plausible kind) | Constraint trigger against `official.v_facility_usable` |
| 6 | Consent scope covers a refusal-closed gap's rule (`scope_rule` = gap rule, else `scope_pathway` = rule's pathway); a consent's `scope_pathway` equals its rule's pathway | Constraint trigger |
| 7 | **D18 default:** outreach sent and AI score produced only under a **current, applicable, explicit** permission (cited by FK); suppression/suppressed-scoring reasons match the real consent history (`no row` ≠ `withdrawn` ≠ `refused`); deceased ⇒ suppressed | Constraint trigger (time- and scope-dependent) |
| 8 | No refusal recorded twice (consent **and** component for one scope); no completion after a current valid refusal without a superseding consent row | Constraint trigger / engine test |
| 9 | `partial` completion equals the derived value; an appointment marked `attended` has an event row; a gap-yielding evaluation status backs every gap | Engine test |
| 10 | A referral's `trigger_rule` defines an action or window; an assessment's rule `instrument` matches | Loader/engine test |
| 11 | `guardian.patient_id` is a child in Well-Child scope (`WCV-PROG-SCOPE`) | Generator/engine test (needs a reference date) |
| 12 | No FK crosses the dependency rule (§2.1) | Schema test over `pg_constraint` / `pg_depend` |
| 13 | Equal reproducibility tuple ⇒ equal data (`generation_run`) | Generator test |

---

## 7. MVP data lifecycle

AI is used in **exactly one step (8)**. Everything else is deterministic code, a seeded random generator (steps 4–5, not AI), or a person.

| # | Stage | What happens | Writes | Deterministic / AI / human |
|---|---|---|---|---|
| 1 | **Official source acquisition** | Fetch scripts retrieve SCAD API and SDI files into `data/raw/`; SHA-256 recorded; `source_manifest.yaml` states what is and is not held | `official.source`, `official.source_file` | Deterministic scripts. Blocked sources stay `blocked` |
| 2 | **Reference-data validation and ingestion** | Parse API JSON; classify dimension members; derive `row_role`; flag 3422; detect (not apply) age-label corruption; load facilities from raw GeoJSON through the repair function; register unseen licence statuses as `unreviewed`; run reconciliation tests | `official.*` | Deterministic. Fails loudly on a shape it does not recognise |
| 3 | **Clinical YAML loading and version validation** | Loader validates YAML (existing rules); DB loader inserts new `(rule_id, rule_version)`; **fails if an existing version's hash changed**; loads open questions, vocabularies, guards | `clinical.*` | Deterministic. YAML is the only authoring path |
| 4 | **Synthetic population generation** | Seeded generator reads `clinical` rules and `official` aggregates for *shape only*; produces patients, guardians, consent, facility overlays; every row `SYNTH-` marked | `synthetic.generation_run`, `patient`, `guardian`, `consent`, `facility_service_profile` | Seeded pseudo-random, **not AI**; reproducible from run seed |
| 5 | **History availability and patient attributes** | Generator decides, per patient and pathway, whether history is `available`, `partial`, `not_available`; generates prior events consistent with it; leaves unknown attributes `NULL` on purpose | `history_availability`, prior `ifhas_screening` / `well_child_visit` / `component_result` / `assessment` | Seeded generator. Must produce every scenario in spec §5 |
| 6 | **Deterministic clinical rule evaluation** | Engine applies the applicability policy (§4.4), then each applicable rule version to each patient with guards first; records status, reason(s), next due date | `evaluation_run`, `eligibility_evaluation`, `evaluation_reason` | **Deterministic only.** No model may decide eligibility or frequency (status YAML) |
| 7 | **Care-gap identification** | A gap is created from an evaluation in a gap-yielding status, with a gap type and subject; unknown/insufficient/review statuses do **not** create "not screened" gaps | `care_gap` (rule-fact and lifecycle columns) | **Deterministic.** A model never creates a gap |
| 8 | **AI-assisted prioritisation and explanation** | A model **orders** the already-identified gaps and writes an explanation — **only for patients with an explicit, current, applicable `ai_assisted_prioritisation` permission (D18)**; otherwise the gap is left unscored (`no_ai_permission_recorded` / `ai_consent_withdrawn` / `ai_consent_refused`). A clinician may confirm or override | `care_gap` (scoring group), `care_gap_review` | **AI (ordering + explanation only)** with **human** review. Never changes gap identity, eligibility or status. Labelled a technical scaffold where NHANES shaped any input (RAI §3.1.5.1.1). Aggregate dashboard counts are not person-level scoring |
| 9 | **Consent-aware outreach** | Outreach proceeds **only** under an explicit, current, applicable `contact` permission (D18); with none, the event is recorded as `suppressed` with the reason that matches the history (no row / withdrawn / refused); child outreach goes to the child's guardian; record approval and whether an AI score triggered it | `outreach_event` | Deterministic checks; approval is **human** |
| 10 | **Appointment booking** | Patient/guardian responds; a slot at a profile facility is booked (capability and geography routing); outreach linked to the booking | `appointment`, `outreach_event.appointment_id` | Deterministic. **Booking is not care** |
| 11 | **Screening or visit completion** | Event row created and linked to the appointment; per-item results; assessments scored; refusal recorded as a documented fact; `partial` derived; gap closed with its evidence | `ifhas_screening`, `well_child_visit`, `component_result`, `assessment`, `care_gap` status | Deterministic from generator output; refusal via `consent` (no event) or `component_result` (item in an event) per D2, and a gap closes as refused only on valid evidence (§5.5) |
| 12 | **Referral and follow-up tracking** | Rule triggers (M-CHAT-R tier, IDAQ, abnormal result) create `referral` rows; deadlines are **computed** from the rule and the working-day calendar; `referral_not_initiated` gaps arise from overdue obligations | `referral`, `care_gap` | Deterministic |
| 13 | **Population-level dashboard aggregation** | Counts and rates over synthetic rows, shown beside official context with **both vintages and definitions visible**; never presented as Abu Dhabi coverage | Read-only views over all three schemas | Deterministic aggregation. Banner: *synthetic data*. Synthetic coverage is never representative (the 67/33 sex skew distorts female-package aggregates) |

The same boundary, as a dependency: AI output (step 8) exists only as columns on `care_gap` and rows in `care_gap_review`. Steps 6–7 do not read them.

---

## 8. Decision register

**Status key.** **APPROVED** = approved by the project owner (instruction recorded in revision 2.2); **PROVISIONAL** = design assumes the recommendation, approval incomplete; **OPEN** = not approved. *Approved by the project owner does not imply clinical, legal or governance approval — those are listed per decision as "external approvals still required".* "Recommended" in an OPEN decision is a recommendation, not a decision.

Blocking classification: **Blocks ERD** means the entity-relationship diagram cannot be completed (for the layer named) without it. Items marked ◆ are classified by this document and **differ from, or add to, the review**; the review's own classification is quoted.

### Decision status summary (revision 2.2)

| ID | Decision | Status | Owner approval | External approvals still required | Blocks ERD? | Blocks implementation? |
|---|---|---|---|---|---|---|
| **D1** | Real facilities + simulated overlay | **APPROVED** | Yes | Governance review of naming real facilities beside synthetic patients: **not obtained** | No (settled) | Facility-profile *creation* needs D13 |
| **D2** | Refusal representation | **PROVISIONAL** | Partial (design retained) | **Clinical: S2, S3, S4, S5; product: S1, S4; governance/legal: S5; ADPHC clarification of `OQ-WCV-REFUSAL-STATE`** | **Yes (synthetic)** | Refusal-related triggers and generator |
| D3 | Meaning of `-` / `:` | OPEN | — | SCAD | No | Workbook loading only |
| D4 | Age-label correction | OPEN | — | SCAD | No | Age-band use of 4 indicators |
| D5 | Duplicate 3422 | OPEN | — | SCAD | No | No (rows quarantined) |
| D6 | PostGIS vs plain coordinates | **RECOMMENDED — awaiting owner confirmation** (plain lat/lon) | Not yet | — | No | **Yes — before the first migration** |
| D7 | Migration tool | **RECOMMENDED — awaiting owner confirmation** (Alembic + SQLAlchemy 2.x) | Not yet | — | No | **Yes — before the first migration** |
| **D8** | Generation-run provenance | **APPROVED** | Yes | None required by the decision; **spec refresh is a follow-up** | No (settled) | No |
| D9 | Workbook loading / re-fetch | OPEN | — | — | No | Loader only |
| D10 | IFHAS component codes | OPEN | — | Rules owner (if YAML codes) | No | Rule loader |
| D11 | Evaluation history | **RECOMMENDED — awaiting owner confirmation** (append-only; design already assumes it) | Not yet | — | No (reshapes one table if reversed) | `eligibility_evaluation` |
| D12 | Working-day calendar | OPEN | — | ADPHC/programme owner | No | Decides whether `working_calendar` exists |
| D13 | Licence-status mapping | OPEN | — | DoH licensing (advisable) | No | **Facility-profile creation and `v_facility_usable`** |
| D14 | Rule applicability policy | OPEN | — | **Clinical** | No | Engine |
| D15 | Facility vintage / as-published coordinates | OPEN | — | — | No | Facility loader |
| **D16** | Six additional entities | **APPROVED** | Yes | None | No (settled) | No |
| D17 | Evaluation-contract gaps | OPEN | — | **Clinical** (guard precedence, `partial` history, age convention) | No | Engine |
| **D18** | Consent defaults | **APPROVED (safest default)** | Yes | **Governance and legal review of consent requirements: not obtained** | No (settled) | No |

### D1 — Real facilities with synthetic capability overlays — **APPROVED**
| | |
|---|---|
| **Question** | May synthetic patients be attached to the real SDI facilities, with simulated `offers_ifhas/offers_wcv/evening_hours/weekend_hours` in a separate overlay, and are real facility names shown beside synthetic patients? |
| **Decision** | **APPROVED (project owner, revision 2.2).** Use official Abu Dhabi facility names and locations from the acquired SDI register. Simulated service capabilities live in a **separate synthetic `facility_service_profile` overlay**. Simulated capabilities are **clearly labelled in the application** and are never presented as verified real-world services |
| **Rationale** | 5,339 geocoded official facilities are held and validated; inventing facilities would discard them. The patient rows carry the synthetic marker, so a single exported row still cannot be mistaken for a real patient. No official source supplies IFHAS/WCV capability (`THIQA/BASIC/ENHANCED` are `N/A` in all 4,905 populated rows), so capability must be simulated — and therefore labelled |
| **Alternatives not adopted** | (a) Real coordinates with pseudonymised names. (b) Fully fictional facilities (the spec's original §3.3) |
| **Consequences** | `patient → facility_service_profile → official.facility` (a `synthetic → official` FK). `capability_basis = 'simulated'` is a `CHECK`-enforced constant on every profile; `official.facility` holds no synthetic columns. **Application obligation (outside the database):** every screen showing a profile's capability must label it "simulated", and a persistent banner states that capabilities and patients are simulated — a UI requirement for the API/UI contract, not a schema feature. A profile may only be created for an identified, usable-coordinate, operating, plausible-kind facility — **"operating" is unavailable until D13**, so profile creation is blocked on D13, not on the ERD |
| **Approval status** | Owner: **approved**. Clinical: not required. **Not yet obtained:** governance review of showing real facility names beside synthetic patients (recommended before any external demo) |
| **Blocks ERD?** | **No — settled** |

### D2 — Refusal representation — **PROVISIONAL — clinical approval required (not approved)**
| | |
|---|---|
| **Question** | How is refusal recorded? (`OQ-WCV-REFUSAL-STATE` says a status-model decision is needed "before database design".) Before revision 2.1, `refused` was a `completion_status`, an `attendance_status` *and* a consent `state` |
| **Decision** | **PROVISIONAL.** The project owner retains the revision 2.1 design as the working design, **pending clinical/product approval**. It is **not** marked approved |
| **Design retained** | Keep the 9 evaluation statuses unchanged. A refusal is a documented fact **recorded once, at the narrowest place it happened** (R-S11): **(1)** an item refused inside a screening/visit that occurred → `component_result`; **(2)** a refusal with **no** event — whole screening, one rule, or a pathway, including a guardian's refusal for a child → `consent` (`screening_participation`, `refused`, scoped). Evidence must be traceable and linked to the correct **patient, run and applicable rule**. A care gap closes as `closed_refused` only by citing **exactly one** of `closed_by_component_result_id` / `closed_by_consent_id`, enforced by composite FKs to rows whose `refusal_evidence_valid` is true for the same run, patient and rule (§5.5). `refused` is removed from `completion_status` and `attendance_status`. **Declined-referral handling is unresolved** (S4); meanwhile `closed_refused` is forbidden for referral gaps |
| **Why it matters** | Refusal ≠ not-yet-done (scenario 19): a documented, signed refusal is not a care gap to chase (`WCV-POLICY-PARENTAL-REFUSAL`). Adding `refused` to the evaluation vocabulary would invent a status the standard does not define |
| **Alternatives not adopted** | (a) `refused` as an evaluation status. (b) `refused` kept in event tables as well. (c) A dedicated `refusal` table. (d) Consent-only |
| **Consequences** | No event row is needed for a whole-screening refusal; one refusal cannot be stored twice; a gap cannot be closed as refused without valid evidence. The entity set is fixed under this design; the sub-questions below can change **constraint content and generated expressions**, and S1/S4 could add or move an entity |
| **Blocks ERD?** | **Yes (synthetic)** — until clinical approval, or until the owner chooses to draw a clearly **provisional** synthetic ERD (§9) |

**The five sub-questions the design does not decide** (all five are open; this table is the register of them):

| # | Sub-question | Provisional design position | Approval required to settle |
|---|---|---|---|
| **S1** | Is a pathway/rule-scoped `consent` the right home for a refusal when no screening/visit event occurred? | Yes — consent, scoped by `scope_pathway`/`scope_rule` | **Product approval.** Clinical *consultation* to confirm no conflict with the standard (not formal clinical approval) |
| **S2** | What counts as **valid evidence** of a refusal? | Provisionally "documented in record **and** signature on file" (the only encoded rule is the Well-Child policy; **no IFHAS refusal rule is in the YAML**), plus a guardian for a child's Well-Child refusal. One generated expression per table | **Clinical approval required** (including whether the signature requirement applies to IFHAS) |
| **S3** | Does a **patient-wide** refusal (no pathway/rule scope) count as evidence for closing a gap? | No — scope must name a pathway or rule | **Clinical approval required** (product consulted) |
| **S4** | Is a **declined referral** a refusal needing documented evidence, or a different outcome? | **Unresolved.** `referral.status = 'declined'` is an outcome; `closed_refused` is forbidden for referral gaps | **Clinical approval required, and product approval required** |
| **S5** | **Which guardian** may refuse for a child (any of the child's own guardians, one designated guardian, both)? | Any of the child's own guardians (FK-enforced to *this child's* guardians only) | **Clinical approval required, plus governance/legal** (guardianship/consent authority) |

**Clinical approval required for: S2, S3, S4, S5** (S4 and S1 also need product approval; S5 also governance/legal). **S1 is the only sub-question that does not need formal clinical approval.** **External approvals still required:** clinical reviewer sign-off before `OQ-WCV-REFUSAL-STATE` is marked resolved; ADPHC clarification (`WCV.Support@adphc.gov.ae`, the question's `resolve_via`) where the standard is silent; governance/legal for S5. **D2 must not be recorded as approved until S2–S5 are answered.**

### D3 — Meaning of SCAD `-` and `:`
| | |
|---|---|
| **Question** | What do the cell markers `-` (births 2024) and `:` (births 2025) mean — not applicable, not reported, suppressed, zero? |
| **Why it matters** | Coercing either to 0 invents data; the project's reading ("not applicable / not reported") is **not** stated by the publisher — the in-file `Metadata` sheets of all three workbooks do not define the markers. The marker also changed between editions |
| **Recommended** | Store `value_marker_raw` verbatim with `value IS NULL`; assign no semantics until SCAD confirms |
| **Alternatives** | (a) Map both to a single "not reported" state now. (b) Map to 0 |
| **Consequences** | Recommended: no downstream interpretation is possible. **No MVP impact** — the API load has 0 markers; this matters only if workbooks are loaded (D9). (a) hard-codes an unconfirmed meaning; (b) is wrong in at least some cells |
| **Blocks ERD?** | No (the column exists either way) |
| **Approval** | Owner: no. **External: SCAD confirmation.** Clinical: no |

### D4 — Age-label correction
| | |
|---|---|
| **Question** | May the date-corrupted age labels (`2026-05-09` → `5-9`, `2026-10-14` → `10-14`, `2026-01-04` → `1-4`) be corrected, and by what rule? |
| **Why it matters** | 4 indicators / 3 labels are affected. The year `2026` is probably the extraction year, so a literal remap fails on re-fetch (`2027-05-09`). `1-4` is an inference, not evidence. A wrong remap silently misassigns population to bands |
| **Recommended** | Detect by pattern on `AGE_GROUP` members only; apply **only** when the pattern matches, the band is contiguous with its neighbours, **and** SCAD confirms (`correction_state`: `none` → `pending` → `applied`). Until applied: bounds `NULL`, member unusable as a band |
| **Alternatives** | (a) Literal remap of the three strings (what the docs imply). (b) Never correct; exclude affected members. (c) Pattern remap without waiting for SCAD |
| **Consequences** | Recommended: affected age shapes are unusable until confirmation (4868's age structure cannot calibrate the generator meanwhile; the births series can). (a) breaks silently in 2027. (b) loses real numbers. (c) acts on an unconfirmed inference |
| **Blocks ERD?** | No |
| **Approval** | Owner: yes (the rule). **External: SCAD confirmation.** Clinical: no |

### D5 — Duplicate indicator 3422
| | |
|---|---|
| **Question** | What to do with the two rows for `3422_deaths_by_region_citizenship_gender`, 2025, `Non-Emirati / Male / Abu Dhabi Region`, values **1** and **1,708** with identical labels? |
| **Why it matters** | A plain `UNIQUE` cannot be created. One row is almost certainly mislabelled (candidate: `Abroad` or `Missing/Unknown`) — an inference |
| **Recommended** | Load both with `quality_flag = 'duplicate_key_conflict'`, exclude both from default views, enforce uniqueness with a **partial unique index** (`WHERE quality_flag IS NULL`), query SCAD |
| **Alternatives** | (a) Drop both. (b) Keep the larger. (c) Sum them |
| **Consequences** | Recommended: totals for 3422 under-count until resolved, visibly. (a)–(c) guess or destroy evidence |
| **Blocks ERD?** | No |
| **Approval** | Owner: no. **External: SCAD.** Clinical: no |

### D6 — PostGIS versus ordinary coordinates
| | |
|---|---|
| **Question** | Switch the compose image to `postgis/postgis:16-…`, or keep `postgres:16-alpine` and store `DOUBLE PRECISION` coordinates? |
| **Why it matters** | One-time infrastructure choice, best made before the first migration. At 5,339 facilities the MVP needs only radius/nearest (scenario 24) |
| **Recommended** | Plain coordinates with range `CHECK`s and an index; `cube`/`earthdistance` or a haversine function. Move to PostGIS **only** if polygon operations (region membership by geometry) are required |
| **Alternatives** | PostGIS now (`geography(Point,4326)`, GiST index) |
| **Consequences** | Recommended: no polygon queries; the "inside the box ≠ inside the emirate" caveat stays. PostGIS: image change, new extension in migrations, geometry column instead of two doubles |
| **Blocks ERD?** | No (column type only) |
| **Approval** | Owner: yes (technical). Clinical: no |
| **Status (rev 2.3)** | **RECOMMENDED — awaiting owner confirmation.** Not approved |
| **Recommendation detail (rev 2.3)** | MVP uses plain PostgreSQL `DOUBLE PRECISION` `latitude`/`longitude` with the range `CHECK`s already in §3.4; **no PostGIS** unless polygon-based spatial queries become an established requirement (none is in the requirements reviewed; scenario 24 needs radius/nearest only). The original and usable coordinates and `geo_quality` are preserved exactly as designed: `source_longitude/latitude` (as published), `longitude/latitude` (usable only when `geo_quality IN ('ok','swapped_repaired')`), `geo_quality` (4 values). Keep the `postgres:16-alpine` image. Revisit if polygon/region-by-geometry queries are required — that would be a migration adding a geometry column derived from the two doubles, not a rewrite |

### D7 — Migration tooling
| | |
|---|---|
| **Question** | Which migration tool? Alembic is **not** in `backend/requirements.txt`. |
| **Why it matters** | Three schemas, generated columns, partial unique indexes, triggers and roles all need migration-managed DDL; `create_all` cannot express them reliably |
| **Recommended** | Alembic, with `version_table_schema` fixed and a shared `naming_convention` |
| **Alternatives** | Plain versioned SQL files; another tool |
| **Consequences** | Adds a dependency (not installed here) |
| **Blocks ERD?** | No |
| **Approval** | Owner: yes (technical) |
| **Status (rev 2.3)** | **RECOMMENDED — awaiting owner confirmation.** Not approved; nothing installed or created |
| **Recommendation detail (rev 2.3)** | **Alembic with SQLAlchemy 2.x** (SQLAlchemy 2.0.36 and psycopg 3 are already in `backend/requirements.txt`; Alembic is not and would be added only after confirmation). **Reasons:** (1) native to the SQLAlchemy stack already chosen; (2) hand-written migrations can express what `create_all` cannot — generated columns, partial unique indexes, `NULLS NOT DISTINCT`, triggers, roles/privileges, schema creation; (3) linear, reviewable history per schema change; (4) supports offline SQL generation for review. **Conventions (proposed):** one Alembic environment and one revision history for all three schemas; the version table lives in a dedicated location (`version_table_schema` fixed, e.g. a `public` or `meta` schema, not any of the three); `include_schemas=True` with an `include_object` filter so autogenerate sees `official`, `clinical`, `synthetic` only; the shared `naming_convention` (§2.2) on `MetaData`; each model's `MetaData`/tables declare `schema=` explicitly; autogenerate output is **always reviewed and hand-edited** (it cannot detect generated columns, triggers, partial/`NULLS NOT DISTINCT` indexes, privileges, views); views, triggers and grants are written as explicit `op.execute` statements; migrations ordered `official` → `clinical` → `synthetic` so the one-way FK direction (§2.1) holds at every revision; downgrades are provided but append-only tables are never data-reversed; seed/lookup data (e.g. `region`, status vocabularies) is **loaded by the loaders, not by migrations**. **Implications for schema-separated tables:** the schema-boundary test (§2.1) runs after every migration; the migration role needs `CREATE` on all three schemas while the application role stays `SELECT`-only on `official`/`clinical`; FKs across schemas must name the schema; generated-column composite FKs (§2.5, U8) are verified in the first migration |

### D8 — Generation-run provenance — **APPROVED**
| | |
|---|---|
| **Question** | Replace the per-row `generator_version`, `generation_seed`, `clinically_validated` (spec §1.1, repeated on 11 tables) with one `generation_run` table and a `run_id` per row? |
| **Decision** | **APPROVED (project owner, revision 2.2).** `generation_run` is the central provenance record for synthetic data. It retains **generator version, seed, commit, specification version, generation parameters and calibration inputs**, and is **immutable once the run is completed** |
| **Rationale** | These values are constant within a run; repeating them on every row lets them disagree. One immutable record is auditable. Per-row `is_synthetic` and the `SYNTH-` key remain, so a single exported row is still unmistakably synthetic |
| **Alternatives not adopted** | Keeping the four columns on every table as specified |
| **Consequences** | `run_id` and `is_synthetic CHECK` on all 18 tables; every synthetic reference is a same-run composite FK (R-S2, §5.6). **Exports must join `generation_run` or carry the data card** to keep the seed and generator version with the data. **Change from the existing specification** is documented in §12.2; **`synthetic_data_spec.md` is not modified** — refreshing it (§1.1 row markers, §3 tables, §2/§3.3/§8 stale items) is a follow-up |
| **Approval status** | Owner: **approved**. Clinical: not required. No external approval required; the spec owner should be told §1.1 is superseded |
| **Blocks ERD?** | **No — settled** |

### D9 — Workbook loading strategy (and re-acquisition)
| | |
|---|---|
| **Question** | Load the SCAD publication workbooks into `observation`? And how do a re-fetched indicator and the old vintage coexist? |
| **Why it matters** | API and XLSX disagree (births 2025 Emirati/Non-Emirati 16,308/24,760 vs 16,310/24,758; totals agree). The workbooks are non-tidy and carry `-`/`:`. A re-fetch must not collide with, or silently replace, the old rows |
| **Recommended** | **API only** in the MVP; workbooks stay `source_file` provenance and cross-check fixtures. `source_file_id` is part of row identity; `v_observation_current` picks the latest `retrieved_at` per indicator |
| **Alternatives** | (a) Load workbooks into the same fact table. (b) Separate `publication_observation` table. (c) Replace rows on re-fetch |
| **Consequences** | Recommended: defers hierarchical-row and marker parsing (D3). (a) risks summing two sources. (c) destroys vintage evidence |
| **Blocks ERD?** | No |
| **Approval** | Owner: yes |

### D10 — IFHAS component identifiers
| | |
|---|---|
| **Question** | IFHAS `components` are plain strings with no codes. How do `component_result` rows key them? |
| **Why it matters** | Per-component results (scenario 8) need a stable key; a raw string is not one. **New fact:** 75 component strings, 37 distinct slugs, no collision within any package |
| **Recommended** | Loader derives `code = slug(text)` deterministically, marks `code_origin = 'derived_slug'`, keeps `text_verbatim`; ask for explicit YAML codes in the next rules version |
| **Alternatives** | (a) Add codes to the YAML now (a rules change). (b) Key on the raw string. (c) No component-level IFHAS results |
| **Consequences** | Recommended: a later move to YAML codes is a data migration of `code`. (a) is out of scope here. (b) breaks on any typo. (c) loses scenario 8 |
| **Blocks ERD?** | No |
| **Approval** | Owner: yes. Clinical: no for the slug; the **rules owner** for any YAML change |

### D11 — Evaluation history
| | |
|---|---|
| **Question** | Keep every evaluation, or only the current one? |
| **Why it matters** | Rules require evaluation "traceable to a `rule_id` and `rule_version`"; regenerating destroys the evidence a clinician acted on and orphans gaps |
| **Recommended** | Keep history (append-only); `v_eligibility_current` for the latest. ≈ 240 k rows per run |
| **Alternatives** | Current-only with overwrite |
| **Consequences** | Recommended: trivial volume; a `care_gap` FK stays valid. Alternative: breaks FKs and audit |
| **Blocks ERD?** | No — **provisionally treated as decided in the design**; reversing it would reshape `eligibility_evaluation`, so confirm it with D1/D2/D8 |
| **Approval** | Owner: yes |
| **Status (rev 2.3)** | **RECOMMENDED — awaiting owner confirmation.** Not approved |
| **Recommendation detail (rev 2.3)** | **Append-only evaluation history.** Each `synthetic.eligibility_evaluation` row preserves: its **rule version** (`rule_id`, `rule_version`, composite FK to `clinical.rule`); its **evaluation run** (`evaluation_run_id` → `evaluation_run`); the **reference date** (held once on `evaluation_run.reference_date`, so row and run cannot disagree); the **timestamp** (`evaluated_at`); the **status** (`evaluation_status`); and the **reason** (`reason_code`, plus every fired guard in `evaluation_reason`). Rows are never updated or deleted. **Current status is read through `v_eligibility_current`** (latest per patient and `rule_id`), never by overwriting. This matches §5.3 as already written; no table shape changes |

### D12 — Working-day calendar
| | |
|---|---|
| **Question** | `IFHAS-WF-REFERRAL-15WD` counts working days. Where does the calendar come from? |
| **Why it matters** | No calendar, weekend or holiday definition exists in the repository, and the same gap blocks deriving `slot_type = 'weekend'` |
| **Recommended** | A configuration table `official.working_calendar` (loaded, with a stated `source`); **no hard-coded weekend** |
| **Alternatives** | Engine setting; a library calendar |
| **Consequences** | Recommended: deadlines are exact and auditable; the table needs a source. If rejected, the engine owns it and `referral` deadlines depend on code |
| **Blocks ERD?** | No (one optional table) |
| **Approval** | Owner: yes. **Programme owner/ADPHC: the working-week definition** |

### D13 — Licence-status mapping ◆ (additional review point)
| | |
|---|---|
| **Question** | Which of the 15 raw licence-status strings mean "operating"? |
| **Why it matters** | Only 3,005 of 5,339 are `Active`; `About to Expire`, `Temporary Closed`, `Preliminary – …` are not self-explanatory. Operating status must **not** be inferred from unreviewed values |
| **Recommended** | `license_status_map` with `review_state`; `is_operating` stays `NULL` until `confirmed`; `v_facility_usable` returns no operating facility until some mapping is confirmed |
| **Alternatives** | Treat `Active` as operating by convention; show raw status only |
| **Consequences** | Recommended: facility-profile creation is blocked until review. Alternatives hard-code an assumption |
| **Blocks ERD?** | No (it blocks *loading*, not the model) |
| **Approval** | Owner: yes. **DoH licensing authority clarification advisable** |

### D14 — Rule applicability and candidate-set policy ◆ (additional review point)
| | |
|---|---|
| **Question** | Which rules are evaluated for which patient, before any evaluation is recorded? |
| **Why it matters** | If every rule is evaluated for everyone, children get `not_eligible` against 20 adult packages, and age 78 contradicts `OQ-IFHAS-AGE-CEILING`. If too few are evaluated, "not evaluated" hides as "fine" |
| **Recommended** | §4.4: structural classes by `rule_type`; no DB restriction on the rule type an evaluation may cite; "not applicable" = **no row**; the policy is named and versioned on `evaluation_run.applicability_policy` |
| **Alternatives** | Evaluate every rule for every patient; short-circuit on gate failure |
| **Consequences** | Recommended: reproducible, but the policy content (gates-first? pathway candidacy?) still needs defining before the engine is built |
| **Blocks ERD?** | No — the policy changes content, not shape |
| **Approval** | Owner: yes. **Clinical review: yes** — the policy decides who is shown as eligible |

### D15 — Facility vintage and as-published coordinates ◆ (additional review point)
| | |
|---|---|
| **Question** | How is the facility register's date represented, and how are as-published coordinates obtained? |
| **Why it matters** | The register has **no publication date**; the retrieval timestamp is not the effective date, and the catalogue's "modified 2025-07-25/28" is catalogue metadata. And `processed/` keeps only repaired coordinates |
| **Recommended** | Keep `retrieved_at` (on `source_file`) separate from `source_effective_date` (`NULL` unless stated). Load from the raw GeoJSON through the repair function (or extend the transformation to emit the as-published pair) — **separate task, not done here** |
| **Alternatives** | Use the retrieval date as `as_of_date` (the review's wording); use `processed/` and lose `source_*` |
| **Consequences** | Recommended: honest vintage; a loader task exists. Alternatives conflate retrieval with validity or lose provenance |
| **Blocks ERD?** | No |
| **Approval** | Owner: yes |

### D16 — Additional database entities — **APPROVED**
| | |
|---|---|
| **Question** | Approve six entities the review's own table lists omit: **clinical** — `rule_load`, `verification_status`, `guard`, `rule_item_open_question`; **synthetic** — `evaluation_run`, `evaluation_reason`. |
| **Decision** | **APPROVED (project owner, revision 2.2) — all six.** Their proposed relationships and constraints are retained as written in §4.2 and §5.1/§5.3 |
| **Rationale** | The review's F-03 uses `evaluation_run_id` without a table; its F-26 names a `guard` lookup its table list omits; the loader's own model has `verification_status` and item-level open-question ids. The two `synthetic` additions are needed by F-03 and by the undefined guard precedence (D17) |
| **Alternatives not adopted** | Drop `rule_load` (hash on each rule); `verification_status` as a `CHECK`; drop `guard` / `rule_item_open_question` (item questions in JSONB); drop `evaluation_run` (reference date per row); drop `evaluation_reason` (one `reason_code`) |
| **Consequences** | Table inventory **39 (+1 conditional)** stands: `official` 9, `clinical` 12, `synthetic` 18. `guard` stays a pure lookup with **no precedence column** (D17 open). `rule_bundle_load_id` on `generation_run`/`evaluation_run` references `clinical.rule_load` |
| **Approval status** | Owner: **approved**. Clinical: not required. No external approval required |
| **Blocks ERD?** | **No — settled.** The `clinical` ERD and the entity set of the `synthetic` ERD are no longer waiting on D16 |

### D17 — Evaluation-contract gaps ◆
| | |
|---|---|
| **Question** | Four points the status YAML leaves undefined: (1) precedence among the 7 guards when several fire; (2) how `partial` history is evaluated; (3) the `upcoming` look-ahead; (4) the age reference date and convention (`OQ-COMMON-AGE-CALC`) |
| **Why it matters** | Each is a place where an engine would silently invent behaviour. The review says "single primary reason by guard precedence", but no precedence exists |
| **Recommended** | Store, don't decide: `evaluation_reason` keeps every fired guard; `partial` ⇒ `requires_clinical_review` or `unknown` until defined; `look_ahead_days` is nullable config (no clinical meaning); `reference_date` and `age_convention` are recorded per `evaluation_run` |
| **Alternatives** | Decide each now |
| **Consequences** | Recommended: the schema is neutral to every answer |
| **Blocks ERD?** | No |
| **Approval** | Owner: yes. **Clinical: yes for (1), (2), (4)**; (3) is owner-only |

---

### D18 — Consent defaults — **APPROVED (safest default)**
| | |
|---|---|
| **Question** | When **no** `contact` consent row exists, may outreach be sent (opt-out) or is it forbidden (opt-in)? The same question for person-level AI scoring (`ai_assisted_prioritisation`) |
| **Decision** | **APPROVED — the safest default (project owner, revision 2.2).** **Unless an explicit, valid and applicable permission exists: (1) contact consent is *not granted* and outreach must not proceed; (2) AI scoring permission is *not granted* and person-level AI scoring must not run.** Consent **absence** stays distinct from an explicit **refusal** or **withdrawal** |
| **Rationale** | No source reviewed says what absence permits; the lowest-risk reading is that it permits nothing. Keeping three states distinct prevents "never asked" from being reported as "refused" and prevents a refusal from being read as mere absence |
| **Limits of the decision** | It is a **data-model default**. It does **not** assume consent is legally required or sufficient in any context; applicable governance and legal requirements **must still be reviewed**. It does not gate deterministic rule evaluation or aggregate dashboards |
| **Alternatives not adopted** | Opt-out for both; opt-out for AI and opt-in for contact |
| **Consequences (direct, applied in revision 2.2)** | (1) `outreach_event`: `CHECK (delivery_status = 'suppressed' OR contact_consent_id IS NOT NULL)` — a non-suppressed event must cite an explicit `contact`/`granted` row; with none it is `suppressed`/`no_contact_permission_recorded`. (2) `care_gap`: new `scoring_consent_id` (+ generated marker, FK to a `grants_ai_scoring` row) and `CHECK (priority_score IS NULL OR scoring_consent_id IS NOT NULL)`; unscored with `no_ai_permission_recorded`. (3) `consent`: new generated `grants_ai_scoring` and its parent key. (4) Reserved, trigger-checked reason values keep **no row / withdrawn / refused** distinct. (5) **No new table**; table inventory unchanged. (6) The generator must produce patients with **no** consent rows (a population the previous spec lacked) and must give every scored gap a granted AI permission. (7) Currency and scope of a permission remain constraint triggers (§6.3 #7) |
| **Approval status** | Owner: **approved**. Clinical: not required. **External approvals still required:** governance and legal review of consent requirements for outreach and AI processing — **not obtained** |
| **Blocks ERD?** | **No — settled** |

---

## 9. ERD readiness assessment

The ERD is **not drawn** here. Two different things are reported and must not be confused:

- **Entity-design readiness** — are the entities, keys and relationships in this document settled enough to draw?
- **Approval** — has the decision they depend on been approved, and by whom? **Project-owner approvals recorded in revision 2.2: D1, D8, D16, D18. No clinical, legal or governance approval has been obtained for anything.**

### 9.1 Readiness by schema

| Schema | Tables | Entity-design readiness | ERD status | What it still depends on |
|---|---|---|---|---|
| **`official`** | 9 | **Complete** | **Ready for ERD** | Nothing. (D3–D6, D9, D13, D15 change loader behaviour, column types or content, not relationships; `working_calendar` (D12) is outside the 9 and would be additive) |
| **`clinical`** | 12 | **Complete** | **Ready for ERD** — D16 approved, so all 12 tables (incl. `rule_load`, `verification_status`, `guard`, `rule_item_open_question`) are in | Nothing for the entity set. D10 and D17 affect loader/engine content only |
| **`synthetic`** | 18 | **Complete as designed** — D1, D8, D16, D18 are settled and applied | **Pending D2 (provisional)** | **D2 — clinical approval required.** Formally the synthetic ERD waits for it. The entity set is fixed under the retained design; S1–S5 can change constraint content and generated expressions, and S1/S4 could in principle add or move an entity. If the owner wants to proceed sooner, a **clearly marked provisional synthetic ERD** can be drawn with `consent`, `component_result`, `care_gap` and `referral` flagged as D2-dependent — that is an owner choice this document does not make. D11 should also be confirmed (reversing it reshapes `eligibility_evaluation`) |

### 9.2 What is blocking what

| Decision | Status | Blocks the ERD? | Blocks database implementation? |
|---|---|---|---|
| D1, D8, D16, D18 | **Approved** | **No (settled)** | No |
| **D2** | **Provisional — clinical approval required** | **Yes — synthetic ERD** | Refusal triggers and the generator; not the schema skeleton |
| D11 | Not formally approved (treated as decided) | Only if reversed | `eligibility_evaluation` |
| **D6** (PostGIS vs plain coordinates), **D7** (migration tool) | Open | No | **Yes — both must be settled before the first migration** |
| **D12** (working-day calendar) | Open | No | Decides whether `official.working_calendar` exists; needed before referral deadlines |
| **D13** (licence-status mapping) | Open | No | **Yes for loading/using facilities as "operating"** — blocks creating any `facility_service_profile` |
| D15 (facility vintage, as-published coordinates) | Open | No | Facility loader prerequisite |
| D3, D4, D5, D9, D10 | Open | No | Loaders only (rows can load with flags/raw values) |
| D14, D17 | Open | No | **Engine** (needs clinical review) |

### 9.3 Approvals still required

**Project owner:** D2 (final approval, after clinical), D6, D7, D9, D10, D11 (confirm), D12, D13, D14, D15, D17.
**Clinical:** **D2 — S2, S3, S4, S5** (S4 also product; S1 product with clinical consultation); D14; D17 (guard precedence, `partial` history, age convention).
**Governance / legal:** D18 — review of consent requirements for outreach and AI processing; D1 — review of naming real facilities beside synthetic patients; D2-S5 — guardianship/consent authority.
**External confirmation:** SCAD (D3, D4, D5); DoH licensing (D13, advisable); ADPHC (`OQ-WCV-REFUSAL-STATE`, working week D12).

### 9.4 ERD deliverables (revision 2.3)

- [`erd/official-schema-erd.md`](erd/official-schema-erd.md) — all 9 `official` tables.
- [`erd/clinical-schema-erd.md`](erd/clinical-schema-erd.md) — all 12 `clinical` tables.
- **Not created:** the `synthetic` ERD (D2 is provisional) and the conditional `official.working_calendar` (D12).
- The ERDs are design documents only. They claim no clinical, legal or governance approval.

**Mapping specifications (Phase 3, Step 3 — revision 2.4).** Status: **drafted, awaiting review.** Design/documentation only; no model, migration, SQL, loader, ingestion or YAML change was made. They contain no approval of D2, D3–D5, D6, D7, D10, D11, D13 or any clinical, legal, governance or publisher matter; each unresolved item is registered there with its safe interim behaviour. Findings that differ from this document are listed in each mapping's discrepancy section (official §12, clinical §8) and are **not** applied here — review requested.

| Document | Covers | Status |
|---|---|---|
| [`mappings/official-source-to-table-mapping.md`](mappings/official-source-to-table-mapping.md) | all 9 `official` tables | **Drafted — awaiting review** |
| [`mappings/clinical-yaml-to-database-mapping.md`](mappings/clinical-yaml-to-database-mapping.md) | all 12 `clinical` tables | **Drafted — awaiting review** |
| [`mappings/data-loading-and-validation-strategy.md`](mappings/data-loading-and-validation-strategy.md) | loading sequence, validation placement, reconciliation, quarantine, idempotency, cross-schema needs | **Drafted — awaiting review** |

### 9.5 Verdict

- **`official`: ready for ERD.**
- **`clinical`: ready for ERD** (D16 approved).
- **`synthetic`: ERD pending D2.** All other decisions that shaped its entities are approved and applied.

Before **database implementation** (not the ERD): D7 and D6 must be settled before the first migration, D13 before any facility profile is created, and D2 before refusal enforcement is built.

---

## 10. Inconsistencies found and not resolved

These were found while consolidating. None has been silently resolved; each points to a decision or a follow-up.

| # | Inconsistency | Handling |
|---|---|---|
| 1 | The review's F-03 uses `evaluation_run_id`, but its §8 `synthetic` list (16 tables) has no `evaluation_run` | Added — **D16 approved** |
| 2 | The review's F-26 names a `guard` lookup (7 rows), but its §8 `clinical` list (8 tables) omits it, and omits `verification_status`, `rule_load`, and item-level open-question links the loader's model requires | Added — **D16 approved** |
| 3 | The review says `reason_code` = "single primary reason by guard precedence"; **`status_definitions.yaml` defines no precedence among guards** | `evaluation_reason` records all fired guards — **D17** |
| 4 | Reason code `rule_reported_not_verified` exists but **no guard produces it**; `GUARD-RULE-NOT-VERIFIED` maps *every* non-`verified` status (including `reported`) to `rule_unresolved` | Noted; `evaluation_reason.guard_id` is nullable. Needs the rules owner |
| 5 | `history_availability.partial` has no defined evaluation behaviour | **D17** |
| 6 | The review says `appointments.slot_type` is derivable from datetime + facility hours; **facility hours are not modelled** (only two booleans) and "weekend" is undefined | `slot_type` kept stored; revisit with **D12** |
| 7 | The review proposes `spec_sha256`; a hash of `spec` alone does not detect a metadata edit (e.g. `verification_status` flipped) without a version bump | Design uses `content_sha256` over the whole rule mapping. **Deviation from the review**, to be confirmed with D16 |
| 8 | The review says to record the facility register's `as_of_date = 2026-11-15`; that is the **retrieval** date, not an effective date | Separated — **D15** |
| 9 | The review's `facility` design says the loader should prefer raw GeoJSON, but `data/processed/facilities/` (and the data dictionary) is what exists; dictionary also says non-usable rows "have no usable coordinates" while the CSV retains `out_of_bounds` values | Follow-up task (not performed); consumers must test `geo_quality` |
| 10 | `synthetic_data_spec.md` §1.1 (per-row provenance), §2 (2022 anchors), §3.3 (invented facilities), §3.2 (`consent_to_contact`), §3.8 (`never_screened`), §8 are stale or superseded by this design | Spec **not modified** (out of scope for this step). Follow-up: refresh it after approval |
| 11 | Existing-document discrepancies listed in review §9 (age-label scope, aggregate rule, 3280 headline, 2677 headline, C7, B3, births split, `acquisition_log.json` paths, out-of-bounds coordinates) | Carried, **not corrected here** |
| 12 | `OQ-IFHAS-AAA-SMOKING-DEFINITION` is attached to a **verified, non-review-flagged** rule (`IFHAS-PKG-AAA-M-65-75`): an open question does not make a rule non-authoritative under the derived formula | Design follows the formula as written; flagged for the rules owner |
| 13 | The earlier "Phase 3 database design proposal" cannot be located (§0) | If it exists, diff §5 against it |
| 14 | The loader-test count (80, per the review) was **not** re-run in this step | Not asserted here |

### Changes from the original proposal (summary)

| Change | Reason |
|---|---|
| Two layers added: `official` (9), `clinical` (12) | Never proposed; driven by 215 files and 54 rules |
| `facilities` → `official.facility` + `synthetic.facility_service_profile` | 5,339 real facilities now held (F-20) |
| 11 synthetic tables → 18 | Added `referral`, `component_result`, `care_gap_review`, `history_availability`, `generation_run`, `evaluation_run`, `evaluation_reason`; `consent_and_preferences` renamed `consent` |
| `screening_eligibility` → append-only `eligibility_evaluation` | "Regenerated" destroyed the trace (F-03) |
| `care_gaps` split into rule fact / lifecycle / AI scoring + `care_gap_review` | F-04 |
| `refused` removed from `completion_status`, `attendance_status` | One source of truth (D2) |
| `never_screened` → `no_documented_screening`; `never_requested` removed | `unknown` guard; absence ≠ stored state |
| `components_*` / `assessments_*` arrays removed; `component_result` added | F-06 |
| Polymorphic `encounter_id` → two FKs with `num_nonnulls = 1` | F-08 |
| Per-row `generator_version`/`seed`/`clinically_validated` → `generation_run` | D8 |
| Dropped as redundant: `requires_clinical_review` (evaluation, assessment), `reminder_count`, `suppressed`, `pathway`, `scheduled_date`, `scheduled_age_months`, `package_name`, `is_diagnosis`, `guardian.consent_to_contact` | Derivable or duplicated |
| Added attributes: `patient.ever_smoked`, `contact_status`, `consent.guardian_id` / scope | F-07, F-09, F-29 |
| Synthetic keys `TEXT SYNTH-…`; official keys `BIGINT identity`; rule keys natural | §2.2 |

---

## 11. Strict-scope confirmation

Revisions 2.1 and 2.2 edited **only** `docs/phase-3-database-design.md`. No SQLAlchemy model, migration, ERD, dependency, YAML rule, ingestion script, application code, synthetic data or other document (including the review and `synthetic_data_spec.md`) was created or changed, and no clinical or governance question was resolved by assumption: D2 stays provisional and every other undecided item stays open.

---

## 12. Final consistency corrections (revision 2.1)

### 12.1 Corrections made

| # | Correction | Where |
|---|---|---|
| C1 | **Refusal evidence made relational.** `care_gap` now cites refusal evidence by two dedicated FKs — `closed_by_component_result_id` (exactly which item) and `closed_by_consent_id` (no-event refusals) — through the evidence-marker pattern; exactly one is required for `closed_refused` and none otherwise. Evidence must be same-run, same-patient and (for component results) same-rule | §2.5, §5.5 |
| C2 | `component_result` gains `refused_by_guardian_id`, `refusal_reason`, a generated `refusal_evidence_valid`, and checks that evidence flags exist only on refusals. `consent` gains a generated `refusal_evidence_valid`, scope checks and a guardian-of-this-child composite FK. Whole-screening refusal needs **no** event row (R-S11) | §5.2, §5.4 |
| C3 | Duplicate/contradictory refusal prevented: one refusal, one place (R-S11); a refused item may close at most one gap; contradiction trigger; `declined` outreach responses and `declined` referrals are *not* refusals; referral gaps cannot be `closed_refused` pending D2-S4 | §5.4, §5.5, §6.3 |
| C4 | Closing evidence for completion is now FK-proven too (screening/visit **performed**, referral **initiated**, same patient and rule) | §5.5 |
| C5 | ERD readiness restated per schema, separating entity-design readiness from owner approval; **clinical** moved to *pending D16* | §9 |
| C6 | Provenance verified across all 18 tables: `generation_run` now has `is_synthetic`, `generator_commit`, `spec_version`, immutability; **`evaluation_reason` lacked `run_id` and a `SYNTH-` PK — fixed**; PK prefix registry and `is_synthetic` on every table | §5.1, §5.3, §5.6 |
| C7 | **Same-run *and* same-patient** composite FKs everywhere a synthetic row references another (a screening's appointment, a guardian, a care gap, a consent must belong to the same patient); parent unique keys added to every referenced table; `history_availability` unique key added | §5.0 (R-S2), §5.2–5.5, §5.6 |
| C8 | `care_gap` carries the evaluation's rule via a composite FK, so every evidence FK can prove same-rule; duplicate-gap unique key added | §5.5 |
| C9 | Consent-to-outreach: `outreach_event.contact_consent_id` records the consent row relied on, proven `contact`/`granted` by FK; time-dependent checks are triggers. The "no row" default, left open in 2.1, is **settled by D18 in revision 2.2** (no permission ⇒ no outreach, no scoring) | §5.5, §8 |
| C10 | AI/human separation made structural: column-level grants for scoring vs `care_gap_review`; reviews append-only | §5.5 |
| C11 | `indicator.detail_source_file_id` removed (several vintages coexist, D9) | §3.3 |
| C12 | `official.working_calendar` kept out of the 9 + clarified; D16 corrected to list the clinical entities it adds; D2 revised; D8, D16 text updated | §8, §9 |

### 12.2 Change from the existing synthetic-data specification (spec **not** modified)

`synthetic_data_spec.md` §1.1 (row-level marker) and §3 are unchanged on disk and are **superseded by this design once approved**. The explicit differences:

| Spec says | This design | Status |
|---|---|---|
| Every table carries `is_synthetic`, `generator_version`, `generation_seed`, `clinically_validated` **per row** | `is_synthetic` **per row** on all 18 tables (CHECK-enforced); `run_id` per row; `generator_version`, `generator_commit`, `spec_version`, `generation_seed`, `clinically_validated`, `parameters` once per run on `generation_run`, which is immutable once finished | **D8 — approved (revision 2.2)** |
| "If a single row were exported without context it must still be obvious it is not a real patient" | Still satisfied by `SYNTH-` keys, `is_synthetic`, `(synthetic)` names, `@example.invalid`, invalid Emirates ID — none depends on the removed columns. **Exports must join `generation_run`** (or carry the data card) to keep the seed and generator version with the data | Mitigation required in the export spec |
| PKs begin `SYNTH-` | Unchanged, now `CHECK`-enforced per table (§5.6A) | — |
| 11 tables; `facilities`; `screening_eligibility` regenerated; `consent_and_preferences` with `never_requested`; arrays of components; polymorphic `encounter_id`; `refused` in three places | See §10 "Changes from the original proposal" | Spec to be refreshed after approval |

### 12.3 Revision 2.2 — owner decisions applied

| Decision | Applied as |
|---|---|
| **D1 approved** | Status recorded; UI "simulated capability" labelling stated as an application obligation; profile creation blocked on D13 |
| **D2 provisional** | Revision 2.1 design retained; five sub-questions tabulated with the approver each needs (clinical: S2–S5); not marked approved |
| **D8 approved** | Status recorded; spec difference in §12.2 (spec untouched) |
| **D16 approved** | Six entities confirmed; **clinical ERD readiness changed to "ready"** |
| **D18 approved (safest default)** | Direct consequences applied: `outreach_event` must cite `contact`/`granted` consent unless suppressed; `care_gap.scoring_consent_id` required for any AI score; `consent.grants_ai_scoring`; reserved suppression reasons distinguish *no row* / *withdrawn* / *refused*. **No table added or removed; inventory unchanged (39 + 1 conditional)** |

### 12.4 Unresolved design issues

| # | Issue | Why unresolved | Route |
|---|---|---|---|
| U1 | **Model re-scores overwrite** `care_gap` Group 3: only human changes are kept (`care_gap_review`); earlier AI scores are lost | Preserving them needs a scoring-event table the review never required; adding it is a scope decision | Owner; non-blocking (additive later) |
| U2 | ~~Consent default for absent rows~~ | **Resolved by D18 (approved, revision 2.2)**: absence ⇒ not granted. Governance/legal review of consent requirements still outstanding | D18 |
| U3 | Evidence standard for refusal (documented **and** signed) applies provisionally to IFHAS although no IFHAS refusal rule is encoded | Clinical | **D2-S2** |
| U4 | Whole-screening refusal is modelled as pathway/rule-scoped consent; patient-wide refusal is not valid evidence; declined referral is not a refusal | Product/clinical | **D2-S1, S3, S4** |
| U5 | A consent that closed gaps and is **later superseded** by `granted`: historical gaps stay closed; whether the engine reopens or re-identifies is engine behaviour not defined anywhere | Clinical/engine | **D17**-adjacent; new gap rows arise from a fresh evaluation |
| U6 | Time-dependent integrity (consent vs outreach/scoring, refusal contradictions, consent scope covering a gap's rule) relies on constraint triggers, not FKs | Inherent to append-only history | §6.3 — each needs a test before the ERD is implemented |
| U7 | Existing inconsistencies #3–#6 in §10 (guard precedence, unproduced reason code, `partial` history, `slot_type`) | Need rules-owner or clinical input | **D17**, **D12** |
| U8 | Generated-column composite FKs are used for evidence (§2.5). They are valid PostgreSQL but unusual; SQLAlchemy 2.0 must model them with `Computed(persisted=True)` | Implementation detail | Verify in the first migration (D7) |

---


*Suggested next step: obtain clinical approval for D2 (S2–S5), settle D6 and D7, then draw the `official` and `clinical` ERDs (ready now) and the `synthetic` ERD once D2 is decided; start from a fresh conversation.*
