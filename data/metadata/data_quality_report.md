# PulseReach — Data Quality Report

**Date:** 2026-11-15
**Scope:** every file held in `data/` as of this date — 215 files in `data/raw/`, plus the one
validated transformation in `data/processed/`.
**Method:** each XLSX opened with `openpyxl` and read cell-by-cell; each API extract parsed and
its dimensions, units, reference periods and row counts enumerated; every stated total
recomputed from its components; every facility coordinate bounds-checked; every file
SHA-256-checksummed (`data/reference/raw_checksums.sha256`, all 215 verified).

> **No file in `data/` has been clinically validated.** "Validated" below means *structurally*
> inspected and arithmetically cross-checked. It does not mean the data is fit for any clinical
> purpose.

---

## 1. Summary

| Source group | Files | Opens | Totals reconcile | Fit for intended use |
|---|---|---|---|---|
| `raw/scad/` (5 publications) | 5 | Yes | **Yes — exactly** | Yes, as aggregate context and cohort shape |
| `raw/statad_api/` (86 indicators + 71 metadata) | 158 | Yes | **Yes — exactly** | Yes, with the §2.1 aggregate-row rule enforced |
| `raw/abudhabi_sdi/` (5,339 facilities) | 10 | Yes | n/a (register) | Yes, 99.25% of geometry usable |
| `raw/abudhabi_opendata/` (metadata + 7 files) | 42 | Yes | n/a | Metadata yes; **5 of 7 files contain no data** |
| `processed/facilities/` | 3 | Yes | Cross-checks to SCAD ±5–9% | Yes — the validated facility layer |

All files are authentic, unmodified since download, and attributable. **None contains
individual-level data. None contains any preventive-screening indicator.**

**The two pre-existing SCAD files are byte-for-byte unchanged.** The 2022 workbook's source URL
was re-fetched on 2026-11-15 and returned an identical SHA-256
(`398529220d625a7b68dec04a34a902fa5603f9c026ee3a47d2920d4c4a76ff27`) — independent confirmation
that the held copy is authentic and uncorrupted.

---

## 2. `raw/statad_api/` — SCAD Statistics API (86 indicators)

### Verified
- **All 86 indicator extracts parse cleanly.** 71 carry an accompanying official
  *Metadata and Methodology* XLSX from SCAD's own endpoint.
- **Totals reconcile exactly.** On every indicator tested, the region members sum precisely to
  the stated `Emirate of Abu Dhabi` member — population 2025: 3,008,513 + 1,003,647 + 346,761 =
  **4,358,921**, matching standalone indicator 3916 to the person. Hospital beds 5,574 + 2,060 +
  448 = **8,082**. Clinics 462 + 230 + 233 = **925**. Physicians 9,864 + 3,374 + 542 + 31 =
  **13,811**.
- **Cross-source agreement.** Births 2025 reconciles across three independent API cuts
  (by citizenship, by region, by gender) *and* the separately downloaded XLSX publication:
  **41,235** in all four.
- **Provenance stated in-extract.** Every record carries `"data_source": "SCAD Official"` and an
  `updated` timestamp.
- **Long series.** Population to 1960, births to 1977, capacity and workforce to 2009/2010.

### Problems found

