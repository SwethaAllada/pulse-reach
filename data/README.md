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

Two files. Both are official Abu Dhabi government aggregate statistics, both verified by
download, both left exactly as served:

| File | Source | Reference period | Size |
|---|---|---|---|
| `raw/scad/scad_health_statistics_2022_en.xlsx` | Statistics Centre – Abu Dhabi | 2022 | 1.17 MB |
| `raw/scad/scad_birth_statistics_2024_en.xlsx` | Statistics Centre – Abu Dhabi | 2024 | 1.18 MB |

Nothing else has been downloaded. In particular there is **no** local copy of the IFHAS or
Well-Child Visit standards — their content was transcribed into `data-pipeline/rules/` during an
earlier phase, but `doh.gov.ae` is not reachable from the current network, so the PDFs themselves
are not held. `processed/`, `synthetic/` and `reference/doh_standards/` are empty.

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

## Attribution requirement

SCAD's terms of use permit reproduction **with attribution**. Any figure, table or chart derived
from the SCAD files must carry:

> Source: Statistics Centre – Abu Dhabi; *year of publication, name of the statistical product,
> reference period, page(s)*.

This applies to the UI, the submission and any slide. It is a licence condition, not a courtesy.

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
