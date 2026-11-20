# BE-33 — Geospatial Population Intelligence: Repository Audit

Audit of the repository at commit `aefbfc2` ("User auth") before BE-33 was implemented. All
patient data is synthetic. This is an engineering review, not a clinical or epidemiological
validation.

## 1. What exists

| Area | Location | Finding |
|---|---|---|
| Patient geography | `synthetic.patient.region_id` (NOT NULL, FK `official.region`), `district_label` (nullable free text) | Two levels only. `district_label` is chosen by the generator from a fixed per-region list (`_DISTRICTS_BY_REGION`, 13 labels). No address, city, postcode or coordinates. |
| Official regions | `official.region` (3 rows: AD, AIN, DHF) loaded by `official_loader` | Stable ids/codes, `name_en`/`name_ar`. No boundary geometry anywhere in the repository. |
| Facilities | `official.facility` (SDI register, 2 985 usable rows in memory mode) | `region_id`, published `city` label, `source_layer`, `longitude`/`latitude` only when `geo_quality` is `ok`/`swapped_repaired`. No capacity, appointment availability or verified service capability (`facility_service_profile` is explicitly `simulated`). |
| Disease / condition records | — | **None.** No diagnosis, problem-list or condition table exists in `official`, `clinical` or `synthetic`. `official.observation` holds annual SCAD aggregates (by region, some by `disease_type`), which are emirate statistics, not patient diagnoses. |
| Care gaps | `synthetic.care_gap` (rule fact + lifecycle) | Preventive-care gaps produced by the deterministic evaluation engine. **Not diagnoses**; they must never be counted as disease cases. `identified_date` is the evaluation reference date for almost every gap (1 447 of 1 451), so care-gap *trends* have no history yet. |
| Screening events | `synthetic.ifhas_screening`, `synthetic.well_child_visit` | Dated `performed_date`; usable for a screening-completion count. |
| Follow-up | `synthetic.care_gap_follow_up_event`, `workflow_status_event` (append-only), memory overlays in `followup_repo.py` | `closed_completed` gaps carry `closed_date`; usable for follow-up completion rates. |
| Population insights | `GET /api/v1/dashboard/summary`, `GET /api/v1/insights/population` (`read_repo.py`) | Region-level care-gap counts over the caller's patient scope; no disease, trend, geography hierarchy or alerting. Reused (not duplicated): BE-33 adds disease/geography surveillance alongside it. |
| Organization isolation / RBAC | `app/core/permissions.py`, `app/core/auth.py`, `identity.patient_organization` | Patient-anchored tenancy; `require(...)` on every route (meta-test in `test_rbac.py`); `record_event` for audit. Reused as-is; new permissions added to the central matrix. |
| Background work / caching | — | No scheduler, queue, worker or cache. `lru_cache` holds the in-memory dataset. FastAPI `BackgroundTasks` is available without new dependencies. |
| Stores | PostgreSQL (`DATA_SOURCE=db`), in-process dataset + SQLite identity store (`DATA_SOURCE=memory`) | Every feature must work in both modes; identity uses its own `MetaData` + an SQLite engine in memory mode — a pattern reusable for new persistent tables. |
| Migrations | `0001`–`0011`, frozen static DDL, refusing destructive downgrades | New work must be additive (`0012`). Reseeding deletes and recreates a synthetic run, so new non-synthetic tables must not hold FKs into `synthetic.*`. |

## 2. Is the dataset sufficient for real trend calculations?

**No, not before BE-33.** There were no time-stamped disease/condition records at all, so
prevalence, new-diagnosis counts and disease trends could not be computed without fabrication.
Geography was limited to region + a synthetic local label, with no coordinates or boundaries.

Missing data dependencies (reported explicitly):

1. **Condition/diagnosis records** with diagnosis date, recording timestamp and status — added as
   `synthetic.condition_record` (clearly synthetic, deterministic, see §4).
2. **Geographic boundaries** for any level — not available; not fabricated. APIs return
   `boundary: null`. The schema has `boundary_ref` / `boundary_source` columns for when real
   boundary data is obtained.
3. **Patient coordinates / addresses** — not available (and never to be exposed). Distance to the
   nearest facility therefore cannot be computed and is reported as unavailable.
4. **Historical population denominators** — only the current registered population exists;
   previous-period prevalence uses the current denominator and says so (`denominator_basis`).
5. **Facility-to-local-area link** — no boundaries; only the published SDI `city` label. A
   label-based association (exact normalized match within the same region, plus a small,
   documented transliteration crosswalk) is the only defensible basis. Unmatched areas
   report facility coverage as unknown, never zero.
6. **Facility capacity / appointment availability / verified services** — not published; not
   invented.
7. **Care-gap history** — care gaps exist only for one evaluation date; care-gap burden trends
   return `INSUFFICIENT_DATA` until further evaluation runs exist.

## 3. Reuse vs. new

| Reused | New |
|---|---|
| `official.region`, `official.facility`, `synthetic.patient` (`region_id`, `district_label`), care gaps, evaluations, screenings, follow-up events | `synthetic.condition_record` (patient-owned, reseedable) |
| Permission matrix, `require`, `Principal`, `record_event`, i18n catalog, error contract | `population` schema (own `MetaData`, PostgreSQL in db mode / SQLite in memory mode): `geo_area`, `aggregation_run`, `threshold_config`, `population_alert`, `population_alert_event` |
| Synthetic generator (unchanged random stream for existing records) | Separate deterministic condition generator with labelled scenarios |
| `PostgresReadRepository._latest_runs`, cached in-memory dataset and facilities | Aggregation engine (database-side `GROUP BY` in PostgreSQL), trend/hotspot/alert logic, snapshot persistence, `/api/v1/population/*` |

Geographic hierarchy decision (no duplicate location model): `country` (AE) → `state`
(Abu Dhabi Emirate, ISO 3166-2 `AE-AZ`) → `district` (the three official regions) → `city`
(published SDI facility city labels; facility-only) → `local_area` (patient `district_label`).
Area rows are derived from those existing sources, not typed in.

## 4. Gaps that BE-33 closes and what stays open

Closed: condition records, area hierarchy with stable ids, deterministic aggregation, trends,
threshold-based hotspots, persisted alerts with lifecycle and history, snapshot-based refresh,
privacy suppression, RBAC, documentation.

Open (documented limitations): real boundaries, patient coordinates / facility distance,
historical denominators, statistical significance testing and spatial clustering, push updates
(SSE/WebSockets), verified facility capability.

## 5. Verification scope

Focused offline tests cover the new engine, API, RBAC and privacy, and the full offline suite was
rerun. Targeted live PostgreSQL tests for migration `0012` and the database-side aggregation path
(parity with memory mode) are written but have not completed a run, and the full live PostgreSQL
regression suite was not rerun (degraded local Podman networking): NEEDS VERIFICATION, see
`geospatial-population-intelligence.md` §12.

Not implemented and not claimed: `docs/backend-architecture.md` does not exist (nothing to update);
the committed `data/synthetic/SYNTH-RUN-0001/data_card.md` was not regenerated (the generator now
writes a `condition_record` row when it is).
