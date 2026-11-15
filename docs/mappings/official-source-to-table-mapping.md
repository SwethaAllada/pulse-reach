# PulseReach — `official` schema: source-to-table mapping

**Phase 3, Step 3 (design only).** No SQL, SQLAlchemy model, migration, loader or transformation code was written or changed. This document specifies how every `official` table is populated from the files that are actually in the repository.

**Date:** 2026-11-15
**Canonical design:** [`../phase-3-database-design.md`](../phase-3-database-design.md) revision 2.3 (§3, §2, §6.3, §8). **ERD:** [`../erd/official-schema-erd.md`](../erd/official-schema-erd.md).
**Companions:** [`clinical-yaml-to-database-mapping.md`](clinical-yaml-to-database-mapping.md), [`data-loading-and-validation-strategy.md`](data-loading-and-validation-strategy.md).
**Status:** **DRAFT for review.** Nothing here is clinically, legally, governance- or publisher-approved. **D6, D7, D11 are recommendations awaiting owner confirmation (not approved). D3, D4, D5, D13 still need external clarification. D2 is provisional.** The mapping is written so that none of those decisions has to be guessed: wherever one matters, the source ambiguity is preserved and the interim behaviour is stated.

> **How to read the mappings.** `$` is a parsed JSON file. `$.Data.Data[i]` is the *i*-th (0-based) observation record of an indicator file. "Verbatim" means no trimming, case change, re-encoding or type coercion. A "loader assertion" fails the load (nothing is written for that unit); a "report" records a finding and the load continues. Both are defined in the strategy document.

---

## 0. What was inspected

| Input | How |
|---|---|
| `docs/phase-3-database-design.md` (rev 2.3), both ERDs | Read (§§0–4, 6.3, 7–12 of the design in full) |
| `data/README.md`, `data/metadata/data_quality_report.md` | Read in full |
| `data/metadata/data_dictionary.md`, `docs/data-acquisition-report.md` | Read the sections on SCAD API, SDI facilities, data-quality findings (§§4–6 / §6) — not every line |
| `data/reference/source_manifest.yaml` | Parsed: 24 sources; all keys enumerated; SRC-02/03/10/11/17/18/19/20/21 read in full |
| `data/reference/raw_checksums.sha256` | **Re-verified in this step: all 215 files `OK`** (`shasum -a 256 -c`) |
| `data/raw/statad_api/` | **All 86 indicator JSON files parsed** (14,913 rows); all 71 metadata workbooks opened; `acquisition_log.json` read |
| `data/raw/abudhabi_sdi/` | **All 9 GeoJSON files parsed** (5,339 features, 43 properties); `_source` blocks read |
| `data/raw/scad/`, `data/raw/abudhabi_opendata/` | File inventory and manifest/quality-report statements only (workbooks are provenance, D9) |
| `data/processed/facilities/` + `data-pipeline/transformation/build_facilities.py` | Read; the repair logic is the reference for `geo_quality` |
| `data-pipeline/ingestion/*.py` | Read the SCAD and SDI fetchers |

Numbers quoted below as "verified" were recomputed from the files in this step, not copied from documentation.

---

## 1. Source inventory and file registration

215 files are registered in `official.source_file`, one per line of `data/reference/raw_checksums.sha256` (4 comment lines + 215 entries).

| Path pattern | Files | `source_id` | `file_role` | `contains_data` |
|---|---|---|---|---|
| `data/raw/statad_api/indicator_detail/*.json` | 86 | `SRC-17-SCAD-STATISTICS-API` | `indicator_detail` | true |
| `data/raw/statad_api/indicator_metadata/*.xlsx` | 71 | `SRC-17-…` | `indicator_metadata` | true |
| `data/raw/statad_api/acquisition_log.json` | 1 | `SRC-17-…` | `other` | false (a log) |
| `data/raw/abudhabi_sdi/*.geojson` | 9 | `SRC-18-ABUDHABI-SDI-FACILITIES` | `facility_geojson` | true |
| `data/raw/abudhabi_sdi/acquisition_log.json` | 1 | `SRC-18-…` | `other` | false |
| `data/raw/scad/scad_health_statistics_2022_en.xlsx` | 1 | `SRC-10-SCAD-HEALTH-2022` | `publication_workbook` | true |
| `data/raw/scad/scad_birth_statistics_2024_en.xlsx` | 1 | `SRC-11-SCAD-BIRTHS-2024` | `publication_workbook` | true |
| `data/raw/scad/scad_birth_statistics_2025_en.xlsx`, `scad_death_statistics_2025_en.xlsx` | 2 | `SRC-19-SCAD-VITAL-2025` | `publication_workbook` | true |
| `data/raw/scad/scad_health_tables_en.xlsx` | 1 | **none — see OU-14** | `publication_workbook` | true |
| `data/raw/abudhabi_opendata/metadata/*.json` (33) + `catalogue_search_results.json` (1) | 34 | `SRC-20-ABUDHABI-OPENDATA-CATALOGUE`; files whose name starts `mohap_` → `SRC-21-MOHAP-NURSES-2008` | `catalogue` | true |
| `data/raw/abudhabi_opendata/acquisition_log.json` | 1 | `SRC-20-…` | `other` | false |
| `data/raw/abudhabi_opendata/files/govdigital_*.xlsx` | 5 | `SRC-20-…` | `other` | **false** (one dead-URL cell each; loader re-asserts ≤ 1 non-empty cell) |
| `data/raw/abudhabi_opendata/files/mohap_nurses_*.xlsx` | 2 | `SRC-21-…` | `other` | true; `fit_for_use = false` (manifest: "NOT FIT FOR USE") |
| **Total** | **215** | | | |

**Role/ownership rules are by path, not by content sniffing.** A file that matches no row of this table is a loader error (`unmapped_file`), never a guess.

---

## 2. `official.source`

**Source:** `data/reference/source_manifest.yaml` → `sources[]` (24 entries; `manifest_version` `2.0.0`). One row per entry, **including** blocked, excluded and researched ones, so "held" vs "only researched" is queryable.

| Destination | Source field | Type / conversion | Transformation | Null / missing handling |
|---|---|---|---|---|
| `source_id` (PK) | `sources[].id` | TEXT verbatim | none | required; a missing/duplicate id fails the load |
| `name` | `sources[].name` | TEXT verbatim | none | required |
| `publisher` | `sources[].publisher` | TEXT verbatim | none | required (present on all 24 — loader asserts) |
| `url` | `sources[].url`, else `landing_page`, else `service_url` | TEXT | first non-null in that order; all three are publisher-stated URLs, never constructed | `NULL` if none |
| `licence_text` | `sources[].licence`, else `sources[].permitted_reuse` | TEXT verbatim | `COALESCE(licence, permitted_reuse)`. The manifest carries licence wording in `permitted_reuse` (8 sources) and in `licence` (1 string, 23 null); there is no other field | `NULL` = not recorded |
| `attribution_statement` | **no manifest field** | TEXT | **Not populated** by the loader (the attribution wording is prose in `data/README.md` §"Attribution requirement" and inside `permitted_reuse`). Parsing it out would be an interpretation | always `NULL` today (**OU-15**) |
| `acquisition_state` | `sources[].acquisition.state` | TEXT, CHECK 5 values | verbatim. Observed: `blocked` 11, `dataset_obtained` 7, `excluded` 4, `researched` 2, `document_obtained` 0 | required |
| `validation_state` | `sources[].validation` | TEXT | **only when** `acquisition_state ∈ {dataset_obtained, document_obtained}` (verbatim: `structural` ×7); otherwise `NULL` even where the manifest says `none` | a value `clinical` is **rejected** (design: nothing is clinically validated) |
| `fit_for_use` | none at source level | BOOLEAN | `NULL` (not assessed). Set only at file level (§3) | `NULL` |
| `contains_data` | none at source level | BOOLEAN | `NULL` | `NULL` |
| `acquisition_reason` | `sources[].acquisition.reason` | TEXT verbatim | only present for `blocked`/`excluded` | `NULL` otherwise |
| `manifest_version` | top-level `manifest_version` | TEXT | `'2.0.0'` | required |

