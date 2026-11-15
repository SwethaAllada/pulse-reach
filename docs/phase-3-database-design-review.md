# PulseReach — Phase 3 Database Design Review

**Step 1 of Phase 3.** Design review only. No models, migrations, scripts, rules or data were created or changed. The only file added to the repository is this document.

**Review date:** 2026-11-15
**Verdict:** **APPROVED WITH CHANGES** (see §10)

> **Read this first — what was actually reviewed.**
> The request refers to "the proposed Phase 3 schema". **No document with that title exists in the repository**, and none was available to this review. The only entity-level design in the repo is the 11-table contract in [`data/metadata/synthetic_data_spec.md`](../data/metadata/synthetic_data_spec.md) §3–4, which states it exists so that "the database schema in Phase 3 is derived from a stated contract". This review treats that contract as the proposed schema. It covers **only synthetic individual-level data**: there is **no proposed design at all** for the official aggregate layer (86 SCAD indicators), the facility register, or the clinical-rule registry. Those are reviewed in §4–5 as *missing design*, not as design that was checked. If a separate Phase 3 proposal exists, send it and §3 should be re-run against it; §4–8 stand regardless because they are driven by the data and rules on disk.

---

## 1. Executive summary

The 11-table synthetic contract is a **sound foundation with good safety instincts**: `SYNTH-` keys, no valid Emirates IDs, a status vocabulary taken from the rules, an explicit "unknown ≠ not done" stance, refusal and AI-opt-out as first-class consent states. Ten of the 11 tables are necessary for the MVP; none is redundant outright.

It is **not sufficient to approve as the Phase 3 design**, for four reasons:

1. **It is stale against the data now on disk.** Spec §3.3 invents facilities and coordinates; the repo now holds 5,339 real, geocoded facilities. spec §2 anchors to 2022 facility counts and "only 2024 births"; the 2025 API and a 1977–2025 birth series now exist.
2. **It cannot represent several MVP scenarios it itself lists.** There is no referral entity (scenarios 9, 13, 14, 16), no way to tell `unknown` from `due` (scenarios 1 vs 7), no smoking attribute although a machine-evaluable rule needs one (scenarios 11, 12), no per-component results (scenarios 8, 25), no audit trail for overrides (scenario 27), and `screening_eligibility` is "regenerated", which destroys the trace the rules require.
3. **No design exists for the official layer, and the data is harder than the documents say.** Reading the actual files found defects that the existing quality report does not record, and that break the obvious schema (details below). The headline ones:
   - **37 of 86 indicators change cube shape between years.** 34 of them are aggregate-free **only in 2025**; indicator 3549 sums to exactly 8× the true birth count in 2024 and to the correct 41,235 in 2025. "Filter the aggregate member" is not a rule that holds across years.
   - **Indicator 3422 has a duplicate natural key with different values** (1 vs 1,708), so a naïve `UNIQUE` constraint cannot be created.
   - **Date-corrupted age labels affect 4 indicators and 3 labels**, not 1 and 2 as documented. The year in the corrupted label is probably the extraction year, so a hard-coded remap will break on re-fetch.
   - **434 facility rows carry nothing but coordinates** (no name, licence, status, region or type).
   - The facility CSV keeps **only corrected coordinates**, so "coordinate corrections and provenance" cannot be preserved from `processed/` alone.
4. **The rules are fully representable, but not by a naïve mapping.** All 54 rules, 174 assessment items, 23 open questions and 10 rule types fit a relational model. Three YAML properties will bite a naïve one: partial dates (`2025-07`), items with no stable code on the IFHAS side, and a `history` block that does **not** preserve superseded specs.

**What the design gets right and should be kept unchanged:** separation of official aggregates from synthetic individuals (needs strengthening, not replacing); `is_diagnosis = false`; refusal ≠ not-done; AI opt-out ≠ contact opt-out; assessments stored as structured scores; no `overdue` for Well-Child.

**Net recommendation:** keep the 11 tables, fix them (§6, §8), add **4 required tables** (`referral`, `component_result`, `care_gap_review`, `history_availability`), replace synthetic `facilities` with an overlay on the real register, and design the two missing layers (`official`, `clinical`) before the ERD is drawn. Two decisions block the ERD (§9): refusal representation (`OQ-WCV-REFUSAL-STATE` says a decision is needed "before database design") and real-vs-synthetic facilities.

---

## 2. Existing repository and data architecture

### 2.1 What exists

| Area | State (verified) |
|---|---|
| Monorepo | `backend/` (FastAPI skeleton: `health.py` only; `app/db`, `app/models`, `app/schemas`, `app/services` are **empty packages**), `frontend/` (Next.js scaffold), `data-pipeline/`, `ml/` (empty), `infrastructure/` |
| DB stack declared | `postgres:16-alpine` in `infrastructure/docker-compose.yml`; `sqlalchemy==2.0.36`, `psycopg[binary]==3.2.3`, `pandas==2.2.3` in `backend/requirements.txt` |
| **Not present** | **No Alembic** in `backend/requirements.txt`; **no PostGIS** (alpine Postgres image); no `pytest` in backend requirements; `docs/architecture.md`, `docs/data-dictionary.md`, `docs/requirements.md` are placeholders |
| Clinical rules | `data-pipeline/rules/` (IFHAS 29 rules, Well-Child 25 rules, 23 open questions, 2 sources, status vocabulary) and `data-pipeline/rule_loader/` (load + validate only). **80 tests pass** (run in an isolated venv outside the repo) |
| Ingestion | `data-pipeline/ingestion/` (4 fetch scripts); `data-pipeline/transformation/build_facilities.py` (the only transformation) |
| Data | `data/raw/` 215 files; **`shasum -a 256 -c data/reference/raw_checksums.sha256` → 215 OK**; `data/processed/facilities/` (5,339 rows); `data/synthetic/` **empty** |

### 2.2 What each dataset actually is (inspected, not assumed)

| Source | Files | Shape actually found | Used by MVP? |
|---|---|---|---|
| SCAD API `raw/statad_api/indicator_detail/` | 86 JSON | **14,913 observation rows**, all `VALUE` numeric (0 nulls), all annual (`OBS_DT` always `YYYY-01-01`, `YEAR` always equals its year), 1 unit per indicator (13 distinct unit strings), dimensions per indicator: 17 have none, 55 one, 10 two, 4 three | Yes — calibration and denominators |
| SCAD API metadata `indicator_metadata/` | 71 XLSX | Key/value sheet: indicator code (e.g. `PD_POP_YY_1D_4868`), name, description, keywords, statistical population, geographic coverage, unit, base period, periodicity, data sources, calculation method, last update. **15 indicators have none** | Yes (indicator catalogue) |
| SCAD publications `raw/scad/` | 5 XLSX | Non-tidy bilingual publication layout; parent/child row hierarchy (`Emirati` → `Male`/`Female`) with repeated child labels; footnote asterisks inside labels; trailing spaces | Cross-check only (see F-12) |
| SDI facilities `raw/abudhabi_sdi/` | 9 GeoJSON | 5,339 points, 43 source attributes; `processed/` CSV keeps 26 | Yes |
| Open-data catalogue `raw/abudhabi_opendata/` | 42 | Catalogue + 7 files; 5 contain one cell each, 2 are UAE-wide 2008 | **No** — provenance only |
| IFHAS / WCV standards | **not held** | Manifest `SRC-02`/`SRC-03` are `state: blocked`; content exists only as transcription in the YAML | Rule provenance only |

