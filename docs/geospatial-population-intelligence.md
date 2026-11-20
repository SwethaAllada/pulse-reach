# PulseReach — Geospatial Population Intelligence & Disease Surveillance (BE-33)

Backend for the Population Health Manager dashboard: disease and preventive-care metrics by
geography, period comparisons, threshold-based hotspots and persisted alerts. All patient data is
synthetic; nothing here is clinically or epidemiologically validated. Audit and data-gap analysis:
`geospatial-population-intelligence-audit.md`.

Every number is computed by the backend from stored records (`synthetic.condition_record`, care
gaps, evaluations, screenings, follow-ups, the official SDI facility register). No LLM computes or
phrases any metric, hotspot or alert. The frontend only renders the responses.

## 1. Code map

| Concern | Location |
|---|---|
| Condition records (model, migration) | `app/models/synthetic.py` `ConditionRecord`, `migrations/versions/0012_*.py` |
| `population` schema (areas, runs, thresholds, alerts, alert history) | `app/models/population.py`, migration `0012` |
| Synthetic condition generator + scenarios | `app/services/synthetic_generator/conditions.py` |
| Vocabularies (conditions, periods, cohorts) | `app/services/population/vocabulary.py` |
| Thresholds (validated, per organization) | `app/services/population/config.py` |
| Geography hierarchy and facility association | `app/services/population/geography.py` |
| Grouped input counts (PostgreSQL `GROUP BY` / memory) | `app/services/population/facts.py` |
| Metrics, trends, hotspots, alert candidates (pure) | `app/services/population/engine.py` |
| Privacy suppression | `app/services/population/privacy.py` |
| Alert de-duplication and lifecycle | `app/services/population/alerts.py` |
| Refresh, snapshots, staleness, config | `app/services/population/service.py`, `store.py` |
| Scheduled refresh CLI | `python -m app.services.population refresh` |
| API | `app/api/population.py`, `app/schemas/population.py`, `app/services/population/views.py` |
| Tests | `tests/test_population_engine.py`, `tests/test_population_api.py`, `tests/test_population_live_pg.py` |

## 2. Geographic model

| Level | Id | Source | Population metrics |
|---|---|---|---|
| country | `AE` | ISO 3166 | yes |
| state | `AE-AZ` (Abu Dhabi Emirate) | ISO 3166-2 | yes |
| district | `AE-AZ-AD`, `AE-AZ-AIN`, `AE-AZ-DHF` | `official.region` | yes |
| local area | `AE-AZ-<code>-L-<slug>` | patient `district_label` (synthetic label) | yes |
| city | `AE-AZ-<code>-C-<slug>` | published SDI facility `city` label | no (facility-only) |

- Patients map to a district by `region_id` and to a local area by `district_label`. People
  without a recorded local area are counted at district level and reported as
  `unassigned_local_area_population` / `geographic_completeness`; they are never placed in a guessed
  area.
- Areas are persisted in `population.geo_area` (stable ids, `source`, `verification_status`).
  `boundary` and `reference_point` are always `null`: no boundary or reliable area coordinates
  exist, and none are fabricated. `boundary_ref` / `boundary_source` columns are ready for real data.
- Facility association: district = `facility.region_id`; city = published city label; local area =
  the same normalized label in the same region, or one of a small documented transliteration
  crosswalk (Mussafah/MUSAFFAH, Baniyas/BANI YAS, Al Towayya/AL TIWAYYA). Unmatched local areas
  report `association.status = "no_matching_facility_label"` and `care_facilities = null`
  (unknown, never zero). `published_point_extent` is the bounding box of the published facility
  points — not a boundary; it inherits outliers in the register (district extents overlap).
- Distance to the nearest facility is not available (patients have no locations) and is reported
  as such. Capacity, appointments and services are not published and are never invented.

## 3. Metric definitions

