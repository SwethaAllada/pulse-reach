# PulseReach — Data Dictionary

Field-level description of datasets held in `data/`. One section per file actually on disk, plus a
section for the planned synthetic tables.

**Status as of 2026-11-15:** 215 files held in `raw/` across four publishers, all aggregate or
facility-level official statistics — no individual-level data. `processed/` holds one validated
transformation (the facility table, §6). `synthetic/` is still **empty**, so §8 is a
**specification of intent**, clearly marked as such, not a description of existing data.

> Each dataset's provenance, licence and acquisition status is in
> [`../reference/source_manifest.yaml`](../reference/source_manifest.yaml). This file describes
> *fields*.

---

## 1. `raw/scad/scad_health_statistics_2022_en.xlsx`

**Source:** Statistics Centre – Abu Dhabi, *Health Statistics 2022*. Reference period: calendar
year 2022. Data originator stated inside the file: "Health Department - Abu Dhabi".
**Shape:** 11 sheets — `Index`, `Table 1`–`Table 8`, `Metadata`, `Enquiries`.
**Structure:** this is a **publication workbook, not a tidy dataset**. Every sheet is a formatted
bilingual (English/Arabic) table: the title sits in row 2, the unit of measure in row 3, the row-
dimension label in row 5, column headers in row 6 or 7, data from row 7 or 8, and a source note
below the data. Arabic labels sit in parallel columns to the right. There is no header row that a
dataframe reader will find unaided — each table needs an explicit skiprows/usecols read.

| Sheet | Table | Row dimension | Column dimension | Unit |
|---|---|---|---|---|
| `Table 1` | Key health statistics | Indicator (facilities, beds, professionals, blood units) | 2022 | Count |
| `Table 2` | Health facilities by region | Facility type: Total, Hospitals, Health Centres, Clinics, Pharmacies, Others | Abu Dhabi Region, Al Ain Region, Al Dhafra Region, Total | Count |
| `Table 3` | Beds and admitted patients by region | Beds; Patients (Inpatients) | Same three regions + Total | Count |
| `Table 4` | Health professionals by region | Total, Doctors, Nurses, Dentists, Pharmacists, Others | Same three regions + Total | Count |
| `Table 5` | Patients by region and sector | Government / Private, each split Inpatient / Outpatient | Same three regions + Total | Count |
| `Table 6` | Infections by disease and citizenship | ~30 notifiable disease types | Citizen, Non-citizen, Citizenship Not Stated, Total | **Percent** |
| `Table 7` | Infections by disease and age group | ~30 notifiable disease types | 0-14, 15-29, 30-44, 45-59, 60+, Total | **Percent** |
| `Table 8` | Blood units donated | Blood group (A+, A−, AB+, AB−, B+, B−, O+, O−) | Total | Count |

**Fields used by PulseReach** (nothing else in this workbook is consumed):

| Field | Sheet | Type | Example | Use |
|---|---|---|---|---|
| Facility type × region count | `Table 2` | Integer | Hospitals, Abu Dhabi Region = 42 | Proportional shape for the synthetic facility layer |
| Health professionals × region | `Table 4` | Integer | Doctors, Al Ain = 3,003 | Capacity context in the narrative |
| Facility total | `Table 2` | Integer | 3,323 | Denominator for narrative framing |

**Cautions**
- Tables 6 and 7 are **percentages of infections**, i.e. the disease mix *within* each group — not
  incidence, not prevalence, not a rate per population. They cannot be converted to case counts and
  must never be used as a risk input. The 0-14 / 15-29 / 30-44 / 45-59 / 60+ bands do **not** align
  with any IFHAS screening age band and must not be mapped onto one.
- Column totals in Tables 6–7 are floating-point and print as `100.00000000000001`.
- All counts are emirate-level aggregates for 2022. Not individual records, not current.
- No facility names, addresses or coordinates exist in this file.

---

## 2. `raw/scad/scad_birth_statistics_2024_en.xlsx`