### 2.3 Boundaries the design must preserve

- Official data is aggregate only; **no official source holds screening history, attendance or coverage** (quality report A8, §7). Every individual-level record is synthetic.
- Two clinical-authority rules are enforced in code and must survive into the database: `authoritative` is **derived, never configured** (`loader.py` rejects an `authoritative:` key), and a rule is authoritative only if `verification_status = verified` **and** not `requires_clinical_review`.
- `OQ-GOV-DATA-RESIDENCY` (GCP Cloud Run vs UAE residency) is open: no real patient data in any environment. The database must make that mechanically hard to violate (§8.1).

---

## 3. Review of every proposed table

Verdicts: **KEEP** (as specified), **FIX** (needed, with changes listed), **REPLACE**, **ADD** (missing). MVP-necessity is judged against the 27 scenarios in `synthetic_data_spec.md` §5.

| # | Proposed table | Needed for MVP? | Verdict | Principal issues (finding) |
|---|---|---|---|---|
| 3.1 | `patients` | Yes | **FIX** | `sex`/`date_of_birth` must be nullable (guards need it); no smoking attribute (F-07); `region` should reference the official region table; `registered_facility_id` FK target changes (F-20); 4 repeated provenance columns (F-26) |
| 3.2 | `guardians` | Yes (child outreach, scenario 19) | **KEEP** | Siblings duplicate guardian rows — acceptable at 2,000 children; do not add a link table now |
| 3.3 | `facilities` | Yes, but **as specified it is obsolete** | **REPLACE** | Synthetic names/coordinates/`SYNTH-FAC` ids contradict the 5,339-row real register (F-20) |
| 3.4 | `screening_eligibility` | Yes | **FIX** | "Regenerated on evaluation" destroys the trace (F-03); `requires_clinical_review` duplicates the status; needs `reference_date` and a lookup-table status (F-03) |
| 3.5 | `ifhas_screenings` | Yes | **FIX** | `components_completed/outstanding` arrays (F-06); `refused` triplicated (F-05); duplicates `scheduled_date` with appointments (F-09) |
| 3.6 | `well_child_visits` | Yes | **FIX** | Same as 3.5; `catch_up` appears as both a status value and a boolean |
| 3.7 | `assessments` | Yes (scenarios 13–16) | **FIX** | Polymorphic `encounter_id` cannot carry a foreign key (F-08) |
| 3.8 | `care_gaps` | Yes | **FIX** | One row mixes rule fact, model score and clinician audit (F-04); no lifecycle/closure; `never_screened` contradicts the `unknown` guard (F-02) |
| 3.9 | `appointments` | Yes | **FIX** | No link to the resulting visit/screening or to the outreach that produced it (F-09); `reminder_count` is derivable |
| 3.10 | `outreach_events` | Yes | **FIX** | `recipient='guardian'` has no guardian FK; `suppressed` and `delivery_status` say the same thing twice |
| 3.11 | `consent_and_preferences` | Yes (scenarios 19–21) | **FIX** | `never_requested` as a stored row is ambiguous with "no row"; must be append-only; refusal needs a rule/pathway scope (F-05) |
| — | *(none)* | **Yes** | **ADD** | `referral` (F-01), `history_availability` (F-02), `component_result` (F-06), `care_gap_review` (F-04) |
| — | *(none)* | Yes | **ADD layer** | `official.*` (F-11 to F-23) and `clinical.*` (F-24 to F-28) were never proposed |

**Answer to "are all proposed tables necessary?"** Yes for 10 of 11; the 11th (`facilities`) is necessary as a *concept* but must be replaced. No table should be deleted. The redundancy is at column level (§7), not table level.

---

## 4. Actual source-to-table compatibility

**4.1 SCAD indicators and workbooks**

### F-11 — Aggregate rows: the "filter the aggregate" rule is not stable across years — **HIGH, new**

- **Issue.** The documents say 65 of 86 indicators embed an aggregate member (`Total`, `Emirate of Abu Dhabi`) and consumers must filter it. That is true, but it is not the whole behaviour. **37 indicators change cube shape across years**; in **34 of them the only aggregate-free year is 2025**, i.e. the 2025 extract is leaf-only and sparse (zero cells omitted). So for 2025 the emirate total is **not stored** and must be derived.
- **Why it matters.** A schema or view that "uses the aggregate member for totals and excludes it for sums" returns nothing for 2025 totals, and a rule that sums all rows is wrong for every earlier year. Rates are worse: leaves of a rate cannot be summed.
- **Evidence.**
  - `3549_births_by_region_citizenship_gender`: 2024 has 80 rows summing to **314,664 = 8 × 39,333**; 2025 has **23 rows** summing to the correct **41,235**.
  - `3463`: 2024 includes `Total` = 39,333; 2025 has only `Emirati` 16,308, `Non-Emirati` 24,760, `Missing/Unknown` 167.
  - `3280` (under-five mortality rate, unit *Death per 1,000 live births*): 2024 has `Emirate of Abu Dhabi` = 6.9916; **2025 has only three region leaves** (7.08, 4.89, 7.51), which cannot be combined into an emirate rate.
  - Full list: 37 indicators incl. 2584, 2585, 2592, 2616, 2650 (2024), 2681, 2703 (13 leaf-only years), 2872 (5), 3422, 3463, 3465, 3505–3510, 3536, 3549.
- **Recommendation.**
  1. Classify at the **dimension-member level**, not the indicator level: `dimension_member.member_role ∈ {leaf, aggregate, not_stated, missing_unknown, abroad, other, unlabelled}`.
  2. Persist `observation.row_role` (`leaf` / `aggregate`) at load time (derived once, tested).
  3. Add `indicator.measure_kind ∈ {count, rate, percentage, ratio, density}` and `is_additive`. Only `count` is summable.
  4. Expose **leaf-only views as the default read path**; derive totals only for additive indicators; never store derived totals as if they were source rows.
  5. Treat an absent cell as "not published", **not zero** and not missing.
  6. Add a load-time reconciliation test (leaves sum to the aggregate wherever both exist — the quality report states they do).

### F-12 — Missing-value markers and categories are two different mechanisms — **HIGH**

- **Issue.** The repo lists one "marker set" `{-, :, Not Stated, Not stated, Missing/Unknown}`. These are two different things: `-` and `:` are **cell-level value markers** (the cell has no number); `Not Stated`, `Missing/Unknown`, `Abroad` are **dimension members that carry real numbers** (e.g. deaths 2025 `Not Stated (Gender)` = 8 and 1).
- **Why it matters.** One column cannot hold both. Collapsing them either drops real counts or invents zeros.
- **Evidence.** In the API extracts **no `VALUE` is null** (0 of 14,913): markers occur only in the XLSX publications (births 2024 `-`, births 2025 `:`). The in-file `Metadata` sheets of all three workbooks contain **no definition of `-` or `:`**, so "not applicable / not reported" is the project's reading, not the publisher's.
- **Recommendation.** `observation.value NUMERIC NULL` + `value_marker_raw TEXT NULL` + `CHECK ((value IS NULL) = (value_marker_raw IS NOT NULL))`. Do **not** map `-`/`:` to semantics until SCAD confirms. Category members live in `dimension_member` with a `member_role`. Never coerce either to 0.
- **Related inconsistency inside the API data:** gender has both `Missing/Unknown` (208 rows) and `Unknown` (1) in the same indicators (3505, 3507); region has `abroad` (lower-case, indicator 3536) next to `Abroad`, and `Other` (2703, 2731). Keep raw labels as separate members; add a `canonical_key` (case-folded) and let the role carry meaning. Do not merge `Unknown` into `Missing/Unknown` without publisher confirmation.

