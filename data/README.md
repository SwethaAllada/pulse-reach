# PulseReach — `data/`

Datasets and source documents for PulseReach. **Synthetic and public aggregate data only.**
No real patient records, ever.

> The authoritative record of what each source is, where it came from and whether it was
> actually obtained is [`reference/source_manifest.yaml`](reference/source_manifest.yaml).
> This README explains the folder; the manifest holds the facts.

## Layout

| Folder | Holds | Committed? |
|---|---|---|
| `raw/` | Original downloaded files, byte-for-byte as served. Never edited. | Small public files: yes |
| `reference/` | The source manifest, and source documents (DoH standards) when held locally | Manifest: yes. PDFs: no |
| `processed/` | Outputs of transformation code. Always reproducible from `raw/` + code. | No |
| `synthetic/` | Generated synthetic patients and records | Small demo fixtures only |
| `metadata/` | Data dictionary, quality report, synthetic data specification | Yes |

Clinical rules are **not** here. They live in `data-pipeline/rules/` as versioned YAML config —
see [`docs/clinical-rules.md`](../docs/clinical-rules.md). Do not copy or restate them in `data/`.

## What is actually in here right now

**215 files in `raw/`, ~20 MB**, from four official publishers. All are aggregate statistics or a
facility register — **none is individual-level data**. Every file is SHA-256-checksummed in
[`reference/raw_checksums.sha256`](reference/raw_checksums.sha256) and all 215 verify.

| Path | Source | What | Reference period |
|---|---|---|---|
| `raw/scad/` (5 files, 4.8 MB) | Statistics Centre – Abu Dhabi | Health Statistics 2022; Birth Statistics 2024 **and 2025**; Death Statistics 2025; historical health tables | 2022 · 2024 · 2025 |
| `raw/statad_api/` (158 files, 6.5 MB) | SCAD Statistics API | **86 Abu Dhabi indicators** (population, capacity, workforce, utilisation, vital statistics, child mortality, insurance) + 71 official metadata workbooks | mostly 2025; series from 1960/1977 |
| `raw/abudhabi_sdi/` (10 files, 8.4 MB) | Abu Dhabi SDI (ArcGIS) | **5,339 geocoded licensed health facilities**, WGS84 | live register, retrieved 2026-11-14 (copied into the repository 2026-11-15) |
| `raw/abudhabi_opendata/` (42 files, 0.5 MB) | Abu Dhabi Open Data Platform | 614-dataset catalogue snapshot, 33 DCAT metadata records, 7 files | mixed (incl. 2008) |

`processed/facilities/` holds the one validated transformation — the cleaned facility table.
`synthetic/` and `reference/doh_standards/` are still **empty**.

There is still **no** local copy of the IFHAS or Well-Child Visit standards — their content was
transcribed into `data-pipeline/rules/` in an earlier phase, but `doh.gov.ae` terminates the TLS
handshake from this network, so the PDFs themselves are not held.

### Three things to know before writing any code against this data

1. **SCAD API dimensions contain their own totals.** 65 of 86 indicators embed a `Total` or
   `Emirate of Abu Dhabi` member *inside* the dimension. Filter aggregate members before any
   `SUM`, or you double-count — births by gender sums to 82,470 against a true 41,235.
2. **The missing-value marker changed between editions.** Births 2024 uses `-`; births 2025 uses
   `:`; 35 API indicators use `Missing/Unknown`. None may be coerced to 0.
3. **Not every downloaded file contains data.** Five Gov-Digital "facility" workbooks hold a
   single cell containing a dead URL, and 18 DoH catalogue entries point at a host with no DNS
   record. A HTTP 200 is not evidence of content — open the file.

Full detail in [`metadata/data_quality_report.md`](metadata/data_quality_report.md) and
[`../docs/data-acquisition-report.md`](../docs/data-acquisition-report.md).

## Rules for this folder

**1. `raw/` is immutable.** A file in `raw/` is what the publisher served. Never clean it, never
re-save it from Excel, never fix a typo in it. Transformations read from `raw/` and write to
`processed/`. If a raw file must be corrected, document the correction as a transformation step —
do not touch the original.

**2. Every file in `raw/` has a manifest entry** recording its source URL, download date,
reference period, file type, size, SHA-256 and permitted reuse. A file without an entry is not
trusted data; it is an unexplained file.

**3. Aggregate statistics are never individual records.** SCAD publishes counts for the emirate.
Those counts may inform how a synthetic population is *shaped* and may be quoted as context. They
may never be joined to a patient row, disaggregated into people, or used as a per-person value.