**Source:** Statistics Centre – Abu Dhabi, *Birth Statistics 2024*. Reference period: calendar year
2024. Data originator stated inside the file: "Department of Health – Abu Dhabi".
**Shape:** 8 sheets — `Index`, `Table 1`–`Table 5`, `Metadata`, `Enquiries`. Same bilingual
publication layout as above.

| Sheet | Table | Row dimension | Column dimension | Unit |
|---|---|---|---|---|
| `Table 1` | Births by citizenship, gender and region | Emirati / Non-Emirati / Citizenship Not Stated, each × Male / Female / Not Stated | Abu Dhabi Region, Al Ain Region, Al Dhafra Region, **Abroad**, Emirate of Abu Dhabi | Count |
| `Table 2` | Births by month, citizenship and gender | Citizenship × Gender | 12 months + Total | Count |
| `Table 3` | Distribution of births by month | Citizenship × Gender | 12 months | Percent |
| `Table 4` | Sex ratio at birth | Citizenship | Regions + Total | Male births per 100 female |
| `Table 5` | Average age of mother at first birth | Citizenship | Regions + Total | Years |

**Fields used by PulseReach:**

| Field | Sheet | Type | Example | Use |
|---|---|---|---|---|
| Births × citizenship × gender × region | `Table 1` | Integer | Emirati Male, Al Ain = 2,961 | Size and shape of the synthetic 0–6 Well-Child cohort |
| Emirate total births | `Table 1` | Integer | 39,333 | Annual birth cohort denominator |
| Sex ratio at birth | `Table 4` | Float | 109.8 overall | Plausibility check on synthetic sex balance |

**Cautions**
- The region axis has a fourth member, **Abroad** (110 births in 2024) — births to Abu Dhabi
  residents outside the emirate. A naive read that assumes three regions will silently mis-total.
  `Al Dhafra` and `Abroad` are distinct; do not merge them.
- Missing data is encoded two ways: the literal string `"-"` in cells, and explicit
  `Not Stated (Gender)` / `Citizenship Not Stated` categories. **Preserve both.** Do not coerce
  `"-"` to zero — it means "not applicable / not reported", and `Non-Emirati × Abroad` is `"-"`
  while `Emirati × Abroad` is 110.
- Births are not well-child visit attendance. This file says nothing about screening uptake,
  attendance or outcomes.

---

## 3. `raw/scad/scad_birth_statistics_2025_en.xlsx` and `..._death_statistics_2025_en.xlsx`

**Source:** Statistics Centre – Abu Dhabi, *Birth Statistics 2025* / *Death Statistics 2025*
(`SRC-19-SCAD-VITAL-2025`). Reference period: calendar year 2025. Originator stated in-file:
"Department of Health – Abu Dhabi".
**Shape:** 8 sheets each — `Index`, `Table 1`–`Table 5`, `Metadata`, `Enquiries`. Same non-tidy
bilingual publication layout as the 2024 file: title row 2, unit row 3, dimension label row 5,
column headers row 6, data from row 7, source notes below.

### Births 2025 — `Table 1` (the table PulseReach uses)

| Field | Type | Values | Notes |
|---|---|---|---|
| Citizenship and Gender (row dimension) | string | `Total`, `Emirati`, `Non-Emirati`, `Citizenship Not Stated*`, each with `Male` / `Female` / `Not Stated (Gender)*` sub-rows | Asterisk is the publisher's footnote marker |
| `Abu Dhabi Region` | integer | 28,822 | |
| `Al Ain Region` | integer | 11,246 | |
| `Al Dhafra Region` | integer | 1,065 | |
| `Abroad` | integer | 100 | **A category, not a region of residence** |
| `Not stated` | integer | 2 | **New column in the 2025 edition** |
| `Emirate of Abu Dhabi` | integer | **41,235** | Stated total; reconciles exactly both ways |

**Cautions — read before writing any parser**
- **Missing-value marker is `":"` in births 2025, not `"-"` as in births 2024.** 67 cells.
  Deaths 2025 uses neither. Never coerce either marker to 0 — both mean not applicable or not
  reported. Repository marker set: `{-, :, Not Stated, Not stated, Missing/Unknown}`.