### F-13 — Unlabelled (NULL) dimension members — **MEDIUM, new**

- **Issue.** Some rows have a dimension column present but **null** (`INDICATOR_EN` null in 2681: 8 of 216 rows; 2798: 4 of 268; 2872: 2 of 16; `AGE_GROUP_EN` null in 2584).
- **Why it matters.** In a wide observation table, `NULL` already means "this dimension does not apply to the indicator". A null *label* would be indistinguishable.
- **Recommendation.** Map null labels to an explicit member `(unlabelled)` with `member_role = unlabelled`; reserve SQL `NULL` for "dimension not applicable".

### F-14 — Duplicate natural key in indicator 3422 — **MEDIUM, new**

- **Issue.** `3422_deaths_by_region_citizenship_gender`, 2025, `Non-Emirati / Male / Abu Dhabi Region` occurs **twice** with identical English and Arabic labels and values **1** and **1,708**.
- **Why it matters.** `UNIQUE (indicator, period, dimensions)` fails to create or load. One of the two is almost certainly mis-labelled (candidate: `Abroad` or `Missing/Unknown`), but that is an inference, not evidence.
- **Recommendation.** Add `source_row_ordinal` and `quality_flag`; enforce uniqueness with a **partial unique index** (`WHERE quality_flag IS NULL`); load both rows, flag both `duplicate_key_conflict`, exclude them from default views, and add the row to the SCAD query list. Do not guess which is right.

### F-15 — Age bands: corruption is wider than documented, and bands are not one scheme — **HIGH**

- **Issue.** The docs record `5-9`/`10-14` corrupted in **one** indicator (4868). Actual: **4 indicators** (2584, 3276, 3535, 4868) and **3 labels** (`2026-05-09`, `2026-10-14`, and `2026-01-04`, evidently `1-4`, adjacent to the genuine `Less than one year` band in 3276/3535). Further, the band *schemes differ*: 5-year (`0-4` … `80+`), a spaced variant (`15 - 19`), 10-year (`25-34`, `35-44`), custom (`0-14`, `15-29`, `30-44`, `45-59`, `60+`; `0-14`, `15-34`, `35-54`, `55-64`, `65+`), plus `Less than one year`, `Total`, `Missing/Unknown`, null. 50 distinct English labels.
- **Why it matters.** (a) A global age-band enum is impossible. (b) The corrupted year component is `2026`, which looks like the **extraction year** (date coercion of `5-9` to "5 September" of the current year). **If so, a re-fetch in 2027 returns `2027-05-09`** and a hard-coded string remap silently misses. That is an inference; it is consistent with every observed label but untested. (c) The 2022 workbook's infection bands align with no IFHAS band (quality report H4) — do not map.
- **Recommendation.**
  - Store age bands as **dimension members with numeric bounds** (`age_min_months`, `age_max_months`, NULL for open-ended `80+`/`85+`; `Less than one year` → 0–11 months), plus `scheme_code`. Keep `raw_label` verbatim and `label_was_corrupted`.
  - Remap with a **pattern**, not a literal: `^\d{4}-(\d{2})-(\d{2})$ → "{int(g1)}-{int(g2)}"`, restricted to AGE_GROUP and documented. Treat `2026-01-04 → 1-4` as an inference to confirm with SCAD.
  - Never derive a single-year-of-age population from bands (quality report A5).

### F-16 — Reporting periods — **MEDIUM**

- **Findings.** All 86 indicators are annual; `OBS_DT` is always 1 January. `MONTH_*`/`QUARTER_*` exist as fields but are **never populated** in these 86. The overview's mixed periodicity (quality report A6) does not affect the acquired set. Indicator 4868 is a **projection** series (years 2024, 2030, 2035, 2040; 2030 bands sum to 5,194,000 vs a stated 5,195,000). `Metadata` sheet `Last data update` is `20400101` for 4868 — a sentinel, not a date.
- **Recommendation.** `observation.period_year SMALLINT` (+ `period_type = 'year'`) rather than a timestamp; keep `obs_date_raw`; add `indicator.series_kind ∈ {observed, projected}`. Do **not** load `MAX_VALUE/MIN_VALUE/MAX_OBS_DT/MIN_OBS_DT` (series extrema repeated on every row, not observations) or `Name` (duplicate of `YEAR`) — the data dictionary already says extrema are not observations. Keep `VALUE` as `NUMERIC` (values are floats such as 6.0240963855 and 61.0).

### F-17 — Region is not one concept — **MEDIUM**