| Metric | Definition |
|---|---|
| `population` | Living registered patients of the organization in the area (denominator). |
| `new_cases` | Patients whose earliest recorded diagnosis date of the condition falls in the window. |
| `patients_with_condition` | Patients with an active (not resolved) recorded condition at the window end (undated entries count from first recording). |
| `existing_patients` | Same, at the window start. |
| `prevalence` | `patients_with_condition / population`; `null` with `prevalence_status = "unavailable_no_denominator"` when there is no denominator. `denominator_basis = "current_registered_population"` (no historical denominators exist). |
| `completeness` | Share of patient-condition pairs with a known diagnosis date. |
| `duplicate_records` / `undated_patients` | Data-quality counts; duplicates never add patients. |
| `open_care_gaps`, `patients_with_open_gap` | Preventive-care facts from the evaluation engine — never disease cases. |
| `preventive_coverage` | In-scope patients without an open gap / in-scope patients (in scope = ≥ 1 evaluation `eligible`/`due`/`overdue`/`upcoming`/`completed`). |
| `screening_completions` | Completed IFHAS screenings + attended well-child visits by `performed_date`. |
| `follow_up_completion_rate` | Gaps closed `closed_completed` in the window / gaps open at some time in the window (superseded/suppressed excluded). |
| `care_facilities` | SDI hospitals, health centres and clinics associated with the area. |

De-duplication (same in SQL and memory): `entered_in_error` entries are dropped; per patient and
condition, onset = earliest known diagnosis date, resolved = latest resolution only when every entry
is resolved. Cohorts: `all`, `adults`, `children` (age at the as-of date, 18 years), `female`, `male`.

## 4. Periods and trends

- Periods: `7d`, `30d`, `90d`, `6m` (182 days), `12m` (365 days). Current = `(T - L, T]`, previous =
  `(T - 2L, T - L]` — equal, adjacent, non-overlapping windows.
- **As-of date** = the dataset reference date or the newest recorded event, whichever is later.
  **Complete-through date** `T` = as-of − `reporting_delay_days` (default 14) for disease counts,
  so recent, not-yet-reported diagnoses cannot fake a decrease. Care and follow-up windows end at
  the as-of date (operational records have no reporting delay).
- History completeness: an area's condition history starts at its earliest recorded entry; for an
  aggregated area it is the *latest* start among its constituents (conservative). A window whose
  previous period begins before that start is `history_complete = false`.
- Classification (`classify_trend`, thresholds `trend.*`):
  - `INSUFFICIENT_DATA` if population < `min_population` (20), history incomplete, completeness <
    `min_completeness` (0.8) or fewer than `min_trend_cases` (3) cases across both periods;
  - `INCREASING` if change ≥ `min_absolute_change` (2) and (previous = 0 or change ≥
    `stable_band_percentage` 20 %); `DECREASING` symmetric (previous > 0); otherwise `STABLE`.
  - Percentage change is `null` when the previous period is 0. An increase is never labelled an
    outbreak.

## 5. Hotspots (threshold rules, explainable)

`classify_hotspot` on the comparison period (`hotspot.comparison_period`, default `90d`, cohort
`all`):

1. `INSUFFICIENT_DATA` — population < `min_population` (20), history incomplete, or completeness <
   `min_completeness` (0.8).
2. `NO_ALERT` — new cases < `min_cases` (5), increase < `min_absolute_increase` (3), or (previous > 0
   and) increase < `min_percentage_increase` (25 %). With previous = 0 only the absolute rules apply
   (`previous_period_zero_absolute_rule`).
3. `WATCH`, escalated to the highest tier met: `MODERATE` (+5 and +50 %), `HIGH` (+8, +100 %),
   `CRITICAL` (+12, +200 %).

Each hotspot returns `reason_codes`, `supporting_metrics`, `thresholds`, `comparison_period` and
window dates, `detected_at`, `data_freshness_at`, `method: "threshold_rules"`,
`statistical_significance: "not_assessed"` and a notice that it is not a confirmed outbreak. No
statistical test or spatial clustering is implemented (future milestone).

