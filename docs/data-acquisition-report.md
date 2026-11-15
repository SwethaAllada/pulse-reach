# PulseReach — Data Acquisition Report

**Phase:** 2.5 — Comprehensive official data acquisition and validation
**Acquisition window:** 14–15 November 2026
**Network context:** non-UAE network (Cloudflare edge `MAA`). This materially affects what
could be reached; every block below records the exact failure.

> **Scope discipline.** This phase acquires and validates data only. No database design, no
> migrations, no synthetic generation, no API or frontend work was performed.

---

## 1. Executive summary

The previous audit held **two** SCAD workbooks and concluded that Abu Dhabi population
structure and health-facility locations were not obtainable as data. **Both of those
conclusions are now obsolete.** Two machine-readable official endpoints were located and
successfully harvested:

1. **SCAD statistics API** (`statad.gov.ae`, Liferay proxy → ClickHouse backend) — **86
   Abu Dhabi indicators** with full time series, including 2025 population estimates by
   region and gender, all eight health indicators named in the brief, and the full
   infant/neonatal/under-five mortality set.
2. **Abu Dhabi SDI ArcGIS OpenData service** (`arcgis.sdi.abudhabi.ae`) — **5,339 geocoded
   licensed health facilities** with WGS84 coordinates, names, licence numbers and status.

Net result: **the two gaps the prior quality report called unclosable (H6 facility
coordinates, P1/P2 population structure) are closed**, from official sources, with licences
read verbatim from the publishers.

| | Before this phase | After |
|---|---|---|
| Files in `data/raw/` | 2 | 215 |
| Abu Dhabi population by region/gender | web page figures only | 2025 API series, reconciled |
| Health-facility coordinates | none | 5,339 facilities, 99.3% clean |
| Latest health-system reference period | 2022 | 2025 |
| Birth/death statistics | 2024 births only | 2024 + 2025 births, 2025 deaths |

**What did not change: there is still no Abu Dhabi preventive-screening data.** No IFHAS and
no Well-Child Visit programme performance figures are published anywhere official. This is now
confirmed by direct search of ADPHC, DoH and the Abu Dhabi open-data catalogue, not inferred.

**Recommendation: READY FOR PHASE 3** — see §9.

---

## 2. Every source investigated