- **Issue.** `REGION_EN` means *region of residence* in births/deaths, *facility region* in 2592/2681/2703/2731/2798 ("…by facility region"), and carries non-geographic members (`Abroad`, `Not stated`, `Missing/Unknown`, `Other`) plus the aggregate `Emirate of Abu Dhabi`. The SDI register uses `Abu Dhabi`/`Al Ain`/`Al Dhafra` (no "Region" suffix).
- **Recommendation.** An `official.region` table (3 rows: codes `AD`, `AIN`, `DHF`, EN/AR names) and a `region_id` on `dimension_member` **only where the member is one of the three regions**. Add `indicator.region_basis ∈ {residence, facility_location, unspecified}` (derive from title, confirm against the metadata workbook's "Geographic coverage"). Source-label aliasing belongs in `dimension_member`, not in the patient/facility tables.

### F-18 — Observation table shape (and why not EAV) — **DESIGN CHOICE**

Dimensions per indicator ≤ 3, but 10 distinct dimension types exist (REGION, CITIZENSHIP, GENDER, AGE_GROUP, CAUSE_DEATH, DISEASE_TYPE, INDICATOR, TYPE, SECTORS, BED_TYPE).

| Option | Integrity | Query ergonomics | Verdict |
|---|---|---|---|
| EAV (`observation_member`) | Hard: uniqueness needs a synthetic key; "exactly these dims" is not checkable | Many joins | Reject |
| `members JSONB` | None | Poor | Reject |
| **Wide: 10 nullable typed FK columns** | `UNIQUE NULLS NOT DISTINCT (indicator_id, period_year, <10 cols>)` (PostgreSQL ≥ 15; compose pins 16) | Direct `WHERE region = …` | **Recommend** |

At 14,913 rows (≈ 15 k) this is trivially small: no partitioning, no materialised views are justified. Rename `INDICATOR_EN`/`TYPE_EN` to `measure_item`/`insurance_type`; their source names are misleading. `indicator_dimension` (which of the 10 an indicator uses) is metadata the loader and tests should assert against (a `CHECK` cannot reference another table).

### F-19 — The workbooks must not be loaded into the same fact table by default — **MEDIUM**

- **Evidence.** Births 2025 Emirati/Non-Emirati: API `3463` gives **16,308 / 24,760**, the XLSX gives **16,310 / 24,758** — totals agree (41,235), the split differs by 2. Also `scad_health_tables_en.xlsx` is **30 stacked tables with reference periods 2008–2012** (e.g. "Table 1: Key Health Statistics, Abu Dhabi, 2012"); the quality report (C7) says it has "no stated reference period", which is wrong.
- **Recommendation.** MVP loads the **API only** into `observation`. Workbooks remain cross-check/validation sources. If a workbook table is ever loaded, `source_file_id` is part of the row identity and rows from different sources are never summed together. This also defers the hierarchical-row and `-`/`:` parsing work.

---

**4.2 Facility register**

### F-20 — Real register vs `SYNTH-FAC` facilities — **HIGH**

- **Issue.** `synthetic_data_spec.md` §3.3 specifies fictional facilities with invented coordinates because "No real facility coordinates are held (quality report H6)". H6 is closed. §2 anchors facility mix to 2022 counts; §8 item 3 asks whether real coordinates can be obtained.
- **Why it matters.** Using fictional rows would discard a validated 5,339-point official layer; using the real rows as-is would give them synthetic attributes the official data does not contain (`offers_ifhas`, `offers_wcv`, `evening_hours`, `weekend_hours`, any Thiqa acceptance — columns `THIQA/BASIC/ENHANCED` are `N/A` in **all 4,905** populated rows, so IFHAS-capability **cannot** be derived).
- **Recommendation.** Two tables:
  - `official.facility` — the register as published, with provenance.
  - `synthetic.facility_service_profile` — one row per official facility chosen to host synthetic patients, with the four capability booleans, `is_synthetic = true`, and a run reference. The UI must label capabilities "simulated". Restrict the eligible set to `is_operating_licence`, usable coordinates, and plausible kinds (hospital, health centre, clinic — not pharmacy, mobile blood unit, dialysis).
- **Decision for the owner (D1):** show real facility names beside synthetic patients, or pseudonymise names in synthetic views while keeping real coordinates. Recommended: real names with a persistent "capabilities and patients are simulated" banner; this is also the spec's own test ("if a single row were exported… it must still be obvious it is not a real patient") — facility names alone do not break it because the *patient* rows carry the marker.

### F-21 — Facility identity, licences and sites — **HIGH**

- **Evidence (inspected in the CSV).**
  - `(source_layer, facility_id)` is unique (0 duplicates); `facility_id` alone is **not** (1,715 distinct in 5,339).
  - `license_no` is non-blank in 4,905 rows and **globally unique** (0 repeats, 0 cross-layer) → usable as an alternate key where non-null. 434 are blank and must be stored `NULL`, not `''`.
  - **The 434 `rehabilitation_center` rows have nothing but `facility_id`, `source_layer`, longitude, latitude and `geo_quality`** — no name (EN or AR), licence, status, region, city or type. The docs say only "blank region and status".
  - **15 raw `license_status` values**, including a typo variant (`Preliminary -Cancelled by Law` ×24 beside `Preliminary - Cancelled by Law` ×368), and only 3,005 `Active`. `is_public` contains a stray `N` (3 rows).
  - **24 co-located groups (50 rows)** share name and coordinates but have **different licences** (e.g. a `HFPRF-…` preliminary and an `MF…` issued licence). The register is **licence-level, not site-level**.
- **Recommendation.**
  - Key: surrogate `facility_id BIGINT IDENTITY`; `UNIQUE (source_layer, source_object_id)`; `UNIQUE (license_no)` (NULLs distinct).
  - `license_status_raw TEXT` + FK to `license_status_map(raw_value → status_group, is_operating)`; do not guess the meaning of unseen values.
  - `identity_status ∈ {identified, unidentified}`; the 434 rows load as `unidentified`, are excluded from every default view, and can never be a registered facility.
  - Do **not** de-duplicate co-located rows; optionally a nullable `site_group_id` later.
  - Normalise `is_public` (`N` → `No`) in a derived column, keep the raw value.
  - **Do not load** `thiqa/basic/enhanced` as columns (constant `N/A` looks like data — finding B1). Do **not** load contact details (`FACILITYEMAIL/PHONE/FAX/POBOX`): the licence grants no right to use personal information, and they are not in `processed/` anyway.
  - `beds`/`specialities`/`professionals` composite strings: store verbatim as `TEXT` (or one `source_properties JSONB`); **do not build child tables in the MVP** — nothing in the 27 scenarios consumes them.

### F-22 — Coordinates, corrections and provenance — **HIGH**

- **Issue.** The facility CSV holds a single `latitude`/`longitude` pair. For 31 `swapped_repaired` rows that pair is the **repaired** value; the as-published values exist only in the raw GeoJSON. The 6 `missing_placeholder` rows are nulled. The 3 `out_of_bounds` rows **keep** their (wrong) coordinates, so a naïve load would plot them (one is in Saudi Arabia at 26.75 N / 37.76 E; another at 18.10 N / 42.19 E; a third at lon 34.45, lat 24.45).
- **Also:** `ok` means "inside a deliberately generous box" (lon 51.0–56.5, lat 22.0–25.5), **not** "inside the emirate". The box includes parts of neighbouring states.
- **Recommendation.**
  - Columns: `source_longitude/source_latitude` (as published, nullable), `longitude/latitude` (**usable**, `NULL` unless `geo_quality ∈ {ok, swapped_repaired}`), `geo_quality` with a `CHECK` on the four values, and `CHECK (geo_quality IN ('ok','swapped_repaired') OR longitude IS NULL)`.
  - **Prerequisite (separate task, not done here):** either load from the raw GeoJSON through the same repair function, or extend `build_facilities.py` to emit the as-published pair. Today `processed/` cannot supply `source_*` for repaired rows. Flagged, not changed.
  - Do **not** attempt to "fix" the `34.45` outlier (it looks like a typo for `54.45`; that is speculation).
- **PostGIS.** The compose image has none. For MVP needs (radius/nearest, scenario 24) plain `DOUBLE PRECISION` columns with range `CHECK`s and an index on `(latitude, longitude)` are enough at 5,339 rows; use the `cube`/`earthdistance` contrib extensions or a haversine SQL function. Switch the image to `postgis/postgis:16-…` **only** if polygon operations (region membership by geometry) are required. Decide once, before the first migration (D6).

### F-23 — SDI vs SCAD must stay separate — **MEDIUM**

Active-only the register has **71 hospitals / 8,828 beds**; SCAD 2801/4111 has **75 / 8,082** (licensed capacity vs operational beds). Recommendation: keep them in different tables with different `source_id` and vintage columns (`as_of_date = 2026-11-15` for the register, which has no publication date); **no foreign key, view or join between `official.facility` and SCAD observations**; maintain the "do not combine" list (quality report §6) as a tested rule in the API layer. A comparison, if shown, is displayed side by side with both definitions, never merged.

---

## 5. Clinical YAML compatibility

All figures below were computed from the YAML on disk.

| Property | Count |
|---|---|
| Rules | **54** (IFHAS 29, WCV 25) in **10 rule types** |
| `screening_package` | 20 (16 verified+clean; **4 verified but `requires_clinical_review`**: cervical Pap, cervical HPV, liquid biopsy, lung LDCT) |
| Unresolved rules | **3** (`IFHAS-PROG-AGE-CEILING`, `WCV-PROG-EFFECTIVE-DATE-TBD`, `WCV-TIMING-DUE-WINDOW`) — all also flagged for review |
| Non-authoritative rules (derived) | **7** of 54 |
| Visit items | **174** across 14 visits, 21 distinct codes; **9 unresolved** (oral exam 15M; head circumference 30–72M; milestones 48–72M) |
| Eligibility conditions | 8, **7 not machine-evaluable**; the one machine-evaluable condition uses attribute `smoking_history.ever_smoked` |
| Open questions | 23 (19 interpretation, 2 governance, 1 data-model, 1 architecture), all `open` |
| Rules with `history` | **0 of 54** |
| `effective_date` | IFHAS `YYYY-MM`; **all 25 WCV rules `null`** (with mandatory note) |

**Can the schema represent all of it? Yes — if the points below are respected.**

### F-24 — Partial and null effective dates — **MEDIUM**
`effective_date` is `YYYY-MM` for IFHAS (the loader explicitly allows `allow_year_month`) and `null` for WCV. A PostgreSQL `date` would force an invented day. Store `effective_date_text TEXT` + `effective_date_precision ∈ {day, month, unknown}` (+ nullable derived `effective_from DATE` only where the day is known), plus `effective_date_note`.

### F-25 — The `history` block does not preserve superseded specs — **HIGH**
`RuleVersionRecord` keeps only `rule_version, source_reference, verification_status, last_reviewed, change_summary` — **not the old `spec`**. Today it is empty for all 54 rules, so nothing has been lost yet. Consequence: an evaluation stored against `(IFHAS-PKG-…, 1.0.0)` cannot be re-derived after a bump unless the database keeps the old rule payload.
**Recommendation.** `clinical.rule` is keyed `(rule_id, rule_version)` and is **append-only**: each load inserts new versions and never updates or deletes an existing one. Add `spec_sha256`; if a loaded `(rule_id, rule_version)` already exists with a different hash, **fail the load** (YAML edited without a version bump). Evaluation tables reference the composite key. Test versioning with fixtures, because the real data has none.

### F-26 — Authority must be derived, not stored — **HIGH**
`is_authoritative` is defined as `verification_status = 'verified' AND NOT requires_clinical_review`, and the loader rejects a configured `authoritative` key. Store it as `GENERATED ALWAYS AS (…) STORED` (or a view); never as an input column. Add `CHECK (verification_status <> 'unresolved' OR requires_clinical_review)` — all 3 unresolved rules satisfy this today. Item-level authority is the item's own `verification_status`.

### Rule storage shape — recommendation
Hybrid, because 54 rules do not justify ten sub-schemas:

- `clinical.rule` (metadata, authority, dates, `spec JSONB` verbatim) **plus typed projection columns for what the engine filters on**: for packages `age_min_years, age_max_years, age_as_printed, sexes TEXT[], frequency_type, interval_value, interval_unit`; for visits `recommended_age_months, visit_number, age_band`; for tiers `instrument, score_min, score_max`. Keep the JSONB as the fidelity copy; the projections are a convenience and must be asserted equal to it in a load test.
- `clinical.rule_condition` (8 rows now): `kind, as_printed, machine_evaluable, attribute, required_value`. Required because `machine_evaluable = false` must force `requires_clinical_review` (lung, liquid biopsy, scenario 11).
- `clinical.rule_item` (174 + IFHAS components): `(rule_id, rule_version, category, code)` unique (verified: no duplicate `(rule, code)` and no code in two categories within a visit), `verification_status`, `source_reference`, `condition`, `open_question_ids`.
- `clinical.open_question` (+ `rule_open_question` link). **Do not use the YAML `affects` field as a foreign key**: it is heterogeneous (`[ifhas, well_child]` vs `[IFHAS-WF-INVITATION-SYSTEM]`). Derive the link from each rule/item's `open_question_ids`, which the loader validates. Add nullable `resolution`, `resolved_on` (the file's header says to add them on resolution).
- Lookups from `status_definitions.yaml`: `evaluation_status` (9), `reason_code` (9), `guard` (7). **Use lookup tables with foreign keys, not PostgreSQL `ENUM`** — the YAML is the source of truth, `OQ-WCV-REFUSAL-STATE` may add values, and `ALTER TYPE` is awkward inside migrations.
- `clinical.standard` for the two sources (`source_name, source_version, document_ref, publication_date, effective_date(+note), revision_date, url`). Both PDFs are **not held**: add `local_copy_sha256 NULL` and `acquisition_state = 'blocked'`. The database must not suggest the standard text is held.