## 6. Alerts

Raised for `district` and `local_area` areas (cohort `all`) by each aggregation run:

| Category | Condition (defaults, configurable) | Severity |
|---|---|---|
| `case_increase` | hotspot ≥ `WATCH` | the hotspot class |
| `disease_burden` | active patients ≥ `burden_min_patients[c]` (30) and population ≥ 20 | MODERATE (HIGH at 2×) |
| `prevalence` | prevalence ≥ `prevalence_max[c]` (diabetes 20 %, hypertension 30 %, dyslipidaemia 30 %, asthma 15 %) | MODERATE (HIGH at 1.5×) |
| `preventive_coverage_low` | coverage < `preventive_coverage_target` (30 %), ≥ 20 in scope | MODERATE (HIGH below half) |
| `follow_up_completion_decline` | rate fell ≥ 10 points over `follow_up_period`, ≥ 10 gaps in both periods | MODERATE |
| `facility_coverage_insufficient` | associated care facilities < `min_care_facilities` (10), population ≥ 20 | MODERATE (HIGH at 0) |

Defaults are demonstration values for the synthetic dataset, not DoH or clinical targets.

- Fields: id, organization, area, category, condition, severity, title/explanation (catalog keys,
  rendered in `en`/`ar`), supporting metrics, thresholds, period, first/last detection,
  data freshness, status, `condition_active`, `occurrence_count`, acknowledged/investigating/closed
  actor and time, `allowed_transitions`, full `history`.
- **De-duplication**: one active alert per `(organization, category|area|condition|period)`
  (unique partial index). Repeated runs update it (`occurrence_count`, `updated` event when
  severity/metrics change). When a run no longer detects it, `condition_active = false`
  (`condition_cleared`); status is left to people. After `RESOLVED`/`DISMISSED`, the same
  condition raises a new alert only after it cleared and recurred, or if severity escalates.
- **Lifecycle**: `NEW → ACKNOWLEDGED | INVESTIGATING | RESOLVED | DISMISSED`;
  `ACKNOWLEDGED → INVESTIGATING | RESOLVED | DISMISSED`; `INVESTIGATING → RESOLVED | DISMISSED`;
  terminal states are final. Other transitions → `409`. The actor is the authenticated user;
  history is append-only (`population.population_alert_event`, PostgreSQL triggers); every change
  (and refusal) writes an `identity.audit_event` (`population_alert.status_changed`) without the
  note text.
- Alerts never contain patient identifiers and never contact anyone.

## 7. Aggregation refresh and live updates

- A run computes one organization's snapshot (all areas × conditions × cohorts × periods, series,
  care, facilities) and persists it in `population.aggregation_run.snapshot`, syncing alerts in the
  same transaction. Requests read the latest snapshot; they never recompute it except the first
  time (`trigger = on_demand`).
- **Staleness**: a data-version fingerprint (condition-record, follow-up and workflow counts and
  latest timestamps, care-gap closures, patient ownership, threshold version) is re-checked at most
  every `POPULATION_FRESHNESS_CHECK_SECONDS` (15). If it changed, or the snapshot is older than
  `POPULATION_MAX_SNAPSHOT_AGE_SECONDS` (3600), the stale snapshot is served with
  `aggregation.stale = true` and a refresh is scheduled after the response (FastAPI background
  task). Threshold changes refresh immediately.
- **Concurrency**: per-organization in-process lock plus the unique index "one `running` run per
  organization" across workers; concurrent requests get `409` (manual) or are skipped
  (background). A `running` row older than `POPULATION_REFRESH_TIMEOUT_SECONDS` (600) is marked
  `failed`/`abandoned`. The latest `POPULATION_RUNS_RETAINED` (10) runs are kept.