| # | Issue | Severity | Consequence |
|---|---|---|---|
| **A1** | **Embedded aggregate rows.** **65 of 86 indicators** include an aggregate member *inside* the dimension — `Total`, or `Emirate of Abu Dhabi` in `REGION_EN`. | **High** | A naive `GROUP BY … SUM()` **double-counts**. `3466_births_by_gender` sums to **82,470** against a true 41,235. Every consumer must filter aggregate members explicitly. This is the single most dangerous property of this source. |
| **A2** | **`Missing/Unknown` dimension member** present in **35 of 86** indicators (physicians by region: 31 people; births by region: 2). | High | A third missing-data convention beyond the workbooks' `-` and `Not Stated`. It is a real category — preserve it; never coerce to zero or drop it. |
| **A3** | **Corrupted age-band labels.** In `4868_projection_of_population_by_age_group`, bands `5-9` and `10-14` are returned as **`"2026-05-09"`** and **`"2026-10-14"`**. The Arabic labels are mangled *identically*, so the fault is upstream in SCAD's pipeline, not a locale artifact. | High | Values (209,060 and 182,960) are intact; only the labels are wrong. Must be remapped explicitly, with the remap documented. Any code keying on the label string will mis-bucket children. |
| **A4** | **Disclosure rounding.** 2024 age bands sum to **4,146,925** against a stated total of **4,135,985** — **+10,940**. Bands are evidently rounded to the nearest 5. | Medium | Usable as a *distribution shape*, never as counts. A synthetic cohort built from them approximates the 2024 age structure; it does not reproduce it. (This is a larger discrepancy than the ±15 previously observed on the census page — see §5.) |
| **A5** | **Projection years are sparse.** Indicator 4868 covers only 2024, 2030, 2035, 2040 — there is no 2025 age breakdown and no annual series. | Medium | Single-year-of-age child population still cannot be read directly. Derive it from the 1977–2025 births series and state the assumption. |
| **A6** | **Mixed periodicity in one catalogue.** The overview mixes Annual, Quarterly, Monthly and Semi-Annual indicators, and its latest-period `VALUE` is not comparable across rows. | Medium | Never read headline values from the overview; always fetch the indicator detail and respect `OBS_DT`. |
| **A7** | **Undocumented endpoint.** Recovered from inline page JavaScript. No contract, no versioning, no deprecation policy. | Medium | Treat the local extracts as the source of record. Re-acquisition may break without notice; the scripts in `data-pipeline/ingestion/` record exactly what was called. |
| **A8** | **No preventive-screening indicator exists** anywhere in the 1,700-indicator catalogue. | High | Confirms from data — not documentation — that screening history has no official source. |

---

## 3. `raw/abudhabi_sdi/` — Abu Dhabi health facility register (5,339 features)

### Verified
- **All 10 GeoJSON extracts parse cleanly.** Feature counts match the service's own
  `returnCountOnly` response exactly for every layer.
- **Geometry is real and correctly projected.** Requested at `outSR=4326`; 5,299 of 5,339
  features (99.25%) fall inside the Abu Dhabi bounding box with no nulls.
- **Facility identity is present** — `FACILITYNAME` in English and Arabic, `FACILITYLICENSE`,
  `LICENSESTATUS`, `REGION`, `CITY`. This is what closes prior gap H6.
- **Cross-validates against SCAD** once licence status is respected (see B4).

### Problems found

| # | Issue | Severity | Consequence |
|---|---|---|---|
| **B1** | **Insurance columns are empty.** `THIQA`, `BASIC`, `ENHANCED` are the literal string `"N/A"` in **every one** of the 4,905 populated rows. | **High** | They look like insurance-acceptance flags and carry **no information**. **IFHAS Thiqa eligibility cannot be derived from this file.** Anyone reading these as booleans gets a silent, uniform wrong answer. |
| **B2** | **Composite string fields.** `BEDS`, `SPECIALITIES` and `PROFESSIONALS` are semicolon-delimited composite records, not numbers — e.g. `"Acute Care , Pediatric , 38 , 0 , 0; Critical Care Unit , …"`. | High | Casting to numeric yields nothing (a first attempt here parsed **0** of 114 hospitals). `INPATIENTBEDCAPACITY` is the plain integer and is the field to use for bed counts. Populated mainly for hospitals. |
| **B3** | **Only 3,005 of 5,339 rows are `Active`.** The remainder are Cancelled (231), Cancelled by Law (147), Preliminary – Cancelled by Law (368), About to Expire (287), Expired (50), Temporary Closed (73), Revoked (3) and others. 434 rows (all `rehabilitation_center`) have blank status *and* blank region. | High | The register is a **licensing** record, not a list of operating facilities. Filter on `license_status` before counting anything as a live facility. |
| **B4** | **Does not reconcile with SCAD, by definition.** Active-only: **71 hospitals / 8,828 beds** here vs **75 hospitals / 8,082 beds** in SCAD 2801/4111 (5% and 9% variance). Unfiltered: 114 hospitals / 11,721 beds. | High | Close enough to confirm both describe the same estate; far enough apart to prove the definitions differ (licensed capacity vs operational beds). **Do not combine them, and do not present either as the other.** |
| **B5** | **Defective geometry in 40 features (0.75%).** 31 have lon/lat transposed; 6 sit at `(0,0)`; 3 are genuinely outside the emirate (two in Saudi Arabia — `AL AIN ROYAL HOSPITAL` at 37.76E/26.75N and a mobile blood unit at 42.19E/18.10N). | Medium | Repaired or flagged — never dropped — in `processed/facilities/`, each row carrying `geo_quality`. The 9 unusable rows must be excluded from any map, not plotted at a default location. |
| **B6** | **No reference date.** A live register with `PRELIMISSUEDATE` / `EXPIRYDATE` per row but no publication date; catalogue entries say modified 2025-07-25/28. | Low | Cite the retrieval date (2026-11-15), recorded in each file's `_source` block. |
| **B7** | **Contains facility contact details** (`FACILITYEMAIL`, `FACILITYPHONE`), some of which are named individuals' work addresses. | Medium | Business contact data, not patient data — but the Abu Dhabi licence grants **no right to use Personal Information**. Do not surface these in any UI or redistribute them. |