**4. US data is not Abu Dhabi data.** NHANES (when acquired) is for pipeline mechanics and
realistic value distributions only. It cannot establish Abu Dhabi prevalence, cannot validate a
local threshold, and must be labelled as a technical scaffold wherever it influences a model
(Responsible AI Standard §3.1.5.1.1).

**5. Synthetic records must be unmistakably synthetic.** See
[`metadata/synthetic_data_spec.md`](metadata/synthetic_data_spec.md) — identifiers carry a
`SYNTH-` prefix, names come from an obviously fictional pool, and every table carries a
provenance column. A synthetic record must never be capable of being mistaken for a real patient.

**6. Nothing here is clinically validated.** Not the rules, not the synthetic data, not any
derived statistic. Every output needs review by a qualified healthcare professional.

## Reproducing the acquisition

```bash
# 1. Verify every raw file is byte-identical to what was downloaded
shasum -a 256 -c data/reference/raw_checksums.sha256

# 2. Rebuild the processed facility table from raw/ (no network needed)
python3 -I data-pipeline/transformation/build_facilities.py .
```

To re-acquire from the publishers, the scripts in `data-pipeline/ingestion/` record the exact
endpoints and parameters used:

| Script | Acquires |
|---|---|
| `fetch_statad_indicators.py` | The 86 SCAD indicators + metadata workbooks |
| `fetch_abudhabi_sdi_facilities.py` | The 9 facility layers as GeoJSON |
| `search_abudhabi_catalogue.py` | The Abu Dhabi catalogue snapshot |
| `fetch_abudhabi_opendata.py` | DCAT metadata and portal file distributions |

Both APIs are **undocumented endpoints recovered from portal JavaScript** — no contract, no
versioning. Treat the local extracts as the source of record; re-acquisition may break.

## Attribution requirement

Two licences apply, both requiring attribution. These are licence conditions, not courtesies, and
they bind the UI, the submission and any slide.

**SCAD** (`raw/scad/`, `raw/statad_api/`) — terms re-read verbatim 2026-11-15 at
<https://statad.gov.ae/terms-of-use>. Reproduction in whole or part by any means is permitted
without further permission, provided:

> Source: Statistics Centre – Abu Dhabi; *year of publication, name of the statistical product,
> catalogue and archive numbers, reference period and page(s)*.

**Abu Dhabi Government Open Data License** (`raw/abudhabi_sdi/`, `raw/abudhabi_opendata/`) — read
verbatim 2026-11-15 from the portal's own licence record. Grants a worldwide, royalty-free,
perpetual, non-exclusive licence to copy, modify, publish, translate, adapt and distribute,
**including for commercial purposes**, conditional on acknowledging the source and linking the
licence. Supplied "as is" with no warranty.

> **Exemption that matters here:** the licence grants **no right to use Personal Information**.
> The facility register carries staff contact details; they are not carried into `processed/` and
> must not be surfaced in any UI or redistributed.

Neither licence addresses this project's specific use. **Legal review is still required per
Responsible AI Standard §3.2.1.5.**

## Adding a dataset

1. Verify the source is public, relevant, permitted and reasonably small.
2. Download into `raw/<publisher>/` without modification. Record the HTTP status,
   `Content-Type`, `Content-Disposition` filename and `Last-Modified` header at the time.
3. Add a `source_manifest.yaml` entry with `acquisition.state: dataset_obtained`, the source URL,
   download date, reference period, bytes, SHA-256 and the licence terms **as read from the
   publisher**, not as assumed.
4. Inspect it: sheets, columns, row counts, missing-value markers, and cross-check any totals.
   Record what you found in [`metadata/data_quality_report.md`](metadata/data_quality_report.md),
   including the problems.
5. Describe its fields in [`metadata/data_dictionary.md`](metadata/data_dictionary.md).
6. If the download fails, do **not** quietly drop it. Record `acquisition.state: blocked` with the
   exact error text and manual download instructions.

## Governance

- No real patient records. No identifiable personal information.
- No unsupported clinical assumptions — unresolved items stay unresolved and cite an `OQ-*` entry
  in `data-pipeline/rules/common/open_questions.yaml`.
- Source provenance is preserved for everything.
- PulseReach makes **no claim of regulatory compliance** (ADHICS, Responsible AI Standard, PDPL or
  otherwise). Open data licences still require Legal review per Responsible AI Standard §3.2.1.5.
- Data residency is unresolved (`OQ-GOV-DATA-RESIDENCY`): the repo targets GCP Cloud Run while the
  Responsible AI Standard §3.1.4.5.1 requires UAE-resident compute and storage. Do not process real
  patient data in any environment until that is settled.