- **Scheduled**: `python -m app.services.population refresh [--org <id>]` (cron / Cloud Scheduler
  job). No Redis/Kafka/queue: the persisted snapshot is the cache and keys are organization ids.
- **Polling** (`GET /population/updates` → `recommended_poll_seconds`): map 60 s, alerts 30 s,
  trends 300 s, updates 30 s. SSE/WebSockets are a later enhancement.
- Measured locally (memory mode, 550 patients): ~0.1 s per organization run; ~1.8 MB snapshot.

## 8. API (`/api/v1/population`)

See `api-contracts.md` §1 for the table. All responses share an envelope: `is_synthetic`,
`as_of`, `complete_through`, `latest_data_at`, `aggregation` (run, `stale`, `refresh_scheduled`),
`privacy`, `disclaimer`. Areas carry `name` localized by `?lang=` / user preference.

| Endpoint | Highlights |
|---|---|
| `GET /map` | `condition`, `period` (90d), `geography` (local_area), `metric` (`population`, `new_cases`, `patients_with_condition`, `prevalence`, `trend`, `hotspot`, `open_care_gaps`, `preventive_coverage`, `care_facilities`), `cohort`, `bbox=minLon,minLat,maxLon,maxLat` (intersects `published_point_extent`; areas without points are excluded and counted in `excluded_without_geometry`), `sort`, `limit`/`offset`. Disease metrics without `condition` → 422. |
| `GET /trends` | `condition` (required), `area_id` or `geography` (district), optional `period`, `cohort`; per area all period comparisons + 12 complete calendar months (`complete` flag per month). |
| `GET /hotspots` | `condition`, `period` (re-evaluated with the configured rules), `geography`, `min_classification` (WATCH); evidence per hotspot. |
| `GET /areas/{area_id}` | ancestors/children, population by cohort, every condition (current, all periods, series, hotspot, data quality), active alerts, facilities, preventive care, data quality. Unknown area → 404. Never patient records. |
| `GET /alerts`, `GET /alerts/{id}`, `PATCH /alerts/{id}` | filters `condition`, `area_id`, `severity`, `status`, `category`, `active_only`, `since`, `until`; detail with history; `PATCH {status, note?}`. Other organizations' alerts → 404. |
| `GET /summary` | represented population, conditions monitored, areas monitored, areas with increasing recorded cases (+ list), hotspots by class, active alerts by severity, state-level preventive care, latest aggregation time. |
| `GET /updates` | aggregation status, last aggregation, latest aggregated data time, `data_changed_since_aggregation`, `staleness_seconds`, dataset/version ids, poll intervals. Does not compute a snapshot. |
| `POST /refresh` | synchronous manual run (409 while one runs); audited. |
| `GET /config`, `PATCH /config` | organization thresholds (full validated document, `extra` fields rejected); PATCH audited and refreshes. |

## 9. Permissions

| Permission | ADMIN | PHM | COORD | CLIN | PATIENT |
|---|:-:|:-:|:-:|:-:|:-:|
| `population.read` (map, trends, hotspots, areas, summary, config read) | | ✓ | | ✓ | |
| `population.alerts.read` | | ✓ | | ✓ | |
| `population.alerts.manage` (PATCH alerts) | | ✓ | | | |
| `population.refresh` (POST refresh, `/updates`) | ✓ | ✓ | | | |
| `population.configure` (PATCH config, config read) | ✓ | ✓ | | | |

- SYSTEM_ADMIN manages aggregation operations and thresholds but sees no population data.
- CARE_COORDINATOR keeps the existing scoped `insights.read` aggregates over assigned patients only;
  organization-wide surveillance is not granted. PATIENT has no access.
- Scope is the authenticated session's organization (`*` only in `AUTH_MODE=legacy`); request
  parameters never select an organization. Checks use the central permission matrix.

## 10. Privacy safeguards

