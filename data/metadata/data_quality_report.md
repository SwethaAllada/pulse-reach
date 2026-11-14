# PulseReach — Data Quality Report

**Date:** 2026-11-14
**Scope:** every file held in `data/` as of this date — two SCAD workbooks. Nothing else has been
downloaded, so nothing else is assessed here.
**Method:** each file opened with `openpyxl`, sheets and table layouts enumerated, column headers
and missing-value markers read cell-by-cell, and every stated total recomputed from its components.

> **No file in `data/` has been clinically validated.** "Validated" below means *structurally*
> inspected and arithmetically cross-checked. It does not mean the data is fit for any clinical
> purpose.

---

## 1. Summary

| File | Opens | Structure | Totals reconcile | Fit for intended use |
|---|---|---|---|---|
| `raw/scad/scad_health_statistics_2022_en.xlsx` | Yes | 11 sheets, as published | **Yes — exactly** | Yes, as aggregate context and facility-mix shape |
| `raw/scad/scad_birth_statistics_2024_en.xlsx` | Yes | 8 sheets, as published | **Yes — exactly** | Yes, as birth-cohort shape |

Both files are authentic SCAD publications, internally consistent, and unmodified since download
(SHA-256 recorded in the manifest). Neither contains individual-level data. Neither contains any
preventive-screening indicator.

---

## 2. `scad_health_statistics_2022_en.xlsx`

### Verified

- **Opens cleanly.** `Microsoft Excel 2007+`, 1,173,070 bytes, 11 sheets:
  `Index`, `Table 1`–`Table 8`, `Metadata`, `Enquiries`.
- **Totals reconcile exactly.** Table 2: the three regional columns sum to the stated Total on
  every row (Hospitals 42+18+7 = 67; Health Centres 730+320+86 = 1,136; Clinics 405+211+149 = 765;
  Pharmacies 721+286+61 = 1,068; Others 221+63+3 = 287), and the five facility-type rows sum to the
  stated grand total of 3,323. Table 4: Doctors + Nurses + Dentists + Pharmacists + Others =
  12,922 + 32,933 + 3,029 + 5,269 + 12,628 = **66,781**, matching the stated total. Table 1's
  headline figures (3,323 facilities; 7,372 beds; 66,781 professionals; 53,875 blood units) agree
  with the detail tables.
- **Provenance stated in-file.** Every table carries "Source: Health Department - Abu Dhabi."
- **Glossary present.** The `Metadata` sheet defines Clinic, Health center, Hospital, Patient and
  Diagnosed condition, and links a Health Statistics Methodology document.

### Problems found

| # | Issue | Severity | Consequence |
|---|---|---|---|
| H1 | **Reference period is 2022** — four years old as of today. 2023/2024 editions were not located on the SCAD health publications page (the newest listed is this 2022 file). | High | Any figure quoted must be labelled "2022". It cannot describe the current facility estate. |
| H2 | **Not a tidy dataset.** Title in row 2, unit in row 3, row-dimension label in row 5, column headers in row 6/7, data from row 7/8, source note below. Arabic labels occupy parallel columns. A default `read_excel` yields garbage. | Medium | Every table needs an explicit per-sheet read (skiprows/usecols). Cannot be ingested generically. |
| H3 | **Tables 6 and 7 are percentages of the infection mix, not rates.** Each column sums to 100% — they describe which diseases make up infections within a group, not how common infection is. | High | Cannot be converted to counts. Must never be used as a risk or prevalence input. |
| H4 | **Table 7 age bands (0-14, 15-29, 30-44, 45-59, 60+) do not align with any IFHAS band** (18-39, 40-64, 65-75, 25-29, 30-65, 40-75, 50-64, 55-75, 60-75, 20-34, 35-39, 20-35). | High | No mapping exists. Do not interpolate one; doing so would invent clinical data. |
| H5 | **Floating-point artefacts.** Percentage totals print as `100.00000000000001` / `99.99999999999999`. | Low | Round for display; never compare percentages for equality. |
| H6 | **No facility names, addresses or coordinates.** Counts by type and region only. | High | Cannot support a map view. The synthetic facility layer needs invented locations (see §5). |
| H7 | **No preventive-screening indicators at all** — no IFHAS uptake, no well-child attendance, no screening coverage. | High | Confirms that screening history has no official source and must be synthetic. |
| H8 | **No publication-date field in the workbook.** Only the HTTP `Last-Modified` header (2023-11-06) is held, which is a server timestamp. | Low | Cite the reference period (2022), not a publication date. |

---

## 3. `scad_birth_statistics_2024_en.xlsx`

### Verified

- **Opens cleanly.** 1,177,885 bytes, 8 sheets: `Index`, `Table 1`–`Table 5`, `Metadata`,
  `Enquiries`.
- **Totals reconcile exactly, in both directions.** Table 1 rows: Emirati 9,676 + 5,524 + 318 + 110
  = **15,628** as stated. Table 1 columns: Abu Dhabi Region 9,676 + 17,510 + 167 = **27,353**;
  Al Ain 5,524 + 5,307 + 43 = **10,874**; Al Dhafra 318 + 675 + 3 = **996**. Grand total
  15,628 + 23,492 + 213 = **39,333** as stated. Male/Female sub-rows sum to their citizenship rows.