### F-27 — IFHAS components have no stable identifier — **MEDIUM**
Visit items have codes (`oral_examination`); IFHAS `components` are **plain strings** (`'Body Mass Index (BMI)'`, `'Waist circumference / Waist hip ratio'`). Component results (F-06) need a key. Recommendation: the DB loader derives `component_key = slug(text)` deterministically and stores the verbatim text; asking for explicit codes in the next YAML version is better but is a rules change, out of scope here. Do not use the raw string as a foreign key.

### F-28 — Rules that govern more than packages
`evaluation_status` rows must be allowed against **any** rule type: `programme_eligibility` (Thiqa gate, 18+, sex, age ceiling), `visit_schedule`, `developmental_screening_tier`. Scenario 4 (age 78) is only representable as a row against `IFHAS-PROG-AGE-CEILING` with `requires_clinical_review`; recording `not_eligible` against every package would **contradict** the open question (the loader's own rule: >75 → no package result). Scenario 17 (WCV non-attendance) must be an event fact on the visit, never `overdue` — and the database should **not** hard-code "no `overdue` for WCV" as a `CHECK`: that bakes the outcome of an open question (`OQ-WCV-DUE-WINDOW`) into the schema. Enforce it in the engine and test it; revisit when the question closes.

---

## 6. Missing entities, fields, constraints and relationships

### F-01 — No referral entity — **HIGH (blocks 4 scenarios)**
- **Issue.** `referral` appears only as a `gap_type` string and an outreach `event_type`. There is no table.
- **Why.** The rules define referral as a first-class, time-bounded obligation: `WCV-MCHATR-HIGH` (refer to neurodevelopment clinic and speech therapy within 2 weeks, PHC follow-up after 1 month), `WCV-MCHATR-MODERATE`, `WCV-IDAQ-REFERRAL`, `WCV-FU-REFERRAL-INITIATION-7D`, `WCV-FU-SPECIALIST-EVALUATION-2-4W`, `IFHAS-WF-REFERRAL-15WD`. Scenarios 9, 13, 14, 16 and the stated goal "tracks whether care is completed" need it. `referral_not_initiated` cannot be computed without a referral table.
- **Recommendation.** `synthetic.referral`: `referral_id`, `patient_id`, source link (one of `ifhas_screening_id | well_child_visit_id | assessment_id`, `CHECK num_nonnulls = 1`), `trigger_rule_id + rule_version`, `referral_target TEXT` (as printed — Appendix 8 mapping is not encoded), `target_facility_id NULL`, `trigger_date` (the reference event: results release / assessment), `initiated_date`, `completed_date`, `status ∈ {pending, initiated, completed, declined, cancelled}`. **Deadlines are derived from the rule, not stored.**

### F-02 — `unknown` cannot be told from `due` — **HIGH**
- **Issue.** The status definitions require: `due` = interval elapsed with "no qualifying completed screening documented", **never inferred from missing history**; missing history → `unknown`. In the proposed tables, "no mammography on record" (scenario 1, `due`) and "no history at all" (scenario 7, `unknown`) are both **zero rows**. The engine has nothing to branch on. `care_gaps.gap_type = never_screened` also asserts a determination the `unknown` guard forbids.
- **Recommendation.** `synthetic.history_availability (patient_id, pathway, history_status ∈ {available, partial, not_available}, as_of_date)`. `due` requires `available`; otherwise `unknown`. Rename `never_screened` to `no_documented_screening` and only allow it when history is `available`.

### F-03 — Evaluations are "regenerated"; trace destroyed — **HIGH**
- **Issue.** Spec §3.4: "one row per patient per applicable rule, regenerated on evaluation." Care gaps, outreach and overrides hang off these rows.
- **Why.** Rules require evaluation "traceable to a `rule_id` and `rule_version`". Regeneration replaces the evidence a clinician acted on and orphans foreign keys. Age depends on an unspecified reference date (`OQ-COMMON-AGE-CALC`), which is not recorded.
- **Recommendation.** Append-only `eligibility_evaluation (evaluation_id, patient_id, rule_id, rule_version [composite FK], evaluation_run_id, reference_date, evaluated_at, evaluation_status [FK], reason_code [FK, single primary reason by guard precedence], next_due_date NULL)`. A `current_evaluation` view selects the latest per `(patient, rule)`. Drop `requires_clinical_review` (it is exactly `evaluation_status = 'requires_clinical_review'`). Store `not_eligible` rows too, so "evaluated and not eligible" differs from "never evaluated". Volume (≈ 7,000 × ~34 rules ≈ 240 k rows per run) is trivial.

### F-04 — `care_gaps` mixes three concerns — **HIGH**
- **Issue.** One row carries the rule-derived gap, the model's `priority_score`, and a single nullable `clinician_override`.
- **Why.** The standards require that a model may only **order** rule-identified gaps, that a score always has an explanation (RAI §3.1.6.3), and that overrides are recorded with an audit trail (§3.1.7.2.3; scenario 27). One nullable override column records the last override, not the trail. There is also no lifecycle (open/closed/suppressed) or closing evidence, so "has care been completed?" is unanswerable.
- **Recommendation.** `care_gap` (rule fact: `evaluation_id` FK, `gap_type`, `identified_date`, `status ∈ {open, closed_completed, closed_refused, suppressed, superseded}`, `closed_date`, `closed_by_event`), scoring columns kept on it **with** `scored_by_model_version`, `scored_at`, `priority_explanation` and `CHECK (priority_score IS NULL OR priority_explanation IS NOT NULL)`, and an append-only `care_gap_review (review_id, care_gap_id, reviewer, action, previous_priority, new_priority, reason NOT NULL, reviewed_at)`. AI opt-out is represented by `scored_at IS NULL` plus a `scoring_suppressed_reason`. Drop `pathway` (derivable from the rule).

### F-05 — Refusal is represented three times and the status model is undecided — **HIGH, blocking**
- **Issue.** `refused` is a `completion_status` (IFHAS), an `attendance_status` (WCV) and a `consent.state`. `OQ-WCV-REFUSAL-STATE` (category `data-model`) says: "A status-model decision is needed **before database design**."
- **Recommendation (decision D2).** Keep the 9-value evaluation vocabulary unchanged; refusal is **not an evaluation status**. Refusal is a documented *fact* with a scope:
  1. component- or screening-level: `component_result.result_status = 'refused'` with `documented_in_record`, `signature_on_file` (the standard's §4.2.1 requirement is about *a specific refused screening*);
  2. patient/pathway-level: a `consent` row `consent_type = 'screening_participation'`, `state = 'refused'`, with nullable `pathway`/`rule_id` scope;
  3. the care-gap lifecycle then closes as `closed_refused`.
  Remove `refused` from `completion_status`/`attendance_status` to leave one source of truth. Needs owner sign-off because it settles an open question.

### F-06 — Component arrays — **HIGH**
- **Issue.** `components_completed` / `components_outstanding` (and the WCV `assessments_*` pair) are arrays of free text. They are complements of one another and of the rule, so they can disagree, carry no foreign key, and cannot express **item-level unresolved** (scenario 25: oral exam at 15 months blocks one item, not the visit).
- **Recommendation.** One `component_result (screening_or_visit link [num_nonnulls = 1], rule_id, rule_version, item_category, item_code → clinical.rule_item, result_status ∈ {completed, refused, not_done, not_applicable}, performed_date, documented_in_record, signature_on_file)`. "Outstanding" is **derived** (rule items − recorded results), excluding items whose `verification_status <> 'verified'`. `partial` completion (IFHAS §4.11.4.3: claims cannot be submitted) is derived from the same data.

### F-07 — No attribute for a machine-evaluable rule — **HIGH**
`IFHAS-PKG-AAA-M-65-75` has a machine-evaluable condition on `smoking_history.ever_smoked`; scenarios 11–12 use smoking. `patients` has no such field. MVP minimum: nullable `ever_smoked BOOLEAN` on `patients` (NULL → `insufficient_information` per the status definitions). Pack-years and the lung/liquid-biopsy criteria are **not** machine-evaluable and need nothing. If more attributes follow, move to a typed `patient_attribute (patient_id, attribute_code, value, status)` keyed on the rule's `attribute` strings.

### F-08 — Polymorphic `encounter_id` — **MEDIUM**
`assessments.encounter_id` "visit or screening" cannot carry a foreign key. Use two nullable FKs (`ifhas_screening_id`, `well_child_visit_id`) with `CHECK (num_nonnulls(…) = 1)`. Do not introduce an `encounter` supertype for the MVP — the two event tables differ (guardian, age-in-months, catch-up vs package, claims).

### F-09 — Appointment / event / outreach linkage — **MEDIUM**
- `appointments` has no FK to the screening or visit it produced; both repeat `scheduled_date`. Put `appointment_id` on the event tables and drop `scheduled_date` from them.
- `outreach_events` has no FK to the appointment it led to, so "outreach → booking" (the impact measure) cannot be attributed; add `appointment_id NULL`.
- `outreach_events.recipient = 'guardian'` has no `guardian_id`; add it with `CHECK ((recipient = 'guardian') = (guardian_id IS NOT NULL))`.
- `appointments.reminder_count` is derivable from outreach rows; drop it. `slot_type` is derivable from `scheduled_datetime` + facility hours; keep only if scenario tests need it stored.
- Drop the `outreach_events.suppressed` boolean; `delivery_status = 'suppressed'` plus `suppression_reason` says it once.
- `IFHAS-WF-REFERRAL-15WD` counts **working days**. No calendar exists in the repo or the design. Add a small configuration table `working_calendar (date, is_working_day)` (or an engine setting) — and do not hard-code weekend/holiday assumptions; they are not specified anywhere reviewed.
- Contact validity (scenario 23, "wrong contact details, 3 failed invitations"): add `contact_status ∈ {valid, wrong, unverified}` columns to `patients` and `guardians`; a separate `contact_point` table is **not** justified for the MVP.

### F-29 — Consent refinements — **MEDIUM**
Make `consent` append-only (current state = latest per `(patient, consent_type, scope)`); drop `never_requested` as a stored value (absence of a row means never requested, otherwise two representations coexist); add `guardian_id` for `applies_to = 'child_by_guardian'`. The table name says "preferences" but the preferences live on `patients`; consider renaming to `consent`.

### Constraints worth stating explicitly
`CHECK (date_of_death IS NULL OR date_of_death >= date_of_birth)`; `CHECK (id ~ '^SYNTH-PAT-[0-9]{6}$')` on every synthetic key; `CHECK (is_synthetic)`; `CHECK (age band bounds: min <= max)`; composite FK `(rule_id, rule_version)` everywhere a rule is cited; `ON DELETE RESTRICT` on all audit/clinical references.

---

## 7. Redundant or unnecessary design elements

| Element | Why unnecessary | Action |
|---|---|---|
| `screening_eligibility.requires_clinical_review` | Equals `evaluation_status = 'requires_clinical_review'` | Drop |
| `components_outstanding`, `assessments_outstanding` | Derivable (rule items − results); can contradict | Drop (F-06) |
| `appointments.reminder_count` | Count of outreach rows | Drop |
| `outreach_events.suppressed` | Duplicates `delivery_status` | Drop |
| `care_gaps.pathway` | Derivable from rule | Drop |
| `ifhas_screenings.scheduled_date` / `well_child_visits.scheduled_date` | Duplicates `appointments.scheduled_datetime` | Drop |
| `assessments.is_diagnosis` | Constant `false` | Keep as `CHECK`, or document; no stored column needed |
| Per-row `generator_version`, `generation_seed`, `clinically_validated` ×11 tables | Constant per generation run | Single `synthetic.generation_run` + `run_id` FK per row; keep per-row `is_synthetic` and the `SYNTH-` prefix. **This deviates from spec §1.1 and needs sign-off** (D8) |
| Synthetic `facilities` | Superseded | Replace (F-20) |
| Child tables for `BEDS`/`SPECIALITIES`/`PROFESSIONALS` | No MVP consumer | Defer |
| SDI `thiqa/basic/enhanced`, contact fields | Constant `N/A` / not permitted | Do not load |
| `MAX_VALUE`, `MIN_VALUE`, `MAX_OBS_DT`, `MIN_OBS_DT`, `Name` | Not observations / duplicates | Do not load |
| Loading `scad_*.xlsx` into `observation` | Duplicates API; differs by 2 births | Defer (F-19) |
| `ingestion_run` table | Provenance fits on `source_file` (`sha256, retrieved_at, loader_version`) | Omit |
| An `encounter` supertype | Two event tables differ materially | Omit |

Over-engineering to avoid: EAV observations; a facility-site hierarchy; PostgreSQL `ENUM`s for YAML-owned vocabularies; partitioning or materialised views at ≤ 240 k rows.

---

## 8. Recommended changes to the proposed schema

Three PostgreSQL schemas with **one-way dependencies**: `synthetic → clinical`, `synthetic → official`; `official` and `clinical` never reference `synthetic`.

| Schema | Tables | Count |
|---|---|---|
| `official` | `source`, `source_file`, `region`, `indicator`, `indicator_dimension`, `dimension_member`, `observation`, `facility`, `license_status_map` | 9 |
| `clinical` | `standard`, `rule`, `rule_condition`, `rule_item`, `open_question`, `rule_open_question`, `evaluation_status`, `reason_code` | 8 |
| `synthetic` | `generation_run`, `patients`, `guardians`, `consent`, `facility_service_profile`, `history_availability`, `eligibility_evaluation`, `ifhas_screening`, `well_child_visit`, `component_result`, `assessment`, `referral`, `care_gap`, `care_gap_review`, `appointment`, `outreach_event` | 16 |

(The 11 proposed tables become 16: `facilities` replaced by `facility_service_profile`; **new** `referral`, `component_result`, `care_gap_review`, `history_availability`, and the optional `generation_run`.)

**Provenance model (official).** `source` mirrors the manifest (`id`, name, publisher, licence text, attribution statement, `acquisition_state`, `validation_state`) with `CHECK (acquisition_state NOT IN ('dataset_obtained','document_obtained') OR local_sha256_present)` enforced through `source_file`. `source_file` mirrors `raw_checksums.sha256` (215 rows, all verified here). Every `observation` and `facility` row carries `source_file_id`, a vintage (`period_year` or `as_of_date`), and the loader version.

**Do not mark acquired what is not held.** `SRC-02` and `SRC-03` (the standards) must load as `blocked`; the 5 Gov-Digital workbooks as `dataset_obtained` with `contains_data = false`; MOHAP nurses as `dataset_obtained`, `fit_for_use = false`.

### 8.1 PostgreSQL / SQLAlchemy improvements worth making

- **Separate schemas and roles.** App role read-only on `official` and `clinical`; the loader role owns them. In SQLAlchemy 2.0: one `DeclarativeBase` per schema or `MetaData(schema=…)`, typed `Mapped[...]` columns, and a shared `naming_convention` so constraint names are stable for migrations.
- **Types.** `NUMERIC` for observation values; `TIMESTAMPTZ` for events (store UTC; scheduling in `Asia/Dubai`); `DATE` where precision is a day; `TEXT` + FK/`CHECK`, not `ENUM`; `BIGINT GENERATED ALWAYS AS IDENTITY` for official surrogate keys; natural `TEXT` keys with `CHECK` for `SYNTH-…` ids.
- **Constraints as documentation.** `UNIQUE NULLS NOT DISTINCT` (PG ≥ 15), partial unique indexes (3422), composite FKs for rule versions, `GENERATED … STORED` for `is_authoritative`, `DEFERRABLE INITIALLY DEFERRED` FKs for the loaders.
- **Bulk load.** Use `psycopg` `COPY` (already a dependency), not `pandas.to_sql`; the volumes are small but COPY keeps types exact (no float round-trip).
- **Migrations.** `alembic` is **not** in `backend/requirements.txt`; adopt one tool before the first migration (D7). Not done here.
- **Residency guard.** Because `OQ-GOV-DATA-RESIDENCY` is open, add `CHECK (is_synthetic)` on every `synthetic` table (DEFAULT true) and keep `synthetic` structurally separate from anything a real-data path would use.
- **Indexing.** Index every FK; `(indicator_id, period_year)`; `(patient_id, rule_id, evaluated_at DESC)`; `(status) WHERE status = 'open'` on `care_gap`; `(latitude, longitude)` on `facility`.

---

## 9. Unresolved decisions and risks

### Decisions that block the ERD

| # | Decision | Recommendation | Why it blocks |
|---|---|---|---|
| **D2** | How is refusal represented? (`OQ-WCV-REFUSAL-STATE`) | §6 F-05: not an evaluation status; component/consent scope; one source of truth | Changes four tables; the open question itself says "before database design" |
| **D1** | Synthetic patients attached to real facilities, with a simulated-capability overlay? | Yes (F-20) | Changes `patients` FK and the facility tables |

### Decisions needed before implementation (do not block the ERD)

| # | Decision | Recommendation |
|---|---|---|
| D3 | Meaning of `-` and `:` | Store raw; ask SCAD; map nothing until answered |
| D4 | `2026-01-04` ⇒ `1-4`; are corrupted labels year-variant? | Pattern remap; confirm with SCAD |
| D5 | Treatment of duplicate-key 3422 | Quarantine both rows; ask SCAD |
| D6 | PostGIS or plain coordinates | Plain + `earthdistance` for MVP |
| D7 | Migration tool | Adopt Alembic; not installed today |
| D8 | Replace per-row provenance columns with `generation_run` | Yes, but it amends spec §1.1 |
| D9 | Load workbooks into `observation`? | No for MVP |
| D10 | IFHAS component codes | Loader-derived slugs now; YAML codes in a later rules version |
| D11 | Keep evaluation history or current only | Keep history; trivial volume |
| D12 | Working-day calendar source | Configuration table; no hard-coded weekend |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Silent double-count or wrong total from year-varying aggregates | **High** if unmitigated | High (wrong denominators on a dashboard) | F-11: member roles, leaf-only views, additive flag, reconciliation test |
| Re-fetched SCAD data breaks the age-band remap | Medium | Medium | Pattern-based remap; tested on a `2027-…` fixture |
| Mixed vintages (2022 vs 2025; SDI vs SCAD) shown as one figure | Medium | High | Vintage column on every row; no cross-source join; API-level test |
| A synthetic row or real facility name misread as real operations data | Medium | **High** (governance story) | `SYNTH-` keys, `CHECK (is_synthetic)`, simulated-capability banner, schema separation |
| Rule edited without a version bump | Medium | High | `spec_sha256` mismatch fails the load; append-only versions |
| `OQ-*` closes and forces schema change | High over time | Low if lookups, not ENUMs | Lookup tables; no CHECK encoding open-question outcomes |
| 434 anonymous facility points plotted or selected | Medium | Medium | `identity_status`; excluded from default views |
| Bounding-box "ok" taken as "inside the emirate" | Medium | Low | Document; optional polygon check later |
| `processed/facilities/` loses as-published coordinates | Certain | Medium | Prerequisite change to the transformation (not done here) |

### Corrections found in existing documents (for the owners of those files)

These are discrepancies between the documents and the files on disk. None were changed here.

1. **Age-label corruption** affects 4 indicators / 3 labels, not 1 / 2 (acquisition report §6.3; manifest `SRC-17`; quality report A3).
2. **Aggregate rule** is not year-invariant (F-11); the acquisition report §8 and README present it as a simple filter.
3. **Acquisition report §3.1 headline** "Under-five mortality rate | 3280 | 6.99 | 2015–2025": **6.99 is the 2024 value**; indicator 3280 has no emirate member for 2025. (Infant mortality 5.38 for 2025 *is* present in 3319.)
4. **Acquisition report §3.1** "Health insurance members | 2677 | 1,024,271": that is the **Thiqa** type only. The three types for 2025 are Daman Basic 1,284,933, Enhanced 1,867,598, Thiqa 1,024,271. Thiqa is 23.5% of the 2025 population estimate (1,024,271 / 4,358,921) — a possible calibration parameter for the `thiqa_member` flag, **not** an eligibility rule.
5. **Quality report C7**: `scad_health_tables_en.xlsx` does state its periods — 2008–2012, 30 stacked tables.
6. **Quality report B3 / data dictionary §5**: the 434 `rehabilitation_center` rows lack **all** identifying attributes, not just region and status.
7. **API vs XLSX births 2025** agree on the total but differ by 2 in the Emirati/Non-Emirati split (F-19, §4).
8. **`synthetic_data_spec.md` §2, §3.3, §8** are stale against the new data (2022 anchors, "only 2024 births", invented coordinates, H6 open).
9. `statad_api/acquisition_log.json` records file paths in **another session's temporary directory**; the SHA-256 values remain valid, the paths are not portable.
10. `out_of_bounds` coordinates are retained in the CSV, whereas the data dictionary says such rows "have no usable coordinates"; consumers must test `geo_quality`, not nullness.

### What this review did **not** verify

The 71 metadata workbooks were sampled (one read in full), not all read. Arabic labels were checked only where age corruption was tested. The cross-checks between SDI and SCAD, and all published totals, were taken from the quality report (the facility 71 / 8,828 figure was recomputed). No clinical content was reviewed; nothing here is clinically validated.

---

## 10. Final recommendation

# ✅ APPROVED WITH CHANGES

**Why not APPROVED.** The reviewed design covers one of three layers, is stale against data now held, and cannot express several of its own acceptance scenarios (referrals, `unknown` vs `due`, per-component results, override audit, smoking attribute). Approving it unchanged would bake a known gap — "history missing" vs "history absent" — into the foundation, and would force an unplanned migration the first time a referral is modelled.

**Why not NOT APPROVED.** The core is correct and worth keeping: the synthetic/official separation, the guard-driven status vocabulary, the explicit refusal and AI-opt-out states, the `SYNTH-` safety rules, and the rule-ID-based traceability. No table needs deleting. The rules and all 215 raw files are consistent enough to support a sound schema; the required changes are additions and corrections, not a redesign. All 54 rules, 174 items and 23 open questions are representable.

**Conditions before the ERD is drawn.**

1. Resolve **D2** (refusal representation) and **D1** (real facilities with a synthetic overlay).
2. Adopt the three-schema layout and the table list in §8, including the 4 required additions.
3. Apply the `official` findings F-11 to F-23 (member roles, `measure_kind`, value markers, age-band bounds with pattern remap, quarantine of 3422, API-only observation load).
4. Apply the `clinical` findings F-24 to F-28 (append-only `(rule_id, rule_version)`, derived authority, partial dates, lookups not ENUMs).
5. Record the follow-up tasks this review deliberately did **not** perform: emit as-published coordinates from the facility transformation; refresh the stale spec sections; correct the document discrepancies in §10; raise the SCAD queries (D3–D5).

**Conditions before implementation (after the ERD).** Choose a migration tool (D7), settle D3–D6 and D8–D12, and write the load-time reconciliation tests named in F-11 and F-25 before any loader.

---

## Appendix A — Verification log

All commands were run from the repository root; nothing under the repo was modified except this file (a throw-away virtual environment was created outside the repo for `pytest`/`openpyxl`).

| Check | Result |
|---|---|
| `shasum -a 256 -c data/reference/raw_checksums.sha256` | 215 OK |
| `pytest` in `data-pipeline/` | **80 passed** |
| Rule YAML profile | 54 rules, 10 types, 7 non-authoritative, 174 items / 9 unresolved, 8 conditions / 7 not machine-evaluable, 23 open questions, 0 histories |
| SCAD API profile (86 files) | 14,913 rows; 0 null `VALUE`; all `OBS_DT` = 1 Jan; `YEAR` = `OBS_DT` year for every row; 65 aggregate-bearing, 35 with `Missing/Unknown`, 37 shape-changing; 1 duplicate-key indicator (3422); 4 indicators with date-corrupted age labels |
| Facility CSV profile (5,339 rows) | `(source_layer, facility_id)` unique; `license_no` unique where present (4,905); 434 identity-less rows; 15 status values; 24 co-located groups (50 rows) |
| Workbooks | 5 SCAD + 7 open-data files opened; births 2025 Table 1 read cell-by-cell; `scad_health_tables_en.xlsx` titles enumerated (30 tables, 2008–2012) |
| Manifest | `SRC-02`, `SRC-03` are `blocked`; no standards PDFs on disk |