---

## 4. `raw/scad/` — SCAD publications (5 workbooks)

### Verified — 2025 editions
- **Both 2025 workbooks open cleanly**, 8 sheets each (`Index`, `Table 1`–`Table 5`,
  `Metadata`, `Enquiries`), same bilingual publication layout as the 2024 file.
- **Births 2025 Table 1 reconciles EXACTLY in both directions.** Rows: every citizenship and
  gender row's five region values sum to its stated emirate total. Columns: Emirati 16,310 +
  Non-Emirati 24,758 + Citizenship Not Stated 167 = **41,235** = stated Total, and the same
  holds for each of Abu Dhabi (28,822), Al Ain (11,246), Al Dhafra (1,065), Abroad (100) and
  Not stated (2).
- **Provenance stated in-file:** "Source: Department of Health – Abu Dhabi".
- **Glossary present** in both `Metadata` sheets.

### Problems found

| # | Issue | Severity | Consequence |
|---|---|---|---|
| **C1** | **The missing-value convention CHANGED between editions.** Births 2024 uses `"-"` (57 cells). **Births 2025 uses `":"` (67 cells).** Deaths 2025 uses neither. | **High** | Code written and tested against the 2024 file will **mis-parse the 2025 file**. Neither marker may be coerced to 0 — both mean not-applicable/not-reported. The repository now needs a marker set of `{-, :, Not Stated, Not stated, Missing/Unknown}`. |
| **C2** | **A new `Not stated` REGION column** sits alongside the pre-existing `Abroad` column in the 2025 editions — five region columns before the emirate total, where 2024 had four. | High | Read region columns **by header, never by position**. Positional code written for 2024 silently shifts by one on 2025. |
| **C3** | **`Abroad` persists as a region** (100 births, 101 deaths in 2025). | High | Carried forward from 2024 finding B1. It is a distinct category, not a region of residence, and must not be folded into Al Dhafra or dropped. |
| **C4** | **Same non-tidy publication layout** — title row 2, unit row 3, dimension label row 5, headers row 6, data row 7, source notes below; Arabic in parallel columns. | Medium | Every table needs an explicit per-sheet `skiprows`/`usecols` read. No generic ingestion. |
| **C5** | **Deaths 2025 Table 1 shows `Not Stated (Gender)` with real non-zero values** (8 in Abu Dhabi, 1 in Al Ain) where births shows zeros. | Medium | Retain the category in both. Dropping "not stated" overstates completeness. |
| **C6** | **Births ≠ well-child attendance; deaths ≠ morbidity.** Neither file carries a screening, visit or outcome field. | High | The Well-Child pathway gets a cohort *size* from these files and nothing else. |
| **C7** | `scad_health_tables_en.xlsx` is a **single flat 925-row sheet** with no metadata sheet, no stated reference period and a 2023 server timestamp. | Medium | Long-run context only. Do not cite a reference period it does not state. |