- **Provenance stated in-file.** "Source: Department of Health – Abu Dhabi".
- **Glossary present** — defines live birth (full WHO wording) and sex ratio at birth.
- **Reference period is current-ish:** 2024, the most recent annual edition. A 2025 edition
  (`publication_64080_17_1_1_2025_EN.xlsx`) is listed on the SCAD population page and should be
  checked before the figures are used in a submission.

### Problems found

| # | Issue | Severity | Consequence |
|---|---|---|---|
| B1 | **A fourth region column, `Abroad`** (110 births), sits between Al Dhafra and the emirate total. Code assuming three regions will mis-total by 110 or silently treat `Abroad` as Al Dhafra. | High | Read region columns by header, never by position. `Abroad` is a distinct category. |
| B2 | **Two different missing-value encodings.** The literal string `"-"` appears in cells, *and* there are explicit `Not Stated (Gender)` / `Citizenship Not Stated` categories. `Emirati × Abroad` = 110 while `Non-Emirati × Abroad` = `"-"`. | High | `"-"` must not be coerced to 0 — it means not applicable/not reported. A naive numeric cast produces a column of mixed types or silent zeros. |
| B3 | **`Not Stated (Gender)` rows total 0** across all regions while the category still exists, and `Citizenship Not Stated` is a real 213 births. | Medium | Retain both categories. Dropping "not stated" would overstate data completeness — exactly the kind of silent cleaning the governance rules forbid. |
| B4 | **Same non-tidy publication layout** as the health workbook. | Medium | Per-sheet explicit reads required. |
| B5 | **Births ≠ well-child attendance.** The file carries no screening, visit or outcome data. | High | The Well-Child pathway gets a cohort *size* from this file and nothing else. |
| B6 | **Single year only.** No multi-year series in this file, so no cohort ageing. | Medium | A 0–6 synthetic cohort needs seven birth years; only 2024 is held. Either fetch 2019–2023 editions or state the flat-cohort assumption explicitly in the generator. |

---

## 4. Population context figures (no file)

Figures read from the SCAD census portal are recorded in the manifest, not in `data/raw/`, because
SCAD publishes no file for them. One quality finding is worth stating because it affects any use:

| # | Issue | Severity | Consequence |
|---|---|---|---|
| P1 | **The age-by-sex pyramid is rounded and does not reconcile to the headline totals.** Summing the 18 bands gives female 1,368,935 and male 2,767,065 (total 4,136,000) against stated figures of 1,368,925 / 2,767,060 (total 4,135,985) — a discrepancy of +10, +5 and +15. The band values are evidently rounded to the nearest 5. | Medium | Usable as a *distribution shape*, never as counts. Do not publish band figures as exact. Any synthetic cohort built from them must be described as approximating the 2024 age structure, not reproducing it. |
| P2 | **No methodology, revision status or per-dataset licence** accompanies the pyramid, since it is a page asset rather than a published dataset. | Medium | Do not promote it into `data/raw/` as if it were a dataset. Request the table from SCAD (`info@scad.gov.ae`) if it is needed as data. |
| P3 | **2024 figures are subject to SCAD's statistical revision policy** (2023 is already published as "R1", a revision). | Low | Record the read date alongside any quoted figure. |

The 0–4 band (206,745 people) is the only direct read on the Well-Child age range, and it does not
decompose into the single years of age that the 14-visit schedule needs.

---

## 5. Gaps that no held file can close

These are the things PulseReach needs and that **no acquired source provides**. They are listed
here so the gap is a documented fact rather than an assumption a later phase might paper over.

| Need | Status | Resolution |
|---|---|---|
| Individual-level patient records | No official source; none permitted | Synthetic only (Synthea base + custom layer) |
| IFHAS screening history / uptake | **No source whatsoever**, confirmed again by H7 | Custom synthetic generation |
| Well-Child visit attendance | **No source whatsoever** | Custom synthetic generation |
| Screening coverage rates for Abu Dhabi | Not in any held file | None available — do not estimate one |
| Facility names and coordinates | Not in SCAD (H6); MOHAP geocoded file unverified and unreachable | Synthetic facilities, proportioned to SCAD Table 2 counts, with invented coordinates clearly labelled |
| Single-year-of-age child population | Only a 0–4 aggregate (P3) | Approximate from births (B6) and state the assumption |
| Abu Dhabi disease prevalence | **Not available.** Tables 6–7 are not prevalence (H3) | Do not use. NHANES must not substitute. |

---

## 6. Assessment

**The two held files are good quality for what they are** — authentic, internally consistent,
unmodified, attributable aggregate official statistics. Their totals reconcile to the unit, which
is a meaningful check that the download is complete and uncorrupted.

**They are not, and cannot become, the data PulseReach runs on.** They contain no individuals and
no screening information. Their value is bounded and specific: real regional facility counts and a
real birth cohort to make a synthetic population plausible, plus citable context figures.

The most consequential finding is a negative one, now confirmed from files rather than inferred
from documentation: **no official source provides Abu Dhabi preventive-screening history,
attendance or coverage.** Every screening record PulseReach uses will be synthetic, and the system
must say so wherever it shows one.