- **Read region columns by header, never by position.** The 2025 edition has five region columns
  before the emirate total where 2024 had four; positional code silently shifts by one.
- Deaths 2025 `Not Stated (Gender)` carries real non-zero values (8 Abu Dhabi, 1 Al Ain).
- Births ≠ well-child attendance; deaths ≠ morbidity. Neither file has a screening or visit field.

`scad_health_tables_en.xlsx` is a single flat 925-row English sheet with no metadata sheet. Its
30 stacked tables state their periods in their titles (first: "Table 1: Key Health Statistics,
Abu Dhabi, 2012"; others span 2008–2012, 1973–2012, 2005–2012) and its embedded document title is
"Health Statistic 2012". It records no server timestamp, URL or manifest entry. Long-run context only.

---

## 4. `raw/statad_api/` — SCAD Statistics API indicator extracts

**Source:** `SRC-17-SCAD-STATISTICS-API`. 86 indicators as JSON + 71 official
*Metadata and Methodology* XLSX workbooks. Endpoints and parameters are in the manifest;
the fetch script is `data-pipeline/ingestion/fetch_statad_indicators.py`.

**File shape.** Each `indicator_detail/<id>_<slug>.json` is the raw API envelope:

```
Data.Metadata        component_title, component_subtitle (the official definition),
                     data_source ("SCAD Official"), updated
Data.Configuration[0] unit, yAxisLabel, note, isMultiDimension, dbColumn
Data.Data[]          the observation rows
```

**Observation row fields**

| Field | Type | Meaning |
|---|---|---|
| `VALUE` | number | The observation. Unit is in `Configuration[0].unit`, never assumed. |
| `YEAR` | integer | Reference year |
| `OBS_DT` | date | Observation date |
| `MONTH_EN` / `QUARTER_EN` | string | Populated only for sub-annual indicators |
| `<DIM>_EN` / `<DIM>_AR` | string | Dimension members, bilingual. One pair per dimension. |
| `MAX_VALUE`, `MIN_VALUE`, `MAX_OBS_DT`, `MIN_OBS_DT` | — | Series extrema; **not** observations |

**Dimension columns actually present:** `REGION_EN`, `CITIZENSHIP_EN`, `GENDER_EN`,
`AGE_GROUP_EN`, `CAUSE_DEATH_EN`, `DISEASE_TYPE_EN`, `BED_TYPE_EN`, `SECTORS_EN`,
`INDICATOR_EN`, `TYPE_EN`.

**Region members:** `Abu Dhabi Region`, `Al Ain Region`, `Al Dhafra Region`, plus the aggregate
`Emirate of Abu Dhabi`, plus `Abroad` and `Missing/Unknown` in vital statistics.

**Cautions — all three are load-bearing**
1. **`Total` / `Emirate of Abu Dhabi` are members of the dimension, not separate fields.**
   65 of 86 indicators embed one. **Filter aggregate members before any `SUM`** —
   `3466_births_by_gender` otherwise sums to 82,470 against a true 41,235.
2. **`Missing/Unknown` is a real member** in 35 of 86 indicators. Preserve it.
3. **Indicator 4868 returns the age bands `5-9` and `10-14` as the strings `"2026-05-09"` and
   `"2026-10-14"`** (English and Arabic alike). Values are intact; remap the labels explicitly.

**Fields used by PulseReach**

| Purpose | Indicator(s) | Field |
|---|---|---|
| Population by region/gender, 2025 | 3916, 3175, 3919 | `VALUE` × `REGION_EN` / `GENDER_EN` |
| Age structure (shape only) | 4868 | `VALUE` × `AGE_GROUP_EN` — see caution 3 and rounding (+10,940) |
| Birth cohorts 1977–2025 | 3463, 3465, 3466, 3549 | `VALUE` × year × region × citizenship |
| Facility and bed capacity by region | 2800/2801, 4111/4052, 2825/2845, 2822/2823 | `VALUE` × `REGION_EN` |
| Workforce by region | 2701/3998, 2702/2703, 2729/2731 | `VALUE` × `REGION_EN` |
| Child mortality context | 3319, 3280, 3813, 3498 | `VALUE` × `REGION_EN` |

---

## 5. `raw/abudhabi_sdi/*.geojson` — health facility register

**Source:** `SRC-18-ABUDHABI-SDI-FACILITIES`. Nine GeoJSON FeatureCollections, 5,339 point
features, WGS84 (`EPSG:4326`). Each file carries a `_source` block recording the service URL,
layer id, retrieval timestamp and the exact query.

**Geometry:** `Point`, `[longitude, latitude]`.

**Properties — the 26 fields carried into `processed/`** (43 exist in source)

| Field | Type | Meaning / caution |
|---|---|---|
| `OBJECTID` | integer | Layer-local identifier. **Not unique across layers** — key on `(source_layer, facility_id)`. |
| `FACILITYNAME` / `FACILITYNAMEAR` | string | Facility name, EN / AR |
| `FACILITYLICENSE` | string | DoH licence number, e.g. `MF4887` |
| `LICENSESTATUS` | string | **Only 3,005 of 5,339 are `Active`.** Filter before treating a row as operating. |
| `TYPE`, `CATEGORY`, `SUBTYPE` | string | Facility classification |
| `REGION` | string | `Abu Dhabi` (3,178) / `Al Ain` (1,236) / `Al Dhafra` (491); blank for 434 rows |
| `CITY` | string | City or area |
| `ISPUBLIC` | Yes/No | Public vs private |
| `INPATIENTBEDCAPACITY` | **string** (digits) | **The bed-count field.** A *string* in the source, not an integer: digit string `"0"` (2,586 features) is a source-stated zero, digit string `> 0` (111, all hospitals) is a count, empty string `""` (2,208) means not recorded and is **not** zero, and `null` (434) is an unidentified record. Positive for 111 of 114 hospitals (the other 3 are `"0"`). Licensed capacity, not operational beds. |
| `BEDS` | **composite string** | Semicolon-delimited records: `"Acute Care , Pediatric , 38 , 0 , 0; …"`. **Not numeric — casting yields nothing.** |
| `SPECIALITIES` | **composite string** | `"Surgery - Thoracic Surgery; Dental - Prosthodontics; …"` |
| `PROFESSIONALS` | **composite string** | `"Allied Health Care - 68; Consultant Physician - 27; …"` |
| `EMERGENCYDEPARTMENT`, `PEDIATRICEMERGENCYDEPARTMENT`, `MATERNITYEMERGENCYCARE`, `HOMECARESERVICES` | Yes/No | Capability flags |
| `THIQA`, `BASIC`, `ENHANCED` | string | **`"N/A"` in every row — carries NO information.** IFHAS Thiqa eligibility **cannot** be derived from this file. |
| `FACILITYEMAIL`, `FACILITYPHONE`, `FACILITYFAX`, `FACILITYPOBOX` | string | Business contact details, some naming individuals. **Not carried into `processed/`; do not surface or redistribute** — the licence grants no right to use Personal Information. |

---

## 6. `processed/facilities/abu_dhabi_health_facilities.csv`

Built by [`../../data-pipeline/transformation/build_facilities.py`](../../data-pipeline/transformation/build_facilities.py)
from `raw/abudhabi_sdi/` alone. **5,339 rows — nothing dropped, no value invented.**

| Column | Type | Meaning |
|---|---|---|
| `facility_id` | integer | Source `OBJECTID`; unique only within `source_layer` |
| `source_layer` | string | `hospitals`, `health_centres`, `clinics`, `pharmacy`, `rehabilitation_center`, `provision_health_service`, `diagnostic_centers`, `mobile_health_unit`, `dialysis_centre` |
| `facility_name_en` / `facility_name_ar` | string | As published |
| `license_no`, `license_status` | string | See the `LICENSESTATUS` caution above |
| `type`, `category`, `subtype` | string | Classification as published |
| `region`, `city` | string | Blank for 434 rows |
| `is_public`, `has_insurance` | Yes/No | |
| `thiqa`, `basic`, `enhanced` | string | Always `N/A` — retained for fidelity, **never read** |
| `beds`, `specialities`, `professionals` | composite string | Verbatim; parse deliberately |
| `inpatient_bed_capacity` | integer | **Use this for bed counts** |
| `emergency_department`, `pediatric_emergency_department`, `maternity_emergency_care`, `home_care_services` | Yes/No | |
| `longitude`, `latitude` | float (WGS84) | **Null** where `geo_quality` is `missing_placeholder` |
| **`geo_quality`** | enum | **`ok` (5,299) · `swapped_repaired` (31) · `missing_placeholder` (6) · `out_of_bounds` (3)** |

**`geo_quality` must be carried through any downstream use.** Rows that are not `ok` or
`swapped_repaired` have **no usable coordinates** and must be excluded from a map, never plotted
at a default location. Companion `quality_report.json` records the output SHA-256, per-layer
counts, the bounding box used and the field cautions.

**Reconciliation, for the record:** Active-licence hospitals here total 71 facilities and 8,828
beds, against SCAD indicators 2801/4111 reporting 75 hospitals and 8,082 beds for 2025. The
definitions differ (licensed capacity vs operational beds) — **the two must not be combined.**

---

## 7. `processed/` — conventions for future outputs

Beyond the facility table above, each new output must be documented here with: source raw file,
transformation script, every column with type and units, row count, and the exact missing-value
convention. Required of every processed file:

| Column | Type | Meaning |
|---|---|---|
| `source_id` | string | Manifest ID of the originating raw file (e.g. `SRC-18-ABUDHABI-SDI-FACILITIES`) |
| `source_reference_period` | string | Reference period carried forward from the source |
| `transform_version` | string | Semantic version of the transformation code |
| `generated_at` | ISO 8601 timestamp | When the file was produced |

> The facility table predates this convention and records equivalent provenance in its companion
> `quality_report.json` instead. Later outputs should carry the columns.

A processed file must be reproducible from `raw/` plus committed code. If it is not, it does not
belong in `processed/`.

---

## 8. `synthetic/` — specification only, nothing exists yet

Entity and field definitions for the synthetic population are specified in
[`synthetic_data_spec.md`](synthetic_data_spec.md). That spec is the contract; this dictionary will
describe the generated files once they exist.

Every synthetic table will carry, without exception:

| Column | Type | Meaning |
|---|---|---|
| `is_synthetic` | boolean, always `true` | Hard marker — no synthetic row ever lacks it |
| `generator_version` | string | Semantic version of the PulseReach generator |
| `generation_seed` | integer | Reproducibility |
| `clinically_validated` | boolean, always `false` | Honest status |

---

## Conventions for everything in `data/`

| Convention | Rule |
|---|---|
| Dates | ISO 8601 (`YYYY-MM-DD`). Timestamps in UTC with offset. |
| Missing values | Preserved as the source encodes them in `raw/`. In `processed/`, a single documented convention, with "not applicable" distinguished from "not reported" and from zero. **The full marker set across held sources is `{-, :, Not Stated, Not stated, Missing/Unknown}` — `-` in births 2024, `:` in births 2025, `Missing/Unknown` in 35 API indicators. None may be coerced to 0.** |
| Aggregate members | SCAD API dimensions embed their own aggregate (`Total`, `Emirate of Abu Dhabi`) as a member row in 65 of 86 indicators. **Filter aggregate members before any `SUM`**, or totals double-count. |
| Region | `Abu Dhabi Region`, `Al Ain Region`, `Al Dhafra Region` — matching SCAD and IFHAS Appendix 1. `Abroad` only where the source has it. |
| Age | Store date of birth; derive age at evaluation time. Missing DOB yields `insufficient_information`, never an age (see `rules/common/status_definitions.yaml`). |
| Units | Stated explicitly in every column description. Counts and percentages are never mixed in one column. |
| Identifiers | Synthetic identifiers only, `SYNTH-` prefixed. Never a real Emirates ID format that could validate. |