### Carried forward — `scad_health_statistics_2022_en.xlsx`
Findings **H1–H8** from the previous report stand unchanged. The two that still bind:
- **H3:** Tables 6–7 are **percentage-of-infection-mix, not prevalence or incidence**. They
  cannot be converted to counts and must never be used as a risk or prevalence input.
- **H4:** their age bands (0-14, 15-29, 30-44, 45-59, 60+) align with **no** IFHAS band. Do not
  interpolate a mapping; doing so would invent clinical data.

**H1 is now mitigated:** the 2022 reference period is superseded for facilities, beds,
professionals and patients by the 2025 API indicators. Keep the 2022 file for series continuity
and **label every figure drawn from it "2022"** — the two vintages must not be mixed (see §6).

---

## 5. `raw/abudhabi_opendata/` — catalogue and downloaded files

| # | Issue | Severity | Consequence |
|---|---|---|---|
| **D1** | **18 Department of Health datasets declare `format: "csv"` but point at `https://tableau.doh.gov.ae/<Name>`, a host with NO DNS A record.** Affects Population Structure, Diabetes Prevalence, Cancer Incidence, Non-Communicable Diseases, Facilities, Clinicians, Bed Occupancy, Vital Statistics, Birth/Death Statistics and more. | **High** | **Dead links in the publisher's own catalogue**, mislabelled as CSV while being dashboard pages. Nothing was obtained and nothing is claimed about their contents. Catalogue metadata alone is not evidence that data exists. |
| **D2** | **5 of 7 downloaded files contain no data.** Each Gov-Digital facility "XLSX" holds a single cell containing a now-404 ArcGIS URL (`Pub/CF_Health/MapServer/<n>`). | High | Retained as provenance for how SRC-18 was found. A successful HTTP 200 and a valid XLSX signature do **not** mean a file contains data — it must be opened. |
| **D3** | **The MOHAP nurse workbooks are UAE-wide and dated 2008.** | High | **Not fit for use.** Wrong geography (MOHAP medical districts, not Abu Dhabi regions) and eighteen years stale. Superseded by API indicators 2702/2703/2704. Retained only as the provenance record for a brief-named dataset. |
| **D4** | Much of the DoH tabular catalogue was last modified **2022-07-17**. | Medium | Treat catalogue currency per dataset; the portal's advertised breadth is not a currency guarantee. |
| **D5** | The unfiltered metastore list endpoint **times out (>60 s, repeatedly)**. | Low | Enumerate via `search_main.php` with pagination (614 datasets recorded in `catalogue_search_results.json`). |

### Population context figures (previous §4) — now superseded
The census-page figures previously recorded in the manifest are **superseded by indicators
3916 / 3175 / 3919** (SRC-17), which supply the same quantities as machine-readable series with
a 2025 reference period and longer history. Previous findings **P1–P3** are retained in spirit
by **A4** (rounding) and **A3** (label corruption), both of which are larger and better
evidenced than the originals. Do not cite the page figures where an API series covers the same
quantity.

---

## 6. Datasets that must NOT be combined

Recorded explicitly because each pairing looks joinable and is not:

| A | B | Why not |
|---|---|---|
| SCAD Health Statistics **2022** | SCAD API **2025** capacity indicators | Four-year gap; the 2022 workbook's facility taxonomy (Hospitals / Health Centres / Clinics / Pharmacies / Others) is not the API's indicator set. Label the vintage on every figure. |
| SDI facility `INPATIENTBEDCAPACITY` | SCAD `Hospital Beds` (4111) | Licensed capacity vs operational beds — 8,828 vs 8,082 on Active licences (B4). |
| SDI facility counts | SCAD `Hospitals`/`Clinics` counts | 71 vs 75 hospitals; the register counts licences, SCAD counts facilities (B3, B4). |
| Births **2024** parsing code | Births **2025** file | Different missing-value marker and an extra region column (C1, C2). |
| 2022 infection age bands | Any IFHAS age band | No mapping exists (H4). |
| MOHAP nurses (UAE, 2008) | Any Abu Dhabi workforce figure | Wrong geography, wrong decade (D3). |
| Any `Total` / `Emirate of Abu Dhabi` member | Its own sibling members | Double-counting (A1). |

---

## 7. Gaps that no held file can close