| # | Source | Endpoint | Result |
|---|---|---|---|
| 1 | SCAD statistics API | `statad.gov.ae/o/communication?url=Statistics/...` | ✅ **86 indicators acquired** |
| 2 | SCAD publications (population) | `statad.gov.ae/population?ThemeID=227` | ✅ Births 2025, Deaths 2025 |
| 3 | SCAD publications (health) | `statad.gov.ae/health?ThemeID=221` | ✅ Health tables; 2022 re-verified |
| 4 | Abu Dhabi SDI ArcGIS | `arcgis.sdi.abudhabi.ae/agspublish/...` | ✅ **5,339 facilities** |
| 5 | Abu Dhabi Open Data catalogue | `data.abudhabi/opendata/apis/search_main.php` | ✅ 614 datasets enumerated |
| 6 | Abu Dhabi Open Data metastore | `.../api/1/metastore/schemas/dataset/items/<id>` | ✅ 33 records; 7 files |
| 7 | SCAD census portal | `census.scad.gov.ae` | ⚠️ Reachable, no data file (superseded by #1) |
| 8 | MOHAP Open Data | `mohap.gov.ae/en/open-data/mohap-open-data` | ❌ **TLS blocked** |
| 9 | FCSC / UAE.Stat | `uaestat.fcsc.gov.ae`, `*.fcsc.gov.ae/rest` | ❌ **Cloudflare 403** |
| 10 | DoH portal & Tableau | `doh.gov.ae`, `tableau.doh.gov.ae` | ❌ TLS blocked / **no DNS record** |
| 11 | Bayanat.ae | `bayanat.ae/en/Datasets` | ⚠️ Reachable, no health dataset found |
| 12 | ADPHC IFHAS programme | `adphc.gov.ae/en/Public-Health-Programs/IFHAS` | ⚠️ Reachable, **no statistics** |
| 13 | `ifhas.gov.ae` | advertised by DoH Aug 2025 | ❌ **HTTP 404** |

---

## 3. Datasets actually downloaded

### 3.1 SCAD statistics API — `data/raw/statad_api/` (158 files, 6.48 MB)

86 indicator JSON extracts + 71 official metadata/methodology XLSX workbooks.

**Discovery.** The portal is Liferay; indicator pages are server-rendered shells. The data
arrives through a proxy declared inline in the page module:

```
PROXY_BASE          = https://statad.gov.ae/o/communication?url=
DETAIL_API_PATH     = Statistics/GetClickhouseIndicatorDetail      (?indicatorId=&lang=EN)
API_BASE_PATH       = Statistics/GetClickhouseKeyStatisticsIndicatorsOverview  (?themeId=221&lang=EN)
DOWNLOAD_METADATA   = Statistics/GetMetadataAndMethodology         (?indicatorId=&lang=EN → XLSX)
```

The overview call returns **1,700 indicators** across all themes; 167 matched health or
population keywords and 86 were selected as in-scope (§8 priorities).

Headline values, all **reconciled** (region members sum exactly to the stated emirate total):

| Indicator | ID | 2025 value | Series |
|---|---|---|---|
| Population estimates | 3916 | 4,358,921 | 1960–2025 |
| Population by region | 3175 | AD 3,008,513 / Al Ain 1,003,647 / Al Dhafra 346,761 | 2006–2025 |
| Population by gender | 3919 | M 2,927,357 / F 1,431,564 | 1960–2025 |
| Hospitals | 2800 / 2801 | 75 | 2009–2025 |
| Hospital beds | 4111 / 4052 | 8,082 | 2010–2025 |
| Clinics | 2825 / 2845 | 925 | 2009–2025 |
| Health centres | 2822 / 2823 | 1,309 | 2009–2025 |
| Physicians | 2701 / 3998 | 13,811 | 2010–2025 |
| Nurses | 2702 / 2703 | 30,277 | 2010–2025 |
| Inpatients by illness | 2590 | 302,781 | 2023–2025 |
| Inpatients by citizenship | 2589 | — | 2010–2025 |
| Cancer deaths | 2614 | 780 | 2009–2025 |
| Births | 3463/3465/3466 | 41,235 | **1977–2025** |
| Infant mortality rate | 3319 | 5.38 /1,000 live births | 2015–2025 |
| Under-five mortality rate | 3280 | 6.99 /1,000 live births | 2015–2025 |
| Health insurance members | 2677 | 1,024,271 | 2022–2025 |

All eight indicators named in the brief (§3) were acquired. **Clinics by region, hospital beds
by region, physicians by facility region, inpatients by citizenship / illness / facility
region, and cancer deaths are all present with 2025 reference periods.**

### 3.2 Abu Dhabi SDI facilities — `data/raw/abudhabi_sdi/` (10 files, 8.44 MB)

Retrieved as GeoJSON (`outSR=4326`) from `OpenData/ADSDI_OpenData/MapServer`:

| Layer | ID | Features |
|---|---|---|
| Hospitals | 330 | 114 |
| Health Centres | 329 | 1,290 |
| Clinics | 328 | 1,250 |
| Pharmacy | 332 | 1,715 |
| Rehabilitation Center | 234 | 434 |
| Provision Health Service | 236 | 387 |
| Diagnostic Centers | 217 | 87 |
| Mobile Health Unit | 235 | 49 |
| Dialysis Centre | 231 | 13 |
| **Total** | | **5,339** |

43 attributes per feature including `FACILITYNAME` (EN/AR), `FACILITYLICENSE`,
`LICENSESTATUS`, `REGION`, `CITY`, `INPATIENTBEDCAPACITY`, `SPECIALITIES`, `PROFESSIONALS`.

**How this was found:** the five Gov-Digital "Hospitals/Clinics/..." XLSX files on
`data.abudhabi` are *not* data — each is a single cell containing an ArcGIS MapServer URL
(`.../Pub/CF_Health/MapServer/<n>`, now 404). The DoH 2025 datasets' `esri rest`
distributions named the live path, which resolved.

### 3.3 SCAD publications — `data/raw/scad/` (5 files, 4.79 MB)

| File | Bytes | SHA-256 (first 16) | Period |
|---|---|---|---|
| `scad_birth_statistics_2025_en.xlsx` | 1,155,510 | `37c8b6b3051a7624` | 2025 |
| `scad_death_statistics_2025_en.xlsx` | 1,211,030 | `2e49419e1b0fe37c` | 2025 |
| `scad_health_tables_en.xlsx` | 70,622 | `d52df9c01181a446` | historical |
| `scad_health_statistics_2022_en.xlsx` | 1,173,070 | `398529220d625a7b` | 2022 *(pre-existing)* |
| `scad_birth_statistics_2024_en.xlsx` | 1,177,885 | `bba301a8e8538d73` | 2024 *(pre-existing)* |

**The two pre-existing files are byte-for-byte unchanged.** The 2022 source URL was re-fetched
and returned SHA-256 `398529220d625a7b68dec04a34a902fa5603f9c026ee3a47d2920d4c4a76ff27`,
**identical** to the held copy — independent confirmation the original download is authentic
and uncorrupted.

### 3.4 Abu Dhabi Open Data portal — `data/raw/abudhabi_opendata/` (42 files, 0.45 MB)

33 DCAT metadata records, a 614-dataset catalogue snapshot, and 7 downloaded files
(5 Gov-Digital pointer workbooks + 2 MOHAP nurse workbooks from the brief's named example).

---

## 4. Every failed download, with exact reason

| Source | URL | Failure | Evidence it is environmental, not absence |
|---|---|---|---|
| **MOHAP Open Data** | `https://mohap.gov.ae/en/open-data/mohap-open-data` | `curl: (35) LibreSSL SSL_connect: SSL_ERROR_SYSCALL` — fails at TLS **Client Hello** | DNS resolves (`185.54.16.190`); TCP connects on :443; handshake is then terminated. Tried `www.` and plain HTTP. **The portal and its five named datasets were never reached — nothing is claimed about their contents.** |
| **FCSC / UAE.Stat** | `uaestat.fcsc.gov.ae/en`, `releaseeuaestat…/rest`, `designuaestat…/rest`, `apiuaestat…`, `chartsuaestat…`, `opendata.fcsc.gov.ae` | **HTTP 403**, `server: cloudflare`, `cf-ray: …-MAA` | `uaestat.fcsc.gov.ae/vis` returns **200**, so the host is alive; the WAF rejects the API paths from this edge. A .Stat **SDMX REST** API exists (`/rest/dataflow/all/all/latest`) and would be the correct route from a permitted network. |
| **DoH portal / standards** | `www.doh.gov.ae/...` | `SSL_ERROR_SYSCALL` | Same class as MOHAP. IFHAS / WCV / RAI PDFs still not held locally; their content remains transcribed in `data-pipeline/rules/`. |
| **DoH Tableau datasets (18)** | `https://tableau.doh.gov.ae/<Name>` | **No DNS A record** | `dig tableau.doh.gov.ae` returns nothing. These are **dead links in the publisher's own catalogue**, not a network block — and they are mislabelled `format: csv` while being dashboard pages. Affects Population Structure, Diabetes Prevalence, Cancer Incidence, Facilities, Clinicians, Bed Occupancy, Vital Statistics and 11 more. |
| **Gov-Digital facility XLSX (5)** | `data.abudhabi/.../Hospitals.xlsx` etc. | Downloaded (200) but **contain no data** | Each holds one cell: a `Pub/CF_Health/MapServer/<n>` URL that now 404s. Superseded by §3.2. |
| **Catalogue bulk list** | `.../metastore/schemas/dataset/items` (unfiltered) | Timeout >60 s, repeated | Worked around via `search_main.php` pagination (614 datasets enumerated). |
| **`ifhas.gov.ae`** | `https://www.ifhas.gov.ae/` | **HTTP 404** | Advertised as the programme's data destination in an official DoH media release of 1 Aug 2025. Does not resolve to content. |

---

## 5. Source and dataset coverage

### Geographic
- **Abu Dhabi-specific:** all 86 SCAD indicators; all 5,339 SDI facilities; SCAD birth/death
  publications. Region dimension is consistently **Abu Dhabi / Al Ain / Al Dhafra**.
- **UAE-wide (must NOT be read as Abu Dhabi):** the two MOHAP nurse workbooks
  (`data/raw/abudhabi_opendata/files/mohap_nurses_*`) are national, by *medical district*,
  **reference year 2008**. Retained only because the brief named them; **not fit for use**.
- **No national total is used anywhere as an Abu Dhabi figure.**

### Temporal
2025 for the current health-system, population and vital-statistics picture; 2022 for the
legacy SCAD health workbook; **2008** for the MOHAP nurse files. Series reach back to 1977
(births) and 1960 (population). **2022 and 2025 definitions are documented separately and are
not compared** — see §6.4.

---

## 6. Data-quality findings

Full detail in [`data/metadata/data_quality_report.md`](../data/metadata/data_quality_report.md).
The consequential ones:

### 6.1 Embedded aggregate rows — HIGH, systematic
**65 of 86 indicators include an aggregate member inside the dimension itself** (`Total`, or
`Emirate of Abu Dhabi` in `REGION_EN`). A naive `GROUP BY … SUM()` **double-counts**.
`3466_births_by_gender` sums to 82,470 against a true 41,235. Every consumer must filter
aggregate members explicitly.

### 6.2 A third missing-value convention — HIGH
| Edition | Marker | Cells |
|---|---|---|
| Births 2024 (held) | `-` | 57 |
| **Births 2025 (new)** | **`:`** | **67** |
| Deaths 2025 | none | 0 |

The convention **changed between editions of the same publication**. Code written against
2024 will mis-parse 2025. Additionally **35 of 86 API indicators** carry a `Missing/Unknown`
dimension member, and the 2025 publications add a `Not stated` **region** column alongside the
pre-existing `Abroad`.

### 6.3 Corrupted age-band labels in SCAD's own API — HIGH
In `4868_projection_of_population_by_age_group`, bands `5-9` and `10-14` are returned as
**`"2026-05-09"`** and **`"2026-10-14"`** — date coercion applied upstream. It affects the
**Arabic labels identically**, so it is in SCAD's pipeline, not a locale artifact. The values
(209,060 and 182,960) are intact; only the labels are wrong. They must be remapped explicitly
and the remap documented, never silently trusted.

### 6.4 Rounding and reconciliation
- 2024 age bands sum to **4,146,925** against a stated total of **4,135,985** — **+10,940**
  (the band values are multiples of 5, but rounding cannot explain the gap; the cause is
  **unexplained** — see `mappings/phase-3-reconciliation-report.md` §3.B, AG-3). Usable as a
  *distribution shape*, never as counts. This is a larger discrepancy than the ±15 previously found on the census page.
- **Facility register vs SCAD, restricted to `Active` licences:** 71 hospitals / 8,828 beds
  (SDI) against 75 hospitals / 8,082 beds (SCAD 2801/4111) — **5% and 9% variance**. Close
  enough to confirm both describe the same estate; far enough apart to prove the definitions
  differ (licensed capacity vs operational beds). **Do not combine them.** Unfiltered, the
  register sums to 11,721 beds across 114 hospitals, including cancelled and expired licences.
- Births 2025 reconciles **exactly** across three independent API cuts and the XLSX: 41,235.

### 6.5 Facility geometry — MEDIUM, bounded and corrected
40 of 5,339 features (0.75%) were defective: 31 lon/lat transposed, 6 at `(0,0)`, 3 genuinely
outside the emirate (two in Saudi Arabia). All are repaired or flagged — never dropped — in
`data/processed/facilities/`, each row carrying `geo_quality`.

### 6.6 Facility attribute traps — MEDIUM
- `THIQA`, `BASIC`, `ENHANCED` are **`N/A` in every row**. They look like insurance-acceptance
  flags and carry no information. **IFHAS Thiqa eligibility cannot be derived from this file.**
- `BEDS`, `SPECIALITIES`, `PROFESSIONALS` are **semicolon-delimited composite strings**, not
  numbers (`"Acute Care , Pediatric , 38 , 0 , 0; …"`). Casting them yields nothing.
  `INPATIENTBEDCAPACITY` is the bed field but is held in the source as a **string**: `"0"`,
  `""` (not recorded, not zero) and `null` (unidentified record) are distinct states
  (see `mappings/phase-3-reconciliation-report.md` §3.E, FA-2).
- Only **3,005 of 5,339** rows are `Active`; 434 (all `rehabilitation_center`) have a blank
  region and status.

### 6.7 Carried forward from the 2022 workbook
Tables 6–7 remain **percentage-of-infection-mix, not prevalence**, and their age bands still
align with no IFHAS band. Unchanged and still disqualifying for risk use.

---

## 7. Known data gaps

| Gap | Status | Resolution path |
|---|---|---|
| **IFHAS programme performance** (eligible population, participation, completion, package-wise or regional uptake, referral completion) | **Not published anywhere.** ADPHC programme page, DoH news, Abu Dhabi catalogue (614 datasets, 1 match for "screening") all checked. Only undated press figures exist (≈195,000 enrolled; >150 facilities). | Formal request: `IFHAS.Support@adphc.gov.ae`, DoH DDGO `DDG@doh.gov.ae`. Aggregate only — **never identifiable records**. |
| **Well-Child Visit performance** | **Not published.** Nearest official figures are newborn-screening uptake 98% (2021) and 322,000 school screenings (2024) — different programmes. | `WCV.Support@adphc.gov.ae` |
| Single-year-of-age child population | Only 5-year bands, and the 5–9 / 10–14 labels are corrupt (§6.3) | Derive from the 1977–2025 births series; state the assumption |
| Facility-level Thiqa acceptance | Columns exist but are empty (§6.6) | DoH licensing data request |
| MOHAP geocoded facilities, child vaccination, mortality 2024, historical matrix | **Unreached** (§4) | Re-run from a UAE network |
| FCSC emirate cross-checks | **Unreached** (§4) | SDMX REST from a permitted network |
| Abu Dhabi disease prevalence | Still unavailable; 2022 Tables 6–7 are not prevalence | None. Do not estimate. NHANES must not substitute. |

**The central negative finding stands: no official source provides Abu Dhabi preventive-screening
history, attendance or coverage.** Every screening record PulseReach uses will be synthetic, and
the system must say so wherever it shows one.

### Resolved and newly unresolved questions
- `OQ-IFHAS-AGE-CEILING` — **still unresolved, and now better evidenced.** The ADPHC programme
  page states "aged 18 to 75", while an official DoH media release of **1 Aug 2025** states
  "Thiqa cardholders aged 18 and above". Official sources contradict each other *today*. Keep
  the package-band rule and the >75 flag.
- **New:** `ifhas.gov.ae`, named in that same release as the programme's destination, returns 404.

---

## 8. Suitability for PulseReach

| Dataset | Suitable? | Role |
|---|---|---|
| SCAD population estimates/projections (3916, 3175, 3919, 4868–4870) | **Yes** | Synthetic population age/sex/region calibration — as a *shape*, with §6.4 rounding stated |
| SCAD births 1977–2025 (3463/3465/3466/3549) | **Yes** | Well-Child birth cohorts across seven birth years — closes prior gap B6 |
| SCAD capacity & workforce (2800–2848, 2701–2731, 4052/4111) | **Yes** | Real facility/workforce denominators by region, 2025 |
| SCAD infant/neonatal/under-5 mortality | **Yes** | Child-health context and narrative framing |
| SCAD inpatients/outpatients, cancer deaths, communicable disease | **Yes, with care** | Context only; disease mix ≠ prevalence |
| **SDI facility register (5,339)** | **Yes** | Real coordinates for the outreach map — closes prior gap H6 |
| `processed/facilities/*.csv` | **Yes** | The validated facility layer |
| SCAD Health Statistics 2022 | **Yes, labelled 2022** | Legacy comparison only; superseded by the API |
| SCAD health tables (historical) | Marginal | Long-run context |
| **MOHAP nurse workbooks (2008, UAE-wide)** | **No** | Retained for provenance; wrong geography, 18 years stale |
| **DoH Tableau datasets** | **No** | Dead links (§4) |
| **Gov-Digital pointer XLSX** | **No** | Contain no data; superseded |
| NHANES / Synthea | Deliberately not acquired | Out of scope this phase; US-derived, kept separate |

---

## 9. Final data-readiness decision

# ✅ READY FOR PHASE 3

**Why.**

1. **The priority datasets were actually downloaded.** 215 files, 20 MB, every one
   SHA-256-checksummed and verified (`data/reference/raw_checksums.sha256`). Priorities 1–5
   of the brief's §8 are met with 2025 Abu Dhabi data.
2. **Original files were inspected, not assumed.** Every workbook opened; every API extract
   parsed; dimensions, units, reporting periods and row counts recorded.
3. **Quality checks were performed and found real defects** — embedded aggregates, a changed
   missing-value convention, corrupted age labels, transposed coordinates, empty insurance
   columns, dead publisher links. All documented with severity and consequence. Finding them
   is the point of the phase.
4. **Totals reconcile.** Region members sum exactly to stated totals across every indicator
   tested; births 2025 agrees across three API cuts and the XLSX; the facility register
   cross-validates against SCAD to within 5–9% once licence status is respected.
5. **Abu Dhabi data is distinguished from UAE-wide data** throughout, and the one UAE-wide
   artifact is explicitly marked unfit.
6. **No synthetic data is misrepresented as official.** `data/synthetic/` is still empty.
7. **Gaps are explicit**, with named contacts, and the blockers are evidenced rather than
   asserted.

**What Phase 3 must carry forward (non-negotiable):**

- Filter embedded aggregate members before any aggregation (§6.1).
- Treat `-`, `:`, `Not Stated`, `Not stated`, `Missing/Unknown` and `Abroad` as distinct,
  first-class categories — never coerce to zero (§6.2).
- Remap the corrupt `2026-05-09` / `2026-10-14` age bands explicitly (§6.3).
- Never join 2022 and 2025 health figures, or SCAD beds with register capacity (§6.4).
- Carry `geo_quality` through any map view (§6.5).
- Do not read Thiqa eligibility from the facility register (§6.6).
- Screening history remains **100% synthetic** and must be labelled so in every view.

**Still out of scope and not begun:** database design, migrations, synthetic patient
generation, backend APIs, frontend.

---

## 10. Reproducing this acquisition

```bash
# Verify every raw file is unmodified
shasum -a 256 -c data/reference/raw_checksums.sha256

# Rebuild the processed facility table from raw GeoJSON
python3 -I data-pipeline/transformation/build_facilities.py .
```

Acquisition scripts are preserved in `data-pipeline/ingestion/`. All endpoints, parameters and
the discovery method for each are recorded in
[`data/reference/source_manifest.yaml`](../data/reference/source_manifest.yaml).

**Attribution is a licence condition, not a courtesy:**
- SCAD: *Source: Statistics Centre – Abu Dhabi; year of publication, name of the statistical
  product, catalogue and archive numbers, reference period and page(s).*
- Abu Dhabi Government Open Data License: acknowledge the source and link the licence.
  Commercial use is permitted; **the licence grants no right to use Personal Information.**