**Primary/foreign keys.** PK `source_id`. No FKs.
**Unique-key handling.** Upsert on `source_id`. An existing row is updated only when `manifest_version` differs; an existing row with the *same* `manifest_version` but different content fails the load (the manifest was edited without a version bump).
**Validation.**
- *Loader assertions:* 24 rows; ids unique; `SRC-02-IFHAS` and `SRC-03-WCV` have `acquisition_state = 'blocked'` (the database must never suggest the standards' text is held); no `validation_state = 'clinical'`; for every `dataset_obtained` source at least one `source_file` is registered after §3 runs.
- *DB constraints:* PK, `acquisition_state` CHECK, `validation_state` CHECK.
- *Deferred constraint trigger (design §3.2):* `dataset_obtained`/`document_obtained` ⇒ ≥ 1 `source_file`.

**Provenance.** The row *is* the provenance of the source; `manifest_version` ties it to the manifest revision, and the manifest file's SHA-256 is recorded in the load report (the manifest is not itself in `raw_checksums.sha256`).

**Not loaded:** `api`, `coverage`, `limitations`, `relevance`, `provides`, `belongs_in`, `datasets_sought` etc. (prose; remain in the YAML, which stays the source of truth for them).

---

## 3. `official.source_file`

**Source:** one record per non-comment line of `raw_checksums.sha256` (`<sha256>  <relative_path>`), enriched from the file itself and the manifest.

| Destination | Source | Conversion / rule | Null handling |
|---|---|---|---|
| `source_file_id` | — | identity | — |
| `source_id` | path rule in §1 | FK → `source` | unmapped path ⇒ error |
| `relative_path` | checksum line, second field | repo-relative, as written (`data/raw/...`). **Never** the absolute paths found in the `acquisition_log.json` files (they point into a temporary directory of another session and are not portable) | required, UNIQUE |
| `sha256` | checksum line | lower-case hex, `CHECK ~ '^[0-9a-f]{64}$'`. **Recomputed from the bytes by the loader** and compared with the checksum line; mismatch fails the whole run | required; **not unique** |
| `byte_size` | filesystem `stat` | BIGINT | required |
| `file_role` | §1 table | CHECK 6 values | required |
| `retrieved_at` | see below | TIMESTAMPTZ (UTC) | **`NULL` = not recorded; never defaulted to load time** |
| `source_effective_note` | see below | TEXT, free text, **never parsed into a date** | `NULL` |
| `contains_data` | §1 table + loader assertion for the 5 Gov-Digital workbooks | BOOLEAN | required |
| `fit_for_use` | `false` only for the two `mohap_nurses_*.xlsx` (manifest SRC-21: "NOT FIT FOR USE") | BOOLEAN | `NULL` otherwise |
| `loader_version` | loader constant | TEXT | required |
| `registered_at` | `now()` | TIMESTAMPTZ | — |

**`retrieved_at` — what the files actually say (verified).**

| Files | Evidence available | Mapping |
|---|---|---|
| 9 SDI GeoJSON | each carries `_source.retrieved`, e.g. `2026-11-14T13:20:17Z` … `13:20:58Z` | use it (UTC, second precision). **It disagrees with the manifest/README ("retrieved 2026-11-15")** — the in-file stamp is the primary evidence; the disagreement is reported (**OU-13**) |
| 86 + 71 SCAD API files | **no timestamp in the files, none in `acquisition_log.json`** (it records path, size, sha256, row count, title, `updated`). The manifest gives only `downloaded: 2026-11-15` (a date) | **`NULL`**. A date is not a timestamp; storing `2026-11-15T00:00:00Z` would invent precision (**OU-13**) |
| 5 SCAD workbooks | manifest `downloaded` (date) and HTTP `Last-Modified` header (publisher-side) | `retrieved_at = NULL`; header goes to `source_effective_note` as text, e.g. `HTTP Last-Modified: 2026-09-30 13:08:58+00:00` |
| Open-data files | per-entry content of `acquisition_log.json` is **not** profiled here | use a timestamp only if the entry carries one; otherwise `NULL` |

**`source_effective_note`** carries publisher-stated dates as text only: for each SCAD indicator JSON `Metadata.updated` verbatim (e.g. `Metadata.updated=2025-12-19T00:00:00`); for metadata workbooks `Last data update` verbatim; for the catalogue the `modified` value; for SCAD workbooks the `Last-Modified` header. It is **not** `facility.source_effective_date` and never feeds a vintage ordering.

**Consequence of a `NULL` `retrieved_at`.** `v_observation_current` ("latest `source_file` per indicator by `retrieved_at`") is well-defined today only because each indicator has exactly one detail file. The loader therefore **refuses to register a second detail file for an indicator while either file has `retrieved_at IS NULL`** (it cannot order them) — see strategy §8.

**Keys / uniqueness.** `UNIQUE (relative_path)`. Re-running with the same path and same hash is a no-op. The same path with a **different** hash is an error (raw files are immutable; a new vintage must be written to a **new path**, e.g. a dated directory, because D9's "new vintage = new `source_file`" cannot coexist with `UNIQUE(relative_path)` otherwise). `sha256` duplicates are allowed and reported.
**Validation.** *Loader:* 215 lines = 215 files on disk = 215 recomputed hashes; every file maps to a source (214 today — **OU-14**); every `dataset_obtained` source has ≥ 1 file; the 5 `govdigital_*.xlsx` contain ≤ 1 non-empty cell. *DB:* UNIQUE, CHECK on `sha256` format and `file_role`, FK.
**Provenance.** This table is the provenance anchor for everything else.

---

## 4. `official.region`

**Source:** seeded by the loader (3 rows), labels taken from the data, not typed in.

| `region_id` | `region_code` | `scad_label` (verbatim from `REGION_EN`) | `sdi_label` (verbatim from SDI `REGION`) | `name_en` | `name_ar` |
|---|---|---|---|---|---|
| 1 | `AD` | `Abu Dhabi Region` | `Abu Dhabi` | = `scad_label` | the single distinct `REGION_AR` paired with that `REGION_EN` |
| 2 | `AIN` | `Al Ain Region` | `Al Ain` | = `scad_label` | idem |
| 3 | `DHF` | `Al Dhafra Region` | `Al Dhafra` | = `scad_label` | idem |

- The **codes and the `region_id` ↔ code assignment are loader constants** (the design fixes `CHECK IN ('AD','AIN','DHF')`). Labels are **asserted to exist** in the data: all three `scad_label`s appear in `REGION_EN`; all three `sdi_label`s are exactly the non-null `REGION` values in the SDI files (verified: `Abu Dhabi` 3,178, `Al Ain` 1,236, `Al Dhafra` 491).
- `name_ar`: the loader reads the Arabic label from the API. **Loader assertion:** each of the three `REGION_EN` labels maps to exactly one `REGION_AR` among `Abu Dhabi Region`/`Al Ain Region`/`Al Dhafra Region` rows (verified 1:1). If it does not, `name_ar` stays `NULL` (never invented).
- **Never regions:** `Emirate of Abu Dhabi`, `Abroad`/`abroad`, `Missing/Unknown`, `Other`, `Not stated`. They become `dimension_member`s with `region_id = NULL` (§7).
- *Idempotency:* upsert on `region_code`; any differing existing label fails the load.
- *Provenance:* labels are source-derived; the loader version is in the load report (the table has no provenance columns by design).

---

## 5. `official.indicator`

**Source:** one row per `statad_api/indicator_detail/<id>_<slug>.json` (86, verified). Definition text from the matching metadata workbook for 71; the 15 without a workbook are `2679, 2705, 2728, 2732, 3178, 3267, 3269, 3274, 3280, 3281, 3319, 3321, 3498, 3813, 3997` (verified).

| Destination | Source | Conversion / rule | Null handling |
|---|---|---|---|
| `indicator_id` (PK) | `$.Data.Configuration[0].indicatorId` (string) | `int()`; **assert equals the numeric prefix of the file name** (verified for all 86) | required |
| `slug` | file stem (e.g. `3463_births_by_citizenship`) | verbatim; UNIQUE | required |
| `title_en` | `$.Data.Metadata.component_title` | verbatim (trim outer whitespace only). Titles end in ` - Annually` | required |
| `definition_en` | `$.Data.Metadata.component_subtitle` | verbatim (non-empty for all 86 — verified) | `NULL` if empty |
| `unit_raw` | `$.Data.Configuration[0].unit` | **verbatim, 13 distinct strings** (verified), including `People\ Square kilometer` (literal backslash) and `Death per 1,000 Population in a specific age-group`. Not trimmed, not normalised | required |
| `measure_kind` | reviewed mapping `unit_raw → kind` (below) | CHECK 6 values | **`unclassified` until the mapping is reviewed** (**OU-10**) |
| `is_additive` | generated | `measure_kind = 'count'` | never written by the loader |
| `series_kind` | title | `projected` iff `title_en` matches `(?i)projection`; else `observed`. **Verified: this is 4 indicators — 4866, 4868, 4869, 4870** (all have years 2024/2030/2035/2040). The design text says "4868 is projected"; the rule covers all four (discrepancy D-1) | required |
| `periodicity` | `$.Data.Configuration[0].timeUnit` | `['Yearly'] → 'annual'`. **Assertion:** all 86 are `['Yearly']` (verified) and no row has `MONTH_*`/`QUARTER_*` set (verified: 0) | any other ⇒ fail (the CHECK allows only `annual`) |
| `region_basis` | title / reviewed mapping | see below | `unspecified` default |
| `metadata_source_file_id` | `source_file` of `indicator_metadata/<id>_*_metadata.xlsx` | FK | `NULL` for the 15 |
| `statistical_population` | workbook row `Statistical population` | verbatim | `NULL` if no workbook |
| `geographic_coverage` | workbook row `Geographic coverage` — **the key has a trailing NBSP (`\xa0`)**; match keys after stripping `\xa0`/spaces | verbatim | `NULL` |
| `calculation_method` | workbook row `Statistical calculation method` | verbatim | `NULL` |
| `data_sources_text` | workbook row `Data sources` | verbatim | `NULL` |
| `last_update_raw` | workbook row `Last data update` | **string, verbatim** (`20250101` ×65, `20240101` ×2, **`20400101` ×4** — the 4 projection indicators). A sentinel, not a date; never parsed. If the cell is numeric, `str(int)` is stored | `NULL` if no workbook |

Workbook layout (verified, all 71): one sheet `Meta data & Methodology`, header row `Title | Value`, then 15 rows keyed by column A. `Measurement unit` equals `unit_raw` in all 71 (loader assertion; mismatch ⇒ report, not silent correction).

**`measure_kind` — proposed mapping (UNREVIEWED; not applied until a reviewer marks it).** The 13 `unit_raw` values and their indicator counts (verified): `People` 51, `Number` 15, `Death per 1,000 live births` 7, `Percentage (%)` 3, `Birth per 1,000 population` 2, and one each of `Nurse/Dentist/Pharmacist/Physician per 1,000 population`, `People\ Square kilometer`, `Death per 1,000 population`, `Death per 1,000 Population in a specific age-group`, `Death per 1,000 total births`.

| `unit_raw` | Proposed `measure_kind` | Note |
|---|---|---|
| `People`, `Number` | `count` | only these two are candidates for `is_additive`; additive across **leaf members at one period only** (stocks such as population are never summed across years) |
| `Percentage (%)` | `percentage` | |
| `Death per 1,000 live births`, `Birth per 1,000 population`, `Death per 1,000 population`, `Death per 1,000 Population in a specific age-group`, `Death per 1,000 total births` | `rate` | |
| `Physician/Nurse/Dentist/Pharmacist per 1,000 population` | `ratio` | |
| `People\ Square kilometer` | `density` | |

The loader reads the mapping from a reviewed seed (a small versioned file the reviewer signs). **If a `unit_raw` is not in the reviewed seed, `measure_kind = 'unclassified'`** and the loader reports it. With no reviewed seed, all 86 are `unclassified`, `is_additive` is false everywhere and `v_derived_total_additive` is empty — safe, if unhelpful.

**`region_basis` — rules (the metadata cannot confirm it).** All 71 workbooks carry the *identical* generic `Geographic coverage` text ("…includes the three regions in the Emirate of Abu Dhabi…"), so it **cannot** distinguish residence from facility location. The design's "confirmed against the metadata" is therefore not achievable (discrepancy D-5). Mapping:

1. Title contains `Facility Region` (2592, 2622, 2681, 2703, 2731, 3998) → `facility_location`.
2. Title contains `Region of Residence` (4870) → `residence`.
3. **Everything else, including all other indicators that have a region dimension and all indicators without one → `unspecified`.**
4. A reviewer may promote others (candidates: births/population indicators whose workbook says "residing" → `residence`; capacity indicators 2801/2823/2845/2848/4052 → `facility_location`). **Candidates are not applied automatically** (**OU-11**).

**Keys.** PK `indicator_id`; `UNIQUE (slug)`. **Unique-key handling:** insert if absent; if present and every mapped column is equal → no-op; if any differs → **fail with a column diff** (an indicator definition changing is a vintage event needing a decision, not an overwrite).
**Validation.** *Loader:* 86 files ⇒ 86 rows; `indicatorId` = file prefix; unit/subtitle non-empty; `timeUnit` assertion; `projected` set equals the title rule's result and the observed set `{4866,4868,4869,4870}` is reported; workbook unit equality. *DB:* PK, UNIQUE, CHECKs (`measure_kind`, `series_kind`, `periodicity`, `region_basis`). *Application:* labelling of `projected` series and of the 20400101 sentinel.
**Provenance.** `metadata_source_file_id` → workbook; `observation.source_file_id` → the detail file (several vintages can coexist, D9).

---

## 6. `official.indicator_dimension`

**Source:** the dimension columns present in each indicator's rows.

| Column in rows (`*_EN`) | `dimension_type` | indicators using it (verified) |
|---|---|---|
| `REGION_EN` | `region` | 38 (29 alone + combinations) |
| `CITIZENSHIP_EN` | `citizenship` | 17 |
| `GENDER_EN` | `gender` | 13 |
| `AGE_GROUP_EN` | `age_group` | 5 (2584, 2650, 3276, 3535, 4868) |
| `CAUSE_DEATH_EN` | `cause_of_death` | 5 |
| `DISEASE_TYPE_EN` | `disease_type` | 3 |
| `INDICATOR_EN` | `measure_item` | 3 (2681, 2798, 2872) |
| `TYPE_EN` | `insurance_type` | 1 (2677) |
| `SECTORS_EN` | `sector` | 1 (2704) |
| `BED_TYPE_EN` | `bed_type` | 1 (2753) |

| Destination | Rule |
|---|---|
| `indicator_id` | FK |
| `dimension_type` | from the table above; **any other `*_EN` column ⇒ load error** (a new dimension is a design change) |
| `source_column` | the column name verbatim (`TYPE_EN`, `INDICATOR_EN` kept — their names mislead, hence the neutral `dimension_type`) |
| `ordinal` | 1-based order of the `*_EN` keys in the first data row. **Cross-check:** the number of `|`-separated segments of `$.Data.Properties` (e.g. `Cause death:Total|Gender:Total`) equals the number of dimension columns (verified for all 86) |

Shape (verified): 17 indicators no dimensions, 55 one, 10 two, 4 three = 86. A dimension is "present" iff the key exists in the rows, **even if some of its labels are null** (§7).
**Interpretation caution (OU-21).** `TYPE_EN` in 2677 holds `Thiqa`, `Enhanced`, `Daman Basic` — consistent with an insurance type; SCAD has not confirmed it (design §3.3 asks for confirmation before reuse). `INDICATOR_EN` in 2681/2798/2872 holds sub-items (`Physicians`, `Hospitals`, `Inpatient`, `Others`…) and null.
**Keys.** PK `(indicator_id, dimension_type)`; `UNIQUE (indicator_id, ordinal)`. Insert-if-absent; differing existing row fails.
**Validation.** *Loader:* every `*_member_id` column used by `observation` rows of an indicator corresponds to one of its `indicator_dimension` rows and vice-versa. *DB:* PK/UNIQUE/CHECK. (A CHECK cannot reference another table — design §3.3.)

---

## 7. `official.dimension_member`

**Source:** every distinct `(dimension_type, English label, Arabic label)` triple over all rows of all indicators. **Verified: 195 distinct triples** (176 distinct English labels incl. `null`; 19 English labels carry more than one Arabic label — below).

| Destination | Rule |
|---|---|
| `dimension_type` | §6 |
| `raw_label_en` | the `*_EN` value **verbatim**. A `null` label is stored as the literal `'(unlabelled)'` (**assertion:** no real label equals that string) |
| `raw_label_ar` | the `*_AR` value verbatim; `NULL` where the source is `null` (the Arabic is also `null` in every null-English case — verified) |
| `canonical_key` | `casefold(strip(raw_label_en))` with internal whitespace runs collapsed to one space; `(unlabelled)` stays `(unlabelled)`. **Does not** merge `Unknown` into `Missing/Unknown`, nor `behavioral` into `Behavioural` — those need the publisher (**OU-19**) |
| `member_role` | ordered rules below |
| `region_id` | set only when `dimension_type = 'region'` and the label is exactly a region's `scad_label` |
| `scheme_code`, `age_min_months`, `age_max_months` | age members only; below |
| `correction_state`, `label_corrected_en`, `correction_basis` | `none`/`NULL`/`NULL`, except corrupted age labels (below) |

**`member_role` — ordered rules** (first match wins; each is on `raw_label_en`):

| # | Rule | Role | Verified occurrences |
|---|---|---|---|
| 1 | label is `null` | `unlabelled` | 17 rows: 2681 ×8, 2798 ×4, 2872 ×2 (`INDICATOR_EN`), 2584 ×3 (**`AGE_GROUP_EN`**) |
| 2 | label = `Total` (any type) or (`region` and label = `Emirate of Abu Dhabi`) | `aggregate` | `Total` 4,154 cells over 8 types; `Emirate of Abu Dhabi` 1,772. **No other label starts with "Total"** |
| 3 | `Missing/Unknown`, `Unknown` | `missing_unknown` | 2,902 and 2 |
| 4 | `Not Stated`, `Not stated` (case-insensitive) | `not_stated` | 0 in the API; reserved for the workbook path (D9) |
| 5 | `casefold = abroad` | `abroad` | `Abroad` 688 + `abroad` 1 (3536, 2025, 101 deaths) |
| 6 | `casefold ∈ {other, others, other diseases}` | `other` | 69 / 8 / 37 |
| 7 | anything else | `leaf` | includes **`Not applicable`** (cause of death, 103 cells in 2583/2584/2585 — **OU-12**: proposed `leaf`, because it carries numbers; the leaf-reconciliation report will show if that is wrong) |

**Never dropped, never coerced.** Roles 3–6 carry real numbers and are *summed with leaves* (R-O7). Only `aggregate` is excluded from sums. SQL `NULL` in an observation member column means "dimension not applicable"; a source `null` label is `(unlabelled)`, never SQL `NULL`.

**Arabic variants — a verified source defect, preserved.** The unique key includes the Arabic label, so these become **separate members with the same `canonical_key`**:
- `Abroad` (REGION) pairs with `خارج الدولة` ("outside the country") in 10 indicators but with **`غير إماراتي` ("non-Emirati")** in 3549 — an Arabic label that contradicts the English one. Both are stored verbatim; nothing is merged or corrected (**OU-19**).
- 3535's age labels have **reversed/swapped Arabic** (`19-15`, `24-20`, …, `14-10`, `2026-09-05`, `2026-04-01`) while 2584/4868 keep `15-19`, `20-24`. So the corruption is **not "identical in Arabic" for 3535** (the quality report's wording holds for 4868 only) — detection therefore uses the **English** label only.
- `Brucellosis` and `Other Food Poisoning` have two Arabic spellings (2650 vs 2651).
- `cause_of_death` has near-duplicate English spellings across indicators (`Mental and behavioral disorders` / `Mental and Behavioural Disorders` / `Mental, behavioural or neurodevelopmental disorders`; `Congenital malformations…` / `Congenital Malformations…`). They are different raw labels, different members; only case-folding aligns the second pair.

**Region members.** `Abu Dhabi Region`, `Al Ain Region`, `Al Dhafra Region` → role `leaf`, `region_id` set. `Emirate of Abu Dhabi` → `aggregate`, `region_id NULL`. `Abroad`/`abroad`/`Missing/Unknown`/`Other` → their roles, `region_id NULL`. (`CHECK (region_id IS NULL OR dimension_type = 'region')`.)

**Age members** (`dimension_type = 'age_group'`, 50 distinct English labels, verified):
- `^(\d+)-(\d+)$` (not date-like): `age_min_months = lo·12`, `age_max_months = hi·12 + 11`. `^(\d+)\+$`: min = `n·12`, max `NULL` (open-ended). `Less than one year` → 0–11. `Total` and `Missing/Unknown` → bounds `NULL`.
- `scheme_code` (**proposed, informational, OU-12**): `5y` (width 5), `10y` (width 10), `15y` (the 0-14/15-29/30-44/45-59 set), `open` (`80+`/`60+`), `infant` (`Less than one year`), else `custom`. A scheme is really a property of an indicator's label set; the design puts it on the member, so the code describes only the member's own width. No clinical meaning (no mapping to IFHAS bands is made or permitted — quality report H4).
- **Corrupted labels (D4, provisional).** If `raw_label_en` matches `^\d{4}-(\d{2})-(\d{2})$` **on an `age_group` member**: `correction_state = 'pending'`; `age_min_months`, `age_max_months`, `scheme_code`, `label_corrected_en`, `correction_basis` all `NULL`. Verified: 3 English labels (`2026-05-09`, `2026-10-14`, `2026-01-04`) in **4 indicators — 2584, 3276, 3535, 4868** — 6 members (3 English × the Arabic variants above). The year (2026) is probably the extraction year; the loader must **not** hard-code the three strings. `applied` is reachable only by an explicit reviewed action after pattern match + contiguity with neighbours + a recorded SCAD confirmation in `correction_basis`. A date-like label on any **non-age** dimension fails the load. The candidate band (`05-09 → 5-9`, `01-04 → 1-4`) may be written to the report, never to a column. `2026-01-04 → 1-4` is an inference.

**Keys / uniqueness.** `UNIQUE NULLS NOT DISTINCT (dimension_type, raw_label_en, raw_label_ar)`. Idempotent load: `INSERT … ON CONFLICT DO NOTHING`, then **compare** the existing row's role/bounds/`region_id` with the computed ones; a difference fails (roles never change silently — the correction path is the only permitted change and is a reviewed action).
**Validation.** *Loader:* every aggregate label is in the known set; exactly one role per member; `abroad`/`Abroad` both present and both role `abroad`; no member with `region_id` outside `region` type. *DB:* UNIQUE, CHECKs (`member_role`, `region_id`, age bounds, `correction_state` ↔ `label_corrected_en`). *Manual/external:* `Not applicable`, `Unknown`, Arabic contradictions, correction basis.
**Provenance.** Members are shared across indicators and have no `source_file_id`; the raw labels are verbatim, and each observation's `source_file_id` identifies where a member was seen. The load report lists, per member, the indicators that use it.

---

## 8. `official.observation`

**Source:** each element of `$.Data.Data[]` in each indicator file. **Verified: 14,913 rows; all `VALUE` are JSON floats; 0 nulls; `YEAR` is a string equal to the first four characters of `OBS_DT` in every row; no sub-annual field is set.**

| Destination | Source | Conversion / rule | Null handling |
|---|---|---|---|
| `observation_id` | — | identity | — |
| `indicator_id` | file | FK | required |
| `source_file_id` | the detail file's `source_file` | FK; part of row identity (D9) | required |
| `period_year` | `YEAR` | `int()`; `CHECK BETWEEN 1900 AND 2100` | required |
| `period_type` | constant | `'year'` (valid because `timeUnit = Yearly` and 0 sub-annual rows) | — |
| `obs_date_raw` | `OBS_DT` | verbatim (`2025-01-01`); **assert** `OBS_DT[:4] == YEAR` | required |
| `<dim>_member_id` ×10 | `<COLUMN>_EN`/`_AR` pair | look up `dimension_member` by `(type, en, ar)`; the column is set **only** for dimensions in `indicator_dimension`; others stay SQL `NULL` | SQL `NULL` ⇔ dimension not applicable |
| `value` | `VALUE` | `NUMERIC`, parsed **from the JSON text** (`json.loads(parse_float=Decimal)`) — no binary-float round-trip (e.g. `6.0240963855`) | `NULL` only with a marker (below) |
| `value_marker_raw` | — | **always `NULL` for the API load** (the API has no marker field; 0 null values) | see below |
| `row_role` | derived | `leaf` iff **none** of the row's members has role `aggregate`, else `aggregate` (R-O2). A row aggregated on one dimension but not another is `aggregate` | required |
| `source_row_ordinal` | array index | **0-based** index in `$.Data.Data` (so the two 3422 duplicates are 104 and 657) | required |
| `quality_flag` | derived | `duplicate_key_conflict` per below; else `NULL` | `NULL` = clean |
| `loader_version` | constant | TEXT | required |

**Not loaded (and why):** `MONTH_EN/AR`, `QUARTER_EN/AR` (always `null`); `MAX_VALUE`, `MIN_VALUE`, `MAX_OBS_DT`, `MIN_OBS_DT` (repeated per-row series extrema; semantics undocumented, not asserted); **`Name`** (equals `YEAR` in most rows but **differs in 108 rows** — verified; undocumented, so not interpreted); `*_AR` columns other than as the member's `raw_label_ar`.

### 8.1 Missing markers vs dimension members (D3 — preserved, not interpreted)

- The SCAD **API** has **no** missing marker: 0 of 14,913 values are null. "Missing" appears only as **dimension members** (`Missing/Unknown`, 2,902 cells; `Unknown`, 2; `(unlabelled)`, 17) which carry real numbers and are rows like any other.
- `-` (births 2024), `:` (births 2025) exist only in the **workbooks**, which are not loaded in the MVP (D9, R-O8). `value_marker_raw` exists so a later workbook load needs no migration. The loader **rejects** any `null` `VALUE` from the API (it would violate `CHECK ((value IS NULL) = (value_marker_raw IS NOT NULL))` and the loader will not invent a marker) and never writes `0` for a missing cell.
- The meaning of `-`/`:` is **unassigned** (the in-file `Metadata` sheets do not define them). Numeric dimension members `Not Stated`, `Missing/Unknown`, `Abroad`, `Other` are *not* markers and are never coerced to null. A **missing cell** (combination absent from the cube) is *not published* — no row is written for it (R-O6); the loader never generates zero or marker rows to fill gaps.

### 8.2 Aggregate rows, leaf rows and non-additive indicators

- **Aggregates are loaded, flagged, never dropped** (5,001 of 14,913 rows are `aggregate`; 9,912 `leaf` — verified). Year-dependent shape is real: of 1,345 (indicator, year) cells, 890 contain an aggregate row and 455 do not.
- `measure_kind ≠ 'count'` (rate, percentage, ratio, density) ⇒ `is_additive = false`: no view sums them (R-O3).
- Counts are additive **across leaf members at one period**, never across periods.
- **Reconciliation is a classified report, not a hard failure.** The design says leaves sum to the aggregate ("the quality report states they do"). Verified on the 680 (indicator, year) cells of the single-dimension `People`/`Number` indicators: **486 reconcile, 141 have no aggregate, 11 are aggregate-only, and 42 do not reconcile** (7 indicators; discrepancy D-2). Rate/percentage and multi-dimension cubes were not tested:

| Indicator | Years not reconciling | Nature (observed) |
|---|---|---|
| 3465 births by region | 33 (1977–2009) | region leaves are present with value **0.0** while the emirate aggregate is non-zero (e.g. 1977: 0/0/0 vs 9,524). A source-stated zero, preserved as `0`; not interpreted |
| 4868 / 4869 / 4870 projections | 2024 (+10,940), 2030, 2035, 2040 | disclosure rounding (quality report A4) |
| 3463, 3466, 3502 | 2008–2009, 2009, 2022 | small differences (12, 24, 10, 1) — unexplained |

  Each (indicator, year, dimension) is classified `reconciles` / `no_aggregate` / `aggregate_only` / `mismatch`, written to the load report, and **never "fixed"**. `v_derived_total_additive` must exclude `mismatch` cells (**OU-16**, SCAD clarification).
- Multi-dimension cubes (2- and 3-dimension indicators) get the same classification per dimension with the other dimensions held fixed; none is asserted to reconcile.

### 8.3 Duplicate natural key — indicator 3422 (D5)

- Identity key: `(indicator_id, source_file_id, period_year, all ten member ids)`. Detection: group within the file; any group of size > 1 → **every** row of the group gets `quality_flag = 'duplicate_key_conflict'` (none is chosen, summed, averaged or dropped).
- **Verified:** exactly one group in all 86 files — 3422, 2025, `Non-Emirati / Male / Abu Dhabi Region` — rows 104 (`1.0`) and 657 (`1708.0`); same English and Arabic labels, same `OBS_DT`.
- The partial unique index `WHERE quality_flag IS NULL` excludes them. The default views exclude them; the report lists them for SCAD.
- **Unexpected duplicates fail the file's load** (they must not be flagged silently). Today's known set is `{(3422, 104), (3422, 657)}`; a re-fetch with a *different* duplicate set needs a decision before it is loaded.

### 8.4 Observed vs projected

`series_kind` lives on `indicator`. 4866/4868/4869/4870 are `projected` (years 2024, 2030, 2035, 2040, `last_update_raw = 20400101`). Their observations are ordinary rows; consumers must join `indicator.series_kind` and must not present a projection as an observation. 2024 appears in the projections *and* is therefore not an "observed 2024" figure for those indicators.

### 8.5 Keys, uniqueness, validation, provenance

- **Unique-key handling.** The partial unique index covers clean rows only, so **the duplicates themselves are not protected against re-insertion by it**. Idempotency is therefore **per source file, all-or-nothing** (strategy §6): if rows for `source_file_id` already exist, the loader compares row count and a content hash to the file and skips; it never inserts a subset. (A `UNIQUE (source_file_id, source_row_ordinal)` constraint would make this structural — recommended as an additive index, **not applied**, **OU-17**.)
- **Loader assertions:** member `dimension_type` matches its column (design §6.3 #1); the file's `source_file` is a detail file of this indicator; row counts equal `TotalItems`/file length (e.g. 2583 has 825 rows); every row maps to a member for each present dimension; no unknown dimension column.
- **DB constraints:** FKs, CHECKs (`period_year`, `period_type`, `row_role`, `quality_flag`, value/marker pairing), partial unique index.
- **Report-only:** leaf/aggregate reconciliation, year shape, `Not applicable` role effect.
- **Provenance:** `source_file_id`, `source_row_ordinal`, `loader_version`; `period_year` is the vintage.

---

## 9. `official.facility`

**Source:** `data/raw/abudhabi_sdi/<layer>.geojson` — **not** `data/processed/facilities/` (which keeps 26 of 43 attributes and only the repaired coordinates). One row per feature. **Verified: 9 layers, 5,339 `Point` features, 43 properties each; per-layer counts equal the manifest and the quality report** (clinics 1,250; diagnostic_centers 87; dialysis_centre 13; health_centres 1,290; hospitals 114; mobile_health_unit 49; pharmacy 1,715; provision_health_service 387; rehabilitation_center 434).

| Destination | Source | Conversion / rule | Null handling |
|---|---|---|---|
| `facility_id` | — | identity | — |
| `source_layer` | file stem | CHECK 9 values | required |
| `source_object_id` | `properties.OBJECTID` | `int`; unique **within** a layer only (1,715 distinct values overall — verified) | required |
| `license_no` | `FACILITYLICENSE` | verbatim | source `null` → SQL `NULL` (434, all `rehabilitation_center`). **Never `''`** (loader asserts no empty/whitespace string) |
| `identity_status` | derived | `unidentified` iff `FACILITYLICENSE` and `FACILITYNAME` are both `null`; else `identified`. **Assertion:** a feature with exactly one of the two null fails the load (none today) | required |
| `facility_name_en`, `facility_name_ar` | `FACILITYNAME`, `FACILITYNAMEAR` | **verbatim** — no trimming (e.g. `… DONOR UNIT  5` keeps its double space) | `NULL` for the 434 |
| `type`, `category`, `subtype` | `TYPE`, `CATEGORY`, `SUBTYPE` | verbatim | `NULL` for the 434 |
| `region_id` | `REGION` | lookup on `region.sdi_label`; **an unknown value fails the load** | `NULL` for the 434 |
| `city` | `CITY` | verbatim | `NULL` |
| `license_status_raw` | `LICENSESTATUS` | verbatim, FK → `license_status_map` | `NULL` for the 434 |
| `is_public_raw` | `ISPUBLIC` | verbatim (`Yes` 907, `No` 3,995, **`N` 3**) | `NULL` for the 434 |
| `is_public` | derived | `Yes→true`, `No→false`, `N→false` (design-approved normalisation; raw retained) | `NULL` |
| `has_insurance` | `HASINSURANCE` | `Yes→true`, `No→false`, **`''` (965) → `NULL`** | `NULL` |
| `inpatient_bed_capacity` | `INPATIENTBEDCAPACITY` | **a string in the source.** digits → `int`; **`''` (2,208) → `NULL`**; `null` → `NULL`; any other string fails the load. `CHECK ≥ 0`. Licensed capacity, not operational beds (R-O4) | `NULL` |
| `beds_raw`, `specialities_raw`, `professionals_raw` | `BEDS`, `SPECIALITIES`, `PROFESSIONALS` | verbatim composite strings; empty string → `NULL`. Not parsed (no MVP consumer; casting yields nothing) | `NULL` |
| `emergency_department`, `pediatric_emergency_department`, `maternity_emergency_care`, `home_care_services` | same-named properties | `Yes→true`, `No→false`; **any other non-null value fails** | `NULL` for the 434 |
| `source_longitude`, `source_latitude` | `geometry.coordinates[0]`, `[1]` | `DOUBLE PRECISION`, **exactly as published** (including the `(0,0)` placeholders and out-of-box values; float32 artefacts such as `54.66668701171875` are kept) | `NULL` only if the geometry is null (0 today) |
| `longitude`, `latitude`, `geo_quality` | derived | repair procedure below | usable pair `NULL` unless `geo_quality ∈ {ok, swapped_repaired}` |
| `source_file_id` | the layer file | FK | required |
| `source_effective_date` | — | **`NULL`** (register has no publication date; never the retrieval date, never the catalogue's "modified" date) | always `NULL` |
| `transform_version` | constant | identifier of the repair logic used | required |

### 9.1 Coordinates: original vs corrected (D6, D15)

Bounding box (generous, **not** an emirate boundary): lon 51.0–56.5, lat 22.0–25.5. Procedure — identical to `build_facilities.py` and verified to reproduce its counts (5,299 / 31 / 6 / 3):

1. geometry missing → `geo_quality` would be `null_geometry`, **which the 4-value CHECK does not allow**: **fail the load** (0 today; discrepancy D-6).
2. `(lon, lat) == (0, 0)` → `missing_placeholder`; usable pair `NULL`; `source_*` keep `0, 0`. (6 rows)
3. pair inside the box → `ok`; usable = source. (5,299)
4. pair outside the box but inside when swapped → `swapped_repaired`; `longitude = source_latitude`, `latitude = source_longitude`. (31)
5. otherwise → `out_of_bounds`; usable pair `NULL`; the bad values stay **only** in `source_*`. (3: `AL AIN ROYAL HOSPITAL` hospitals/90 at 37.76 E/26.75 N; `ABU DHABI MOBILE BLOOD DONOR UNIT  5` mobile_health_unit/38 at 42.19 E/18.10 N; `VIP DOCTOR L.L.C - BRANCH OF ABU DHABI` provision_health_service/334 at lon **34.45**, lat 24.45)
- **Do not "fix" lon 34.45** (a typo for 54.45 is speculation). The properties `Longitude`/`Latitude` carry the **same** defects (`(0,0)`, swapped, 34.453884), so they are no recovery source and are not loaded.
- `data/processed/facilities/*.csv` **retains out-of-bounds values in `longitude`/`latitude`** (the data dictionary says non-usable rows are null) — the DB must **not** be loaded from that CSV, and the loader's equivalence test compares only `ok`/`swapped_repaired` rows against it.
- **Prerequisite (separate task, not done here, D15):** the repair logic lives inside `build_facilities.py:main()` and is not importable. Until it is extracted, the loader re-implements it and an **equivalence test** against the committed CSV (counts per `geo_quality`, and coordinates for `ok`/`swapped_repaired`) gates the load.
- `ok` means "inside a generous box", not "inside the emirate".

### 9.2 Identity, identifiers, licence numbers, source layers

- `OBJECTID` is a layer-local counter: **`(source_layer, source_object_id)` is the key**. `license_no` is globally unique where present (4,905 distinct, 0 duplicates — verified). The **register is licence-level**: 23 groups / 48 licensed rows share name **and** coordinates with different licences (re-measured here; the design says 24 / 50 — the difference is in how the group is defined and does not affect loading) — **kept as separate rows, never de-duplicated**.
- **Unidentified records (434, all `rehabilitation_center`):** loaded with `identity_status = 'unidentified'`, every identity/classification/region/status field `NULL`, `source_object_id` and coordinates kept. They are never counted as facilities in any default view; there is no source field that identifies them, so none is invented.

### 9.3 Not loaded (23 of 43 properties)

`FACILITYEMAIL`, `FACILITYPHONE`, `FACILITYFAX`, `FACILITYPOBOX` (the licence grants no right to use personal information; some name individuals — **excluded permanently**); `THIQA`, `BASIC`, `ENHANCED` (`N/A` in all 4,905 populated rows); `Latitude`, `Longitude` (properties; same defects; they differ from geometry by up to ~2e-4° in the rows inspected); `CH_FID`, `TYPEOFLICENSE`, `PRELIMISSUEDATE`, `EXPIRYDATE` (`dd/mm/yyyy` strings; **no column in the approved design** — relevant to D13, candidate for a design review, not loaded), `CTSCAN`, `MRI`, `SONOGRAPHY`, `XRAY`, `HIGHEND`, `MIDRANGE`, `LOWEND`, `LEVELOFEMERGENCY`, `REMOTEEMERGENCYCARE`, `URGENTCARECENTERS`. Loaded: 20 properties + geometry.

### 9.4 Keys, uniqueness, validation, provenance

- **Keys.** PK `facility_id`; FKs `region_id`, `license_status_raw`, `source_file_id`.
- **Unique-key handling.** `UNIQUE (source_layer, source_object_id)` and `UNIQUE (license_no)` (NULLs distinct → the 434 do not collide). Re-run: `ON CONFLICT (source_layer, source_object_id)` with a **compare** step; a changed row fails. **Limitation (OU-17):** because those uniques are not vintage-aware, only **one** register vintage can exist; a re-fetched register is rejected pending a decision (D15/D9).
- **Loader assertions:** counts 5,339 and per layer = manifest; non-empty `license_no` unique; names/licences null together; region/status vocabularies; boolean vocabularies; bed parsing; `geo_quality` counts equal the equivalence test; `geo_quality` ∈ the 4 values.
- **DB constraints:** the CHECKs of design §3.4 (usable coordinates only when `ok`/`swapped_repaired`; bounding ranges; paired nullness; `identity_status`/identity nulls; `bed ≥ 0`; `license_no <> ''`).
- **Application:** `v_facility_usable` returns **no operating facility** until D13 confirms mappings — by design; every capacity display labelled "licensed", never "operational"; no facility ↔ SCAD join (R-O4).
- **Provenance:** `source_file_id` (retrieval stamp from the file's `_source.retrieved`), `transform_version`, verbatim raw columns.

---

## 10. `official.license_status_map`

**Source:** distinct non-null `LICENSESTATUS` values over all 5,339 features. **Verified: 14 distinct raw strings (not 15 — the design's "15" counted the `null` of the 434 unidentified rows, which is no map row; discrepancy D-3):**

| raw_value | rows | | raw_value | rows |
|---|---|---|---|---|
| `Active` | 3,005 | | `Pending Cancellation` | 48 |
| `Preliminary - Active` | 327 | | `Expired` | 50 |
| `About to Expire` | 287 | | `Temporary Closed` | 73 |
| `Preliminary - About to Expire` | 106 | | `Revoked` | 3 |
| `Preliminary - In Progress` | 85 | | `Cancelled` | 231 |
| `Preliminary - Cancelled` | 151 | | `Cancelled by Law` | 147 |
| `Preliminary - Cancelled by Law` | 368 | | **`Preliminary -Cancelled by Law`** (typo variant, no space) | 24 |

| Destination | Rule |
|---|---|
| `raw_value` (PK) | the string **verbatim** — the typo variant is a distinct row and is **not** merged with `Preliminary - Cancelled by Law` |
| `status_group` | `NULL` when loader-inserted. *Reviewer suggestion only (not applied):* group by the leading word — active / about_to_expire / cancelled / expired / preliminary / pending_cancellation / suspended-or-closed / revoked |
| `is_operating` | **`NULL`** until `review_state = 'confirmed'` |
| `review_state` | `unreviewed` for every loader-inserted row |
| `reviewed_by`, `reviewed_on`, `note` | `NULL` |

- **Raw vs normalised.** `facility.license_status_raw` is the raw string and FK; the *normalised* status is `license_status_map.status_group`/`is_operating`, which exist only after review (D13). The loader never infers `is_operating` — not even for `Active`.
- **Unseen values** found on a later load are inserted `unreviewed` (so the FK holds) and reported.
- **Idempotency.** `INSERT … ON CONFLICT (raw_value) DO NOTHING` — the loader **never updates** a reviewed row. Reviews are done by a separate, audited action outside the loader.
- **DB constraints** (design §3.4): unreviewed ⇒ `is_operating IS NULL`; `confirmed` ⇒ reviewer, date, flag present.
- **External:** DoH licensing clarification of the 14 meanings is advisable (**OU-7**).

---

## 11. Unresolved issues (official)

"Blocks" = what cannot proceed without a decision. *Interim* = behaviour in this mapping meanwhile.

| ID | Unresolved | Why it matters | Blocks | Who | Safe interim |
|---|---|---|---|---|---|
| **OU-1 / D3** | Meaning of `-` and `:` | coercing to 0 invents data; marker changed between editions | **Later** — workbook loading only (no API impact: 0 markers) | **SCAD** | Store raw marker, `value NULL`; assign no semantics; workbooks not loaded |
| **OU-2 / D4** | Age-label correction (`2026-05-09`, `2026-10-14`, `2026-01-04`) | wrong remap silently misassigns population; the year is an extraction artefact | **Later** — age-band use of 2584, 3276, 3535, 4868 | **SCAD** (owner approves the rule) | `pending`, bounds `NULL`, member unusable as a band; values retained |
| **OU-3 / D5** | Duplicate 3422 (1 vs 1,708) | cannot create a UNIQUE; one row is probably mislabelled | None (rows quarantined) | **SCAD** | both rows flagged, excluded from default views |
| **OU-4 / D6** | PostGIS vs plain coordinates — **recommendation only, awaiting owner confirmation; not approved** | column type only | **Implementation** (before first migration); not mapping | Project owner | mapping uses two `DOUBLE PRECISION` columns as the design describes |
| **OU-5 / D7** | Migration tool (Alembic recommended; **not approved**) | all DDL features this schema needs are hand-written | **Implementation** | Project owner | none needed for mapping |
| **OU-6 / D9** | Workbook loading and re-fetch | API/XLSX differ by 2 (births 2025) | Loader scope only | Project owner | API only; new vintage ⇒ new path ⇒ new `source_file` |
| **OU-7 / D13** | Licence-status meaning | operating status cannot be inferred; blocks `facility_service_profile` | **Later** — facility-profile creation and `v_facility_usable` | Owner + **DoH licensing** (advisable) | all 14 `unreviewed`; no operating facility |
| **OU-8 / D15** | Facility vintage & as-published coordinates | `processed/` has only repaired values; no register date | **Loading** until the repair function is importable/equivalence-tested | Project owner | read raw GeoJSON; reimplement + equivalence test; `source_effective_date NULL` |
| **OU-9 / D12** | `working_calendar` | conditional table | None for `official` | Owner + ADPHC | not created |
| **OU-10** | `unit_raw → measure_kind` mapping unreviewed | additive vs non-additive decides sums | **Later** — additive views | Data steward / owner | `unclassified`; nothing additive |
| **OU-11** | `region_basis` cannot be confirmed from metadata (generic text) | residence vs facility location changes interpretation | Later — region comparisons | Data steward; SCAD for confirmation | explicit-title rules only; else `unspecified` |
| **OU-12** | Roles of `Not applicable`, `Unknown`; `scheme_code` | wrong role could double-count or drop | Later — 2583–2585 sums | Data steward | `leaf` / `missing_unknown`; reconciliation report shows the effect |
| **OU-13** | `retrieved_at` unavailable for 157 SCAD files; SDI in-file date (14th) ≠ manifest (15th) | vintage ordering | Loading of a **second** vintage only | Owner | `NULL`; second vintage refused; discrepancy reported |
| **OU-14** | `scad_health_tables_en.xlsx` has **no manifest entry** | `source_id` NOT NULL | Registration of 1 of 215 files | Owner (assign a source / add manifest entry) | not registered; reported as `unmapped_file`; checksum still verified |
| **OU-15** | No manifest source for `attribution_statement`, `source.fit_for_use`, `source.contains_data` | licence conditions bind the UI | Later — attribution display | Owner / legal | `NULL`; attribution kept in `data/README.md`; file-level flags only |
| **OU-16** | 42 leaf≠aggregate cells (3465 zeros, projection rounding, 3 small gaps) | totals/shape from leaves would be wrong | Later — derived totals | **SCAD** | report-classified; `mismatch` excluded from derived totals |
| **OU-17** | Observation duplicates not protected by the partial index; facility uniques are single-vintage | idempotency, re-fetch | Loading design only | Owner (design review) | per-file all-or-nothing load; second register vintage refused |
| **OU-18** | 17 null-label rows (`INDICATOR_EN` ×14, `AGE_GROUP_EN` ×3) — what category do they denote? | could be a total or a blank category | Later | **SCAD** | `(unlabelled)`, summed as a non-aggregate, flagged |
| **OU-19** | `Unknown` vs `Missing/Unknown`; `Abroad`↔`غير إماراتي` in 3549; Arabic spelling/bidi variants; `behavioral`/`Behavioural` | merging would be a guess | Later | **SCAD** | verbatim members, same `canonical_key` only where case-folding aligns |
| **OU-20** | `abroad` (lower case, 3536, 2025) | label inconsistency | None | SCAD | role `abroad`, canonical key aligned |
| **OU-21** | `TYPE_EN` = insurance type (2677) | design asks for confirmation | Later | SCAD | `insurance_type` as designed |

**D2** (refusal representation) is provisional and requires clinical approval; it affects only `synthetic`, not this mapping.

---

## 12. Discrepancies between this mapping, the canonical design and the ERD

| # | Finding | Handling |
|---|---|---|
| D-1 | Design says "4868 is projected"; **four** indicators are projections (4866, 4868, 4869, 4870, all `last_update_raw = 20400101`) | Rule in §5 covers all four; design text to be corrected by the owner (not edited here) |
| D-2 | Design §3.3/§6.3 #2: leaves "sum to the aggregate"; **42 of the 528 tested cells that have both an aggregate and leaves do not** | Reconciliation is a classified report (§8.2); a hard assertion would reject valid data |
| D-3 | Design/ERD: "15 distinct" licence statuses; **14 non-null raw values** (the 15th is `NULL`) | §10 |
| D-4 | ERD `indicator` omits `statistical_population`, `geographic_coverage`, `calculation_method`, `data_sources_text` that §3.3 defines | Mapping follows §3.3 |
| D-5 | Design: `region_basis` "confirmed against the metadata Geographic coverage"; all 71 are the same generic text | §5: cannot be confirmed; explicit-title rules only |
| D-6 | `build_facilities.py` can emit a 5th `geo_quality` value `null_geometry`; the design CHECK allows 4 | None occurs; loader fails on it |
| D-7 | Quality report says age-label corruption is "identical in Arabic"; true for 4868 only — 3535's Arabic is reversed/different | Detect on English label (§7) |
| D-8 | Design (§0, B6): "retrieval date 2026-11-15"; SDI files say `2026-11-14T13:20–13:21Z`; SCAD API files carry no timestamp | §3 / OU-13 |
| D-9 | Design: facilities "24 co-located groups (50 rows)"; re-measured 23 / 48 | Informational |
| D-10 | D9 ("new vintage = new `source_file`") vs `UNIQUE(relative_path)` + immutable `raw/` | New vintage ⇒ new path (§3) |
| D-11 | Design says `INPATIENTBEDCAPACITY` "plain integer"; it is a **string** (`''` for 2,208 rows) | §9 conversion |
| D-12 | `scad_health_tables_en.xlsx` is in `raw_checksums.sha256` but has no manifest source | OU-14 |

No table was added, removed or re-keyed; none of these changes the approved architecture or the table inventory. Items D-1, D-3, D-4, D-5, D-10, D-11 are wording/derivation corrections for the owner; D-2 and OU-17 are the only ones that could justify an additive design change (a reconciliation-state note and a `UNIQUE (source_file_id, source_row_ordinal)`), and **neither is made** — review requested.
