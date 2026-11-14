# PulseReach — Data Dictionary

Field-level description of datasets held in `data/`. One section per file actually on disk, plus a
section for the planned synthetic tables.

**Status as of 2026-11-14:** two files held, both SCAD aggregate statistics. `processed/` and
`synthetic/` are empty, so their entries below are **specifications of intent**, clearly marked as
such, not descriptions of existing data.

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

## 3. Abu Dhabi population context (no file held)

Recorded in the manifest as `SRC-12-SCAD-CENSUS-POPULATION-2024` because the figures matter but
**SCAD publishes no file** — the census portal's download buttons produce PNG images of charts.

Figures read from <https://census.scad.gov.ae/home/PReport?lang=en> on 2026-11-14, as of
September 2024: total 4,135,985; Abu Dhabi Region 2,823,340; Al Ain 986,910; Al Dhafra 325,735;
male 2,767,060; female 1,368,925; median age 33 years. A 5-year age-by-sex pyramid (0-4 … 85+)
exists only as JavaScript literals in a page script.

These are **context figures**, held in the manifest rather than in `data/raw/`, precisely because
they are not a published dataset. They may calibrate the *shape* of a synthetic population and may
be quoted with SCAD attribution. They are not a prevalence source and must never be disaggregated
into individuals.

---

## 4. `processed/` — specification only, nothing exists yet

When transformation code is written, each output will be documented here with: source raw file,
transformation script, every column with type and units, row count, and the exact missing-value
convention. Required of every processed file:

| Column | Type | Meaning |
|---|---|---|
| `source_id` | string | Manifest ID of the originating raw file (e.g. `SRC-10-SCAD-HEALTH-2022`) |
| `source_reference_period` | string | Reference period carried forward from the source |
| `transform_version` | string | Semantic version of the transformation code |
| `generated_at` | ISO 8601 timestamp | When the file was produced |

A processed file must be reproducible from `raw/` plus committed code. If it is not, it does not
belong in `processed/`.

---

## 5. `synthetic/` — specification only, nothing exists yet

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
| Missing values | Preserved as the source encodes them in `raw/`. In `processed/`, a single documented convention, with "not applicable" distinguished from "not reported" and from zero. |
| Region | `Abu Dhabi Region`, `Al Ain Region`, `Al Dhafra Region` — matching SCAD and IFHAS Appendix 1. `Abroad` only where the source has it. |
| Age | Store date of birth; derive age at evaluation time. Missing DOB yields `insufficient_information`, never an age (see `rules/common/status_definitions.yaml`). |
| Units | Stated explicitly in every column description. Counts and percentages are never mixed in one column. |
| Identifiers | Synthetic identifiers only, `SYNTH-` prefixed. Never a real Emirates ID format that could validate. |