- No patient ids, names, contact details, addresses or coordinates exist in the snapshot or any
  population response (tested).
- Small-cell suppression (`POPULATION_MIN_CELL_SIZE`, default 5, system-level): primary
  suppression of counts 1…k−1 and of areas with population < k; cohort complement suppression;
  complementary suppression so a parent minus visible siblings (including the unknown "no local
  area" remainder) never reveals a small cell; derived values (prevalence, change, coverage)
  suppressed with their inputs; alert explanation numbers below k shown as `<k`. Suppressed fields
  are listed in `suppressed`. Rules are deterministic, so repeated filtering returns the same
  pattern; filters only select predefined areas/cohorts/periods (no free-form groups).
- Residual risks: differences between nested time windows (e.g. 30-day vs 90-day) and between
  monthly series and windows are not cross-suppressed; trend direction and hotspot class remain
  visible for suppressed cells.

## 11. Synthetic demonstration scenarios

Generated deterministically from the run seed on a separate random stream (existing records are
unchanged) — see `synthetic_generator/conditions.py` and `data/metadata/synthetic_data_spec.md`:

| # | Scenario | Where | Source |
|---|---|---|---|
| 1 | Increasing type 2 diabetes | Mussafah | `BE33-S1` records |
| 2 | Stable hypertension | Khalifa City | `BE33-S2` records |
| 3 | Decreasing hypertension | Al Bateen | `BE33-S3` records |
| 4 | High preventive-care gaps | e.g. Baniyas, Al Muwaiji, Zakhir | real evaluation-engine care gaps |
| 5 | Limited facility coverage | Zakhir (9 care facilities) | real SDI register |
| 6 | Insufficient history | Al Jimi (record feed starts 50 days before the reference date) | `BE33-S6` records |
| 7 | Missing local area | 12 patients (`idx ≥ 60`, `idx % 41 == 0`) | cleared `district_label` |

Region-3 local areas (8–14 people) additionally demonstrate small-population handling.

## 12. Verification and limitations

- Offline (`.venv/bin/python -m pytest -q -p no:cacheprovider`):
  - `tests/test_population_engine.py` (40) and `tests/test_population_api.py` (45): trends,
    hotspots, aggregation definitions, de-duplication, denominators, seeded scenarios, privacy,
    alert sync/lifecycle, RBAC matrix, organization isolation, no patient data, filters, invalid
    inputs, empty results, staleness, concurrent refresh, configuration, legacy mode.
  - The existing RBAC meta-tests cover the new routes (every route declares a permission and
    returns `401` without a token).
  - Full offline suite after the change: 709 passed, 119 skipped (PostgreSQL), 1 failure caused by
    the schema test's own table list, since fixed; the affected suites were rerun green.
- Live PostgreSQL (`TEST_DATABASE_URL`): `tests/test_population_live_pg.py` is written — migration
  `0012` ↔ models, condition records seeded and reconciled, database-side aggregation identical to
  memory mode (facts and full snapshot), db-mode API with isolation and persisted alert lifecycle,
  append-only alert history, one-running-run index, reseed without duplicate alerts, refused
  downgrade. `tests/test_identity_live_pg.py` was adjusted for head `0012`.
- **NEEDS VERIFICATION (live PostgreSQL):** the local Podman port forward was degraded (~250 ms per
  round trip). One run of the targeted live module was stopped after ~24 minutes, during the reseed
  test, so no pass/fail result exists. It had applied migration `0012` to a fresh database, seeded
  condition records and run the PostgreSQL aggregation for both demo organizations (alerts and
  history persisted). Neither that module nor the full live regression suite has completed; run
  both on a healthy PostgreSQL setup before relying on `DATA_SOURCE=db`.
- Limitations: no boundaries or patient locations (no choropleth geometry, no distance); current
  denominators for historical prevalence; facility association by label only; threshold rules
  without statistical testing; polling only; synthetic, illustrative condition rates.
