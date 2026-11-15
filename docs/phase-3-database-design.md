# PulseReach — Phase 3 Consolidated Database Design

**Phase 3, Step 2.** Design only. No models, migrations, scripts, YAML, data or application code were created or changed. The only file written by this step is this document.

**Date:** 2026-11-15
**Status:** **DRAFT FOR REVIEW — not approved.** Nothing in this document is an approved decision unless §8 says so; at the time of writing, **no decision in §8 is approved.**
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
| `synthetic` | `generation_run`, `evaluation_run` **[D16]**, `patient`, `guardian`, `consent`, `facility_service_profile`, `history_availability`, `eligibility_evaluation`, `evaluation_reason` **[D16]**, `ifhas_screening`, `well_child_visit`, `component_result`, `assessment`, `referral`, `care_gap`, `care_gap_review`, `appointment`, `outreach_event` | 18 |

Versus the review's §8 list (9 / 8 / 16): `clinical` gains `rule_load`, `verification_status`, `guard`, `rule_item_open_question` (all required by findings F-25/F-26 and the loader's own model — see §10); `synthetic` gains `evaluation_run` and `evaluation_reason` **[PROVISIONAL: D16]** (the review's F-03 references an `evaluation_run_id` that its own table list does not define).

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
| `metadata_source_file_id`, `detail_source_file_id` | BIGINT | yes / no | FK → `source_file` |
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
| R-S1 | **Every row is fabricated.** `is_synthetic BOOLEAN NOT NULL DEFAULT true CHECK (is_synthetic)` on every table; every PK matches `^SYNTH-[A-Z]{3,4}-[0-9]+$` (`CHECK`) | spec §1.1 |
| R-S2 | **Same-run integrity.** Every table carries `run_id` → `generation_run`, and every reference to another `synthetic` row is a **composite FK including `run_id`** (e.g. `(run_id, patient_id) → patient(run_id, patient_id)`), so a screening can never point at a patient of a different run. Each parent therefore has `UNIQUE (run_id, <pk>)` | D8 |
| R-S3 | **Unknown ≠ not done.** Absence of a row never means "no screening". `history_availability` is the explicit statement of whether absence is evidence (§5, F-02) | F-02 |
| R-S4 | **Eligibility ≠ care gap.** An `eligibility_evaluation` is a rule result; a `care_gap` is a *consequence* of one (FK to it). A gap never exists without the evaluation that produced it | F-03/F-04 |
| R-S5 | **Completion ≠ refusal.** Refusal is a *documented fact with a scope*, never an evaluation status and never a completion status **[D2]** | F-05 |
| R-S6 | **Rule result ≠ AI score.** Eligibility, status, reasons and gap identity are deterministic and live on `eligibility_evaluation`/`care_gap` (rule columns). The model's `priority_score` and explanation are a separate, clearly-labelled column group with their own provenance; a model may only **order** gaps the rules already identified | F-04, RAI §3.1.6.3 |
| R-S7 | **AI recommendation ≠ human decision.** Overrides are rows in `care_gap_review`, never an edit of the score | F-04, §3.1.7.2.3 |
| R-S8 | **Booking ≠ completed care.** `appointment.status = 'attended'` does not close anything. Care is complete only when a screening/visit event row exists, linked to the appointment, with `performed_date` | F-09 |
| R-S9 | **Nothing here is a diagnosis.** There is no diagnosis column anywhere. `assessment` stores structured scores; PHQ-9/GAD-7 are stored with **no severity band** (the bands are not in the rules) | spec §3.7 |
| R-S10 | Contact data uses only fabricated values: `@example.invalid` emails, a reserved non-routable phone pattern, names suffixed `(synthetic)`, no real address | spec §1.1 |

### 5.1 Provenance and runs

#### `synthetic.generation_run`  — **[PROVISIONAL: D8]**
**Purpose.** One row per generator execution. Replaces the four per-row columns (`generator_version`, `generation_seed`, `clinically_validated`, … repeated on 11 tables) that are constant within a run. **This amends spec §1.1 and needs owner sign-off.** Per-row `is_synthetic` and the `SYNTH-` prefix stay.
**PK.** `run_id TEXT` (`SYNTH-RUN-NNNN`).

| Column | Type | Null | Notes |
|---|---|---|---|
| `generator_version` | TEXT | no | |
| `generation_seed` | BIGINT | no | |
| `started_at`, `finished_at` | TIMESTAMPTZ | no / yes | |
| `rule_bundle_load_id` | BIGINT | no | FK → `clinical.rule_load` — the exact rules the run read |
| `parameters` | JSONB | no | Demographic profile and every `param_abnormal_rate_*` (arbitrary, **named as having no clinical meaning**) |
| `calibration_inputs` | JSONB | no | List of `{source_file_id, sha256}` of official files used for **shape only**. No FK (JSONB); loader validates against `official.source_file` |
| `population_profile` | TEXT | no | `CHECK IN ('mirror_scad','labelled_alternative')` — the 67/33 sex-skew choice (spec §8 item 4) |
| `n_adults`, `n_children` | INTEGER | no | |
| `clinically_validated` | BOOLEAN | no | `CHECK (NOT clinically_validated)` |
| `data_card_path` | TEXT | no | A run without a data card is incomplete (RAI §3.2.5) |

If D8 is rejected, the four columns return to every synthetic table and this table shrinks to a data-card record; nothing else in the design changes except R-S2.

#### `synthetic.evaluation_run`  — **[PROVISIONAL: D16]**
**Purpose.** One execution of the deterministic engine over a population. The review's F-03 uses `evaluation_run_id` but defines no table for it.
**PK.** `evaluation_run_id TEXT` (`SYNTH-EVR-NNNNNN`).

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id` | TEXT | no | FK → `generation_run` |
| `rule_bundle_load_id` | BIGINT | no | FK → `clinical.rule_load` |
| `reference_date` | DATE | no | The date age is computed against (`OQ-COMMON-AGE-CALC` leaves it unspecified, so it is recorded, not assumed) |
| `age_convention` | TEXT | no | DEFAULT `'unspecified'` — stays `unspecified` while the question is open |
| `look_ahead_days` | INTEGER | yes | The `upcoming` look-ahead is "a product configuration value with no clinical meaning" (status YAML); `NULL` ⇒ `upcoming` is not produced |
| `applicability_policy` | TEXT | no | Name/version of the candidate-set policy (§4.4, D14) |
| `engine_version` | TEXT | no | |
| `started_at` | TIMESTAMPTZ | no | |

### 5.2 People, consent, facilities

#### `synthetic.patient`  — **[PROVISIONAL: D1, D2]** (via facility FK and refusal)
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
**PK.** `guardian_id` (`SYNTH-GDN-…`); `UNIQUE (run_id, guardian_id)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK `(run_id, patient_id)` → `patient` (the child) |
| `relationship` | TEXT | no | `CHECK IN ('mother','father','legal_guardian')` |
| `given_name`, `family_name` | TEXT | no | `(synthetic)` suffix |
| `phone_synthetic`, `email_synthetic` | TEXT | yes | As patient |
| `preferred_language`, `preferred_channel` | TEXT | no | As patient |
| `contact_status` | TEXT | no | `CHECK IN ('valid','wrong','unverified')` |

**Removed vs spec §3.2:** `consent_to_contact` — it duplicated `consent`; a guardian's consent is a `consent` row with `guardian_id` (F-29).

#### `synthetic.consent`  — **[PROVISIONAL: D2]**
**Purpose.** First-class, **append-only** consent and refusal facts. **AI opt-out is separate from contact opt-out**: a patient may accept outreach while refusing AI prioritisation, which must suppress scoring and leave rule evaluation untouched (scenario 20).
**Source.** Generator. **PK.** `consent_id` (`SYNTH-CNS-…`).

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK |
| `guardian_id` | TEXT | yes | Composite FK; `CHECK ((applies_to = 'child_by_guardian') = (guardian_id IS NOT NULL))` |
| `consent_type` | TEXT | no | `CHECK IN ('contact','data_processing','ai_assisted_prioritisation','screening_participation')` |
| `state` | TEXT | no | `CHECK IN ('granted','withdrawn','refused')`. **`never_requested` is not a value** — *absence of a row* means never requested, so the two representations cannot coexist (F-29) |
| `applies_to` | TEXT | no | `CHECK IN ('self','child_by_guardian')` |
| `scope_pathway` | TEXT | yes | `CHECK IN ('ifhas','well_child')`; `NULL` = patient-wide |
| `scope_rule_id`, `scope_rule_version` | TEXT | yes | Composite FK → `clinical.rule`; both or neither (`CHECK (num_nonnulls(…) <> 1)`). Refusal of one specific screening |
| `recorded_at` | TIMESTAMPTZ | no | |
| `recorded_by` | TEXT | no | A synthetic staff token |
| `documented_in_record`, `signature_on_file` | BOOLEAN | yes | `WCV-POLICY-PARENTAL-REFUSAL` §4.2.1: a refusal must be documented with a signature. `NULL` = not recorded |
| `refusal_reason` | TEXT | yes | `CHECK (state = 'refused' OR refusal_reason IS NULL)` |

**Append-only;** current state = latest per `(patient, consent_type, scope_pathway, scope_rule_id)` via `v_consent_current`.
**Indexes.** `(patient_id, consent_type, recorded_at DESC)`.
**Cross-table rules (engine + constraint trigger):** outreach requires `contact = granted` unless suppressed; scoring requires `ai_assisted_prioritisation` not withdrawn.

#### `synthetic.facility_service_profile`  — **[PROVISIONAL: D1]**
**Purpose.** A **simulated capability overlay on a real official facility** (F-20). Real facility, real coordinates; *simulated* `offers_*` flags — because no official source gives IFHAS/WCV capability (the `THIQA/BASIC/ENHANCED` columns are `N/A` in all 4,905 populated rows). **Not** a facility register.
**PK.** `profile_id` (`SYNTH-FSP-…`); `UNIQUE (run_id, profile_id)`; `UNIQUE (run_id, facility_id)`.

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
**PK.** `history_id` (`SYNTH-HST-…`).

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK |
| `pathway` | TEXT | no | `CHECK IN ('ifhas','well_child')` |
| `history_status` | TEXT | no | `CHECK IN ('available','partial','not_available')` |
| `as_of_date` | DATE | no | |
| `note` | TEXT | yes | |

**Semantics.** `due` and `no_documented_screening` require `available`; `not_available` ⇒ `unknown`. **How `partial` is evaluated is unspecified** by the status definitions — D17; the engine must return `requires_clinical_review` or `unknown`, not guess. Append-only; latest `as_of_date` wins. **Index** `(patient_id, pathway, as_of_date DESC)`.

### 5.3 Evaluation

#### `synthetic.eligibility_evaluation`  — **[PROVISIONAL: D11 (history), D14]**
**Purpose.** **Append-only** result of applying one rule version to one patient. The deterministic engine's output — **never** an ML output. Traceable to `rule_id` + `rule_version` (status YAML: "deterministic and traceable"). The review's F-03 replaces the spec's "regenerated on evaluation".
**PK.** `evaluation_id` (`SYNTH-EVL-…`).

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK |
| `evaluation_run_id` | TEXT | no | FK → `evaluation_run` (carries `reference_date`; not duplicated here, so the two cannot disagree) |
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

#### `synthetic.evaluation_reason`  — **[PROVISIONAL: D16, D17]**
**Purpose.** *All* guards that fired for an evaluation, plus item-level blocks. The status YAML defines 7 guards and **no precedence among them**; collapsing them to one `reason_code` would invent one. This table records every fired guard and lets the engine report one.
**PK.** `(evaluation_id, reason_ordinal)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `evaluation_id` | TEXT | no | FK |
| `reason_ordinal` | SMALLINT | no | |
| `guard_id` | TEXT | yes | FK → `clinical.guard` (`NULL` for a reason with no guard, e.g. `rule_reported_not_verified`) |
| `reason_code` | TEXT | no | FK → `clinical.reason_code` |
| `item_category`, `item_code` | TEXT | yes | With the evaluation's rule: composite FK → `clinical.rule_item`. Item-level `rule_item_unresolved` (scenario 25) |

If D16 is rejected, `reason_code` on the evaluation is the only reason and guard precedence must be decided (D17) first.

### 5.4 Care events

#### `synthetic.ifhas_screening`  — **[PROVISIONAL: D2]**
**Purpose.** An IFHAS screening **event** for one package.
**PK.** `screening_id` (`SYNTH-SCR-…`); `UNIQUE (screening_id, rule_id, rule_version)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK |
| `profile_id` | TEXT | no | Composite FK → `facility_service_profile` |
| `rule_id`, `rule_version` | TEXT | no | FK → `clinical.rule`; must be a `screening_package` (loader/trigger check). A screening that cannot name its rule is invalid (spec §1.3) |
| `appointment_id` | TEXT | yes | FK; `UNIQUE` — one event per appointment. **Replaces `scheduled_date`** (F-09) |
| `performed_date` | DATE | yes | |
| `completion_status` | TEXT | no | `CHECK IN ('complete','partial','not_attended')`. **`refused` removed** — one source of truth **[D2]** |
| `results_communicated_date` | DATE | yes | §4.9.2.1: within 10 days of the initial visit |
| `journey_reported_date` | DATE | yes | §4.11.4.3: within 15 days |
| `has_abnormal_finding` | BOOLEAN | yes | From `param_abnormal_rate_*` — arbitrary, no clinical meaning |

`CHECK (completion_status <> 'not_attended' OR performed_date IS NULL)`; `CHECK (completion_status = 'not_attended' OR performed_date IS NOT NULL)`. **`package_name` dropped** (derivable from the rule). `partial` is **derivable** from `component_result` (IFHAS §4.11.4.3: an incomplete package means claims cannot be submitted); the stored status must match it (test).
**Indexes.** `(patient_id, rule_id, performed_date DESC)`; `(appointment_id)`.

#### `synthetic.well_child_visit`  — **[PROVISIONAL: D2]**
**Purpose.** A Well-Child visit **event**. Non-attendance is an **event fact**, never `overdue` (scenario 17, `OQ-WCV-DUE-WINDOW`).
**PK.** `visit_id` (`SYNTH-VIS-…`); `UNIQUE (visit_id, rule_id, rule_version)`.

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id`, `guardian_id` | | no | Composite FKs |
| `profile_id` | TEXT | no | Composite FK |
| `rule_id`, `rule_version` | TEXT | no | FK → `clinical.rule` (`WCV-VISIT-01M` … `WCV-VISIT-72M`; `visit_schedule`) |
| `appointment_id` | TEXT | yes | FK; `UNIQUE` |
| `performed_date` | DATE | yes | |
| `attendance_status` | TEXT | no | `CHECK IN ('attended','not_attended')`. **`refused` and `catch_up` removed** — refusal is **[D2]**; catch-up was a status *and* a boolean |
| `is_catch_up_visit` | BOOLEAN | no | `WCV-POLICY-CATCHUP-ELIGIBILITY` §3.10.1.3: a defaulter attending for catch-up vaccination remains screening-eligible (scenario 18) |

**Dropped:** `scheduled_age_months` (it is `rule.recommended_age_months`), `scheduled_date` (the appointment), `assessments_completed/outstanding` (derived from `component_result`). **No `overdue` field or value.**

#### `synthetic.component_result`  — **[PROVISIONAL: D2, D10]**
**Purpose.** Per-item result for a screening or visit — replaces the free-text `components_completed/outstanding` arrays (F-06), which could disagree with each other and with the rule, carried no FK, and could not express an item-level unresolved item.
**PK.** `component_result_id` (`SYNTH-CMP-…`).

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK |
| `ifhas_screening_id`, `well_child_visit_id` | TEXT | yes | `CHECK (num_nonnulls(ifhas_screening_id, well_child_visit_id) = 1)` |
| `rule_id`, `rule_version` | TEXT | no | Composite FK to the **parent event** `(parent_id, rule_id, rule_version)`, so a result cannot cite a different rule than its screening/visit |
| `item_category`, `item_code` | TEXT | no | Composite FK → `clinical.rule_item` |
| `result_status` | TEXT | no | `CHECK IN ('completed','refused','not_done','not_applicable')` |
| `performed_date` | DATE | yes | |
| `documented_in_record`, `signature_on_file` | BOOLEAN | yes | Required to be non-null when `refused` (`CHECK`) |

**Unique.** `UNIQUE (ifhas_screening_id, rule_id, rule_version, item_category, item_code)` and the same for visit.
**"Outstanding" is derived** (`v_item_outstanding` = rule items − recorded results, **excluding** items whose `verification_status <> 'verified'`, which are unresolved, not outstanding). **Measured values (BMI, BP, HbA1c, lipids) are not stored in the MVP** — nothing in the 27 scenarios consumes them.

#### `synthetic.assessment`  — **[FINAL]**
**Purpose.** Scored instruments as structured results (M-CHAT-R, IDAQ, PHQ-9, GAD-7).
**PK.** `assessment_id` (`SYNTH-ASM-…`).

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK |
| `ifhas_screening_id`, `well_child_visit_id` | TEXT | yes | `CHECK (num_nonnulls(…) = 1)` — two FKs, **not** a polymorphic `encounter_id`, and no `encounter` supertype (F-08) |
| `instrument` | TEXT | no | `CHECK IN ('M-CHAT-R','IDAQ','PHQ-9','GAD-7')` |
| `instrument_version` | TEXT | yes | |
| `administered_date` | DATE | no | |
| `raw_score` | NUMERIC | yes | |
| `item_responses` | JSONB | yes | Item-level answers; IDAQ's referral logic needs them (item 1 = YES, or any other = NO) |
| `rule_id`, `rule_version` | TEXT | yes | FK → `clinical.rule`: the tier/referral rule applied (`WCV-MCHATR-LOW/MODERATE/HIGH`, `WCV-IDAQ-REFERRAL`); **`NULL` for PHQ-9/GAD-7** |

**Checks.** `CHECK (instrument NOT IN ('PHQ-9','GAD-7') OR rule_id IS NULL)` — no severity band is ever assigned. The band is **derived** from the rule (not stored). There is **no `is_diagnosis` column** (it was constant `false`); there is no diagnosis anywhere (R-S9). `requires_clinical_review` is dropped: it is derivable (rule review flag / `rule_id IS NULL`).

#### `synthetic.referral`  — **[FINAL]**
**Purpose.** The first-class, time-bounded referral obligation the rules define (`WCV-MCHATR-HIGH` 2 weeks + PHC follow-up after 1 month; `WCV-IDAQ-REFERRAL`; `WCV-FU-REFERRAL-INITIATION-7D`; `WCV-FU-SPECIALIST-EVALUATION-2-4W`; `IFHAS-WF-REFERRAL-15WD`). Without it `referral_not_initiated` cannot be computed (F-01; scenarios 9, 13, 14, 16).
**PK.** `referral_id` (`SYNTH-REF-…`).

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK |
| `ifhas_screening_id`, `well_child_visit_id`, `assessment_id` | TEXT | yes | `CHECK (num_nonnulls(…) = 1)` |
| `trigger_rule_id`, `trigger_rule_version` | TEXT | no | FK → `clinical.rule` |
| `rule_action_ordinal` | SMALLINT | yes | Which `spec.actions[n]` (a high M-CHAT-R yields **two** referrals: neurodevelopment clinic and speech therapy). `UNIQUE` with source + rule |
| `referral_target` | TEXT | no | **As printed.** The Appendix 8 mapping is not encoded and is not invented |
| `target_profile_id` | TEXT | yes | Composite FK |
| `trigger_date` | DATE | no | The rule's `reference_event` (results release / assessment) |
| `initiated_date`, `completed_date` | DATE | yes | |
| `status` | TEXT | no | `CHECK IN ('pending','initiated','completed','declined','cancelled')` |

**Checks.** `CHECK (initiated_date IS NULL OR initiated_date >= trigger_date)`; `CHECK (completed_date IS NULL OR (initiated_date IS NOT NULL AND completed_date >= initiated_date))`; `CHECK (status NOT IN ('initiated','completed') OR initiated_date IS NOT NULL)`; `CHECK (status <> 'completed' OR completed_date IS NOT NULL)`.
**Deadlines are derived** from `rule.timing_*` / `spec.actions` and, for working days, the calendar (D12). They are never stored, so a rule version bump cannot leave stale deadlines. `declined` is a *referral* outcome; a documented, signed refusal is still a `consent`/`component_result` fact (D2).

### 5.5 Care gaps, review, booking, outreach

#### `synthetic.care_gap`  — **[PROVISIONAL: D2]**
**Purpose.** The prioritisation surface. **A care gap is produced by rules, never by a model** (spec §3.8). Three clearly separated column groups on one row, so the distinction survives in the data: **(1) rule fact, (2) lifecycle, (3) AI scoring.** (Overrides are *not* here — they are rows in `care_gap_review`.)
**PK.** `care_gap_id` (`SYNTH-GAP-…`).

| Group | Column | Type | Null | Notes |
|---|---|---|---|---|
| — | `run_id`, `patient_id` | | no | Composite FK |
| **Rule fact** | `evaluation_id` | TEXT | no | FK → `eligibility_evaluation`. **A gap cannot exist without the evaluation that produced it** (R-S4) |
| | `gap_type` | TEXT | no | `CHECK IN ('no_documented_screening','interval_elapsed','partial_completion','referral_not_initiated','visit_not_attended')`. **`never_screened` is renamed** and is permitted only where history is `available` — it would otherwise assert what the `unknown` guard forbids |
| | `subject_ifhas_screening_id`, `subject_well_child_visit_id`, `subject_referral_id` | TEXT | yes | `CHECK (num_nonnulls(…) <= 1)`; required to match `gap_type` (`partial_completion` ↔ screening; `visit_not_attended` ↔ visit; `referral_not_initiated` ↔ referral) |
| | `identified_date` | DATE | no | |
| **Lifecycle** | `status` | TEXT | no | `CHECK IN ('open','closed_completed','closed_refused','suppressed','superseded')` |
| | `closed_date` | DATE | yes | `CHECK ((status LIKE 'closed%') = (closed_date IS NOT NULL))` |
| | `closed_by_ifhas_screening_id`, `closed_by_well_child_visit_id`, `closed_by_referral_id`, `closed_by_consent_id` | TEXT | yes | Closing evidence. `CHECK (num_nonnulls(…) = 1)` when closed, `= 0` when open. **`closed_completed` requires an event row** (R-S8). `closed_refused` requires the consent/component refusal **[D2]** |
| | `suppression_reason` | TEXT | yes | `CHECK ((status = 'suppressed') = (suppression_reason IS NOT NULL))` |
| **AI scoring** | `priority_score` | NUMERIC | yes | Model output; `NULL` = not scored |
| | `priority_explanation` | TEXT | yes | `CHECK (priority_score IS NULL OR priority_explanation IS NOT NULL)` (RAI §3.1.6.3: a score always has an explanation) |
| | `scored_by_model_version` | TEXT | yes | |
| | `scored_at` | TIMESTAMPTZ | yes | `CHECK ((priority_score IS NULL) = (scored_at IS NULL))` |
| | `scoring_suppressed_reason` | TEXT | yes | AI opt-out: `scored_at IS NULL` **plus** this reason. `CHECK (scoring_suppressed_reason IS NULL OR priority_score IS NULL)` |

**Dropped:** `pathway` (derivable from the rule); `clinician_reviewed`, `clinician_override`, `override_reason` (→ `care_gap_review`). **Indexes.** `(status) WHERE status = 'open'`; `(patient_id)`; `(evaluation_id)`.
**View.** `v_care_gap_effective_priority`: latest human override if any, else the AI score — both visible, neither overwritten.
**Cross-table rules (engine + trigger):** the gap's evaluation must be in a gap-yielding status; scoring is forbidden when `ai_assisted_prioritisation` is withdrawn.

#### `synthetic.care_gap_review`  — **[FINAL]**
**Purpose.** **Append-only** human decisions and overrides: the audit trail (§3.1.7.2.3; scenario 27). One nullable override column records only the *last* override.
**PK.** `review_id` (`SYNTH-REV-…`).

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `care_gap_id` | | no | Composite FK |
| `reviewer` | TEXT | no | A synthetic clinician token |
| `action` | TEXT | no | `CHECK IN ('confirmed','priority_overridden','dismissed')` — illustrative vocabulary, to be fixed at implementation |
| `previous_priority`, `new_priority` | NUMERIC | yes | `CHECK (action <> 'priority_overridden' OR new_priority IS NOT NULL)` |
| `reason` | TEXT | no | `CHECK (length(btrim(reason)) > 0)` — an override without a reason is not an override |
| `reviewed_at` | TIMESTAMPTZ | no | |

**Index** `(care_gap_id, reviewed_at DESC)`. Clinicians retain decision authority (RAI §3.1.7.2.2).

#### `synthetic.appointment`  — **[FINAL]**
**Purpose.** A booking. **A booking is not completed care** (R-S8): the screening/visit event row is the care; the appointment is the slot.
**PK.** `appointment_id` (`SYNTH-APT-…`).

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK |
| `profile_id` | TEXT | no | Composite FK |
| `care_gap_id` | TEXT | yes | Composite FK; `NULL` for a booking that did not originate from a gap |
| `appointment_type` | TEXT | no | `CHECK IN ('ifhas_screening','well_child_visit','referral_visit','other')` |
| `scheduled_datetime` | TIMESTAMPTZ | no | Stored UTC; scheduled in `Asia/Dubai` |
| `slot_type` | TEXT | no | `CHECK IN ('weekday','evening','weekend')` (WCV §3.9.1.1). **Kept stored** — see §10: the review calls it derivable, but facility hours are not modelled and "weekend" is undefined (D12) |
| `status` | TEXT | no | `CHECK IN ('scheduled','attended','no_show','cancelled_by_patient','cancelled_by_facility','rescheduled')` |
| `booked_via` | TEXT | no | |

**Dropped:** `reminder_count` (a count of `outreach_event` rows). **Test:** `status = 'attended'` with no linked event row is a data-quality error. **Indexes.** `(patient_id, scheduled_datetime)`; `(care_gap_id)`; `(profile_id, scheduled_datetime)`.

#### `synthetic.outreach_event`  — **[FINAL]**
**Purpose.** Invitations, reminders, recalls (IFHAS §4.7.1: first screening, rescreening, **and recall for positive and insufficient results**). Outreach must be attributable to the gap that justified it and, if it worked, to the booking it produced (the impact measure).
**PK.** `outreach_id` (`SYNTH-OUT-…`).

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id`, `patient_id` | | no | Composite FK |
| `care_gap_id` | TEXT | no | Composite FK — every contact traces to a rule-identified need |
| `guardian_id` | TEXT | yes | Composite FK; `CHECK ((recipient = 'guardian') = (guardian_id IS NOT NULL))` |
| `recipient` | TEXT | no | `CHECK IN ('patient','guardian')` |
| `event_type` | TEXT | no | `CHECK IN ('invitation','reminder','recall_positive_result','recall_insufficient_result','referral_follow_up')` |
| `channel` | TEXT | no | `CHECK IN ('sms','phone','email','app')` |
| `sent_datetime` | TIMESTAMPTZ | yes | `NULL` for suppressed events |
| `delivery_status` | TEXT | no | `CHECK IN ('queued','delivered','failed','suppressed')`. **No separate `suppressed` boolean** |
| `suppression_reason` | TEXT | yes | `CHECK ((delivery_status = 'suppressed') = (suppression_reason IS NOT NULL))` (deceased, contact withdrawn …) |
| `response` | TEXT | yes | `CHECK IN ('no_response','booked','declined','opted_out','wrong_contact')`. A `declined` **response** is not a documented refusal (D2); `wrong_contact` is delivery failure, **not** declined (scenario 23) |
| `appointment_id` | TEXT | yes | FK. `CHECK (appointment_id IS NULL OR response = 'booked')` |
| `triggered_by_ai_score` | BOOLEAN | no | Lets outreach driven by a model score alone be found |
| `clinician_approved_by` | TEXT | yes | `NULL` is **representable** so the human-oversight requirement (§3.1.1.2) can be tested rather than assumed |
| `message_template_id` | TEXT | yes | |

**Cross-table rules (engine + trigger):** a non-suppressed contact requires current `contact = granted`; a deceased patient's events are `suppressed`. **Indexes.** `(care_gap_id)`; `(patient_id, sent_datetime)`; `(appointment_id)`.

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

These need a loader validation, constraint trigger or engine test — stated so nothing is assumed enforced:

1. A member's `dimension_type` matches its observation column.
2. Leaves reconcile to aggregates (R-O2).
3. `machine_evaluable = false` ⇒ parent `requires_clinical_review`.
4. Unresolved rules/items cite ≥ 1 open question.
5. `ifhas_screening.rule` is a `screening_package`; `well_child_visit.rule` is a `visit_schedule`.
6. Facility-profile eligibility (operating, usable coordinates, plausible kind).
7. Outreach vs consent; scoring vs AI opt-out.
8. `partial` completion equals the derived value; appointments marked attended have an event.
9. No FK crosses the dependency rule (§2.1).

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
| 8 | **AI-assisted prioritisation and explanation** | A model **orders** the already-identified gaps and writes an explanation; skipped for patients who opted out of AI (`scored_at IS NULL` + reason). A clinician may confirm or override | `care_gap` (scoring group), `care_gap_review` | **AI (ordering + explanation only)** with **human** review. Never changes gap identity, eligibility or status. Labelled a technical scaffold where NHANES shaped any input (RAI §3.1.5.1.1) |
| 9 | **Consent-aware outreach** | Check current consent and contact validity and death; send or suppress with a reason; child outreach goes to the guardian; record approval and whether an AI score triggered it | `outreach_event` | Deterministic checks; approval is **human** |
| 10 | **Appointment booking** | Patient/guardian responds; a slot at a profile facility is booked (capability and geography routing); outreach linked to the booking | `appointment`, `outreach_event.appointment_id` | Deterministic. **Booking is not care** |
| 11 | **Screening or visit completion** | Event row created and linked to the appointment; per-item results; assessments scored; refusal recorded as a documented fact; `partial` derived; gap closed with its evidence | `ifhas_screening`, `well_child_visit`, `component_result`, `assessment`, `care_gap` status | Deterministic from generator output; refusal via consent/component per D2 |
| 12 | **Referral and follow-up tracking** | Rule triggers (M-CHAT-R tier, IDAQ, abnormal result) create `referral` rows; deadlines are **computed** from the rule and the working-day calendar; `referral_not_initiated` gaps arise from overdue obligations | `referral`, `care_gap` | Deterministic |
| 13 | **Population-level dashboard aggregation** | Counts and rates over synthetic rows, shown beside official context with **both vintages and definitions visible**; never presented as Abu Dhabi coverage | Read-only views over all three schemas | Deterministic aggregation. Banner: *synthetic data*. Synthetic coverage is never representative (the 67/33 sex skew distorts female-package aggregates) |

The same boundary, as a dependency: AI output (step 8) exists only as columns on `care_gap` and rows in `care_gap_review`. Steps 6–7 do not read them.

---

## 8. Decision register

**Every decision below is OPEN.** None is approved. "Recommended" is a recommendation, not a decision. Where this document's design assumes the recommendation, it says so with **[PROVISIONAL: Dn]**.

Blocking classification: **Blocks ERD** means the entity-relationship diagram cannot be completed (for the layer named) without it. Items marked ◆ are classified by this document and **differ from, or add to, the review**; the review's own classification is quoted.

### D1 — Real facilities with synthetic capability overlays
| | |
|---|---|
| **Question** | May synthetic patients be attached to the real SDI facilities, with simulated `offers_ifhas/offers_wcv/evening_hours/weekend_hours` stored in a separate overlay table — and are real facility names shown beside synthetic patients? |
| **Why it matters** | It determines the facility entity: `official.facility` + `synthetic.facility_service_profile` (this design) vs. a fully fictional `synthetic.facility`. It also decides whether a real, named clinic can appear next to a fabricated patient and a fabricated capability — a governance and reputational question as much as a modelling one |
| **Recommended** | Real facilities, real coordinates, simulated overlay, **real names with a persistent "capabilities and patients are simulated" banner**. The patient rows carry the synthetic marker, so a single exported row still cannot be mistaken for a real patient |
| **Alternatives** | (a) Real coordinates, **pseudonymised names** in synthetic views. (b) Fully fictional facilities with invented coordinates (the spec's original §3.3 — now obsolete because 5,339 real points exist) |
| **Consequences** | Recommended: `patient → facility_service_profile → official.facility` (a `synthetic → official` FK); needs D13 for "operating". (a): add a `display_alias` column to the profile. (b): discards the validated register and re-introduces invented coordinates |
| **Blocks ERD?** | **Yes** (review: blocks) — for the synthetic layer only |
| **Approval** | **Owner: yes** (also governance). Clinical: no |

### D2 — Refusal representation
| | |
|---|---|
| **Question** | How is refusal recorded? (`OQ-WCV-REFUSAL-STATE` says a status-model decision is needed "before database design".) Today `refused` is a `completion_status`, an `attendance_status` *and* a consent `state` |
| **Why it matters** | Refusal ≠ not-yet-done (scenario 19): a documented, signed refusal is not a care gap to chase (`WCV-POLICY-PARENTAL-REFUSAL`, §4.2.1). Three representations can disagree, and adding `refused` to the 9-value evaluation vocabulary would invent a status the standard does not define |
| **Recommended** | Keep the 9 evaluation statuses **unchanged**. Refusal is a documented *fact with a scope*: (1) item/screening-level → `component_result.result_status = 'refused'` with `documented_in_record` and `signature_on_file`; (2) patient/pathway/rule-level → a `consent` row (`screening_participation`, `refused`) with optional scope; (3) the care gap then closes as `closed_refused` with that evidence. Remove `refused` from `completion_status` and `attendance_status` — one source of truth |
| **Alternatives** | (a) Add `refused` to `evaluation_status`. (b) Keep `refused` in the event tables as well as consent. (c) A dedicated `refusal` table |
| **Consequences** | Recommended: touches `consent`, `component_result`, `ifhas_screening`, `well_child_visit`, `care_gap`. **Sub-question not settled by it:** how is the refusal of a *whole* screening that never became an encounter recorded (no event row to hang `component_result` on)? Recommended default: pathway/rule-scoped consent row. (a) changes a shared vocabulary owned by YAML; (b) reintroduces the inconsistency; (c) adds a table without removing any column's ambiguity |
| **Blocks ERD?** | **Yes** (review: blocks) — changes 4–5 tables |
| **Approval** | **Owner: yes.** **Clinical: consult advisable and required before `OQ-WCV-REFUSAL-STATE` is marked resolved** — the database decision does not close the clinical question |

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

### D8 — Generation-run provenance ◆ (review: non-blocking; this document: ERD-shaping)
| | |
|---|---|
| **Question** | Replace the per-row `generator_version`, `generation_seed`, `clinically_validated` (spec §1.1, repeated on 11 tables) with one `generation_run` table and a `run_id` FK per row? |
| **Why it matters** | The columns are constant within a run, so repeating them is redundancy that can disagree. **But spec §1.1 is a safety rule**, and this amends it |
| **Recommended** | Yes: `generation_run` + `run_id` on every row + composite same-run FKs (R-S2). Per-row `is_synthetic` and the `SYNTH-` prefix are kept |
| **Alternatives** | Keep the four columns on every table as specified |
| **Consequences** | Recommended: one place to audit a run; every synthetic FK becomes composite. Alternative: no new table, but 4 × 18 repeated columns |
| **Blocks ERD?** | **Yes for the synthetic ERD** ◆ — it adds a table and a column to every synthetic entity. (Review lists it as "before implementation"; an ERD drawn without it must be redrawn.) |
| **Approval** | **Owner: yes** (amends a safety rule). Clinical: no |

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

### D16 — Tables added beyond the review's list ◆
| | |
|---|---|
| **Question** | Approve `evaluation_run` and `evaluation_reason` (synthetic), and `rule_load`, `verification_status`, `guard`, `rule_item_open_question` (clinical)? |
| **Why it matters** | The review's F-03 uses `evaluation_run_id` without a table; its F-26 names a `guard` lookup its table list omits; the loader's own model has `verification_status` and item-level open questions |
| **Recommended** | Yes — all six. The four `clinical` additions are required by findings already in the review; the two `synthetic` additions are needed by F-03 and by D17 |
| **Alternatives** | Drop `evaluation_run` (store `reference_date` per row); drop `evaluation_reason` (one `reason_code`) |
| **Consequences** | Alternatives re-introduce a repeated column and force a guard-precedence rule that does not exist |
| **Blocks ERD?** | **Yes for completeness** ◆ — six entities |
| **Approval** | Owner: yes |

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

## 9. ERD readiness assessment

The ERD is **not drawn** here.

### 9.1 Finalised (can be drawn now, per layer)

| Layer | Status |
|---|---|
| **`official`** (9 tables) | **Ready.** Entities, keys and relationships are settled. Open items change column *types* (D6) or *content* (D3, D4, D5, D9, D13, D15), not relationships. Only the optional `working_calendar` (D12) is undecided |
| **`clinical`** (12 tables) | **Ready**, subject to confirming the four additions in D16. Open items (D10, D12) do not change relationships |

### 9.2 Pending

| Layer | Status |
|---|---|
| **`synthetic`** (18 tables) | **Not ready** until D1, D2, D8, D16 are confirmed (below) |

### 9.3 Decisions that block the ERD

| Decision | Scope | Source of classification |
|---|---|---|
| **D1** — real facilities with overlay | `synthetic` facility entity and `patient` FK | Review |
| **D2** — refusal representation | `consent`, `component_result`, both event tables, `care_gap` | Review |
| **D8** — generation-run provenance | A table and a `run_id` on every synthetic entity | ◆ This document |
| **D16** — six additional tables | Entity set | ◆ This document |

### 9.4 Can be deferred to implementation

D3, D4, D5, D6, D7, D9, D10, D12, D13, D14, D15, D17 — they change loader behaviour, column types, content or configuration, not entity relationships. **D11** is treated as decided in the design and should be confirmed alongside the four above (reversing it reshapes one table).

### 9.5 Verdict

**Ready for the `official` and `clinical` ERDs now. The `synthetic` ERD is blocked on four owner confirmations (D1, D2, D8, D16).** Two of the four (D1, D2) are the review's own blockers; the other two are additional blockers identified in this consolidation. D2 additionally touches an open clinical question (`OQ-WCV-REFUSAL-STATE`), so its owner approval should be taken with a clinical consult. Nothing else stands between this document and a complete ERD.

---

## 10. Inconsistencies found and not resolved

These were found while consolidating. None has been silently resolved; each points to a decision or a follow-up.

| # | Inconsistency | Handling |
|---|---|---|
| 1 | The review's F-03 uses `evaluation_run_id`, but its §8 `synthetic` list (16 tables) has no `evaluation_run` | Proposed as a table — **D16** |
| 2 | The review's F-26 names a `guard` lookup (7 rows), but its §8 `clinical` list (8 tables) omits it, and omits `verification_status`, `rule_load`, and item-level open-question links the loader's model requires | Added — **D16** |
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

This step created **one file**, `docs/phase-3-database-design.md`. It created no SQLAlchemy models, no migrations, no ERD; installed no dependency; changed no YAML, ingestion script, application code or other document (including the review); generated no synthetic data; and resolved no clinical or governance question by assumption. Every open decision remains open.

*Suggested next step: approve or amend D1, D2, D8 and D16 (§9.3), then start the ERD from a fresh conversation — this one carries a large amount of inspection context that is no longer needed.*