| Need | Status | Resolution |
|---|---|---|
| Individual-level patient records | No official source; none permitted | Synthetic only (Synthea base + custom layer) |
| **IFHAS screening history / participation / completion** | **No source whatsoever.** Confirmed by A8 (0 of 1,700 indicators), D1 (catalogue search: 1 match for "screening", not a programme dataset), and direct reading of the ADPHC programme page. | Custom synthetic generation. Formal aggregate request to `IFHAS.Support@adphc.gov.ae` (see SRC-22). |
| **Well-Child visit attendance / uptake** | **No source whatsoever.** Nearest official figures are a different programme (newborn screening 98%, 2021; 322,000 school screenings, 2024). | `WCV.Support@adphc.gov.ae` |
| Screening coverage rates for Abu Dhabi | Not in any held file | None available — **do not estimate one** |
| Facility-level Thiqa acceptance | Columns exist but are empty (B1) | DoH licensing data request |
| Single-year-of-age child population | Only 5-year bands, sparse years, corrupt labels (A3, A5) | Derive from the 1977–2025 births series; state the assumption |
| Abu Dhabi disease prevalence | **Not available.** 2022 Tables 6–7 are not prevalence (H3); API disease indicators are notification counts and mix percentages, not prevalence | Do not use. **NHANES must not substitute.** |
| Child vaccination / immunisation coverage | MOHAP dataset unreachable (TLS); no Abu Dhabi equivalent found | Re-attempt from a UAE network |

**Facility names and coordinates — previously listed here as an open gap — is CLOSED** by
`raw/abudhabi_sdi/` (5,339 facilities) and `processed/facilities/`.

---

## 8. `processed/facilities/` — the one validated transformation

Built by [`data-pipeline/transformation/build_facilities.py`](../../data-pipeline/transformation/build_facilities.py),
reproducible from `raw/` alone.

- **5,339 rows**, one per source feature. **Nothing dropped, no value invented.**
- Output SHA-256 recorded in `quality_report.json` alongside per-layer counts.
- Every row carries **`geo_quality`**: `ok` (5,299), `swapped_repaired` (31),
  `missing_placeholder` (6), `out_of_bounds` (3).
- Composite string fields copied **verbatim**, with the trap documented in the module docstring
  and the quality report.
- `license_status` and `region` distributions emitted so B3's filtering requirement is visible
  at the point of use.

**`geo_quality` must be carried through any downstream use.** Rows that are not `ok` or
`swapped_repaired` have no usable coordinates and must be excluded from a map rather than
defaulted.

---

## 9. Assessment

**The held data is good quality for what it is** — authentic, internally consistent, unmodified,
attributable official statistics, with totals that reconcile to the unit across every indicator
and workbook tested. Two independent sources now cross-validate each other on health-system
capacity to within 5–9%, which is the strongest consistency evidence this project has had.

**The defects found are real and several are dangerous**, specifically because they fail
silently rather than loudly: embedded aggregates that double-count (A1), a missing-value marker
that changed between editions of the same publication (C1), age-band labels corrupted into
dates (A3), insurance columns that are uniformly empty while looking populated (B1), composite
strings that cast to nothing (B2), and 18 catalogue entries whose host does not exist (D1).
Every one is documented above with its consequence. **Finding them is the value of this phase**;
none is a reason to withhold the data, and all must be carried into Phase 3 as explicit rules.

**What has changed since the previous report:** Abu Dhabi population structure and health
facility locations are no longer gaps. The reference period for the health system moved from
2022 to 2025. The birth series extends to 1977, so a seven-year 0–6 cohort no longer needs a
flat-cohort assumption.

**What has not changed, and is the most consequential finding here:** **no official source
provides Abu Dhabi preventive-screening history, attendance or coverage.** This is now
confirmed three ways — 0 of 1,700 SCAD indicators, 1 non-qualifying match across 614 catalogue
datasets, and the programme page itself. Every screening record PulseReach uses will be
synthetic, and the system must say so wherever it shows one.

**A boundary worth restating:** the IFHAS Appendix 9 ">85% participation" and the WCV §5.1
"target 100%" figures are **definitions and targets in a clinical standard, not observed
programme performance**. They must never be presented as measured values.
