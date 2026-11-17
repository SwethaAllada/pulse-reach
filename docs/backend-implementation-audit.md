# PulseReach — Backend Implementation Audit

**Audit date:** 2026-11-17 · **Commit audited:** `e23e37e` (branch `main`, working tree clean before and after the audit) · **Type:** read-only audit; the only file created is this report.

**Evidence labels used throughout**
- **[V]** verified by reading code and/or running it in this audit.
- **[A]** assumption or inference from code/docs.
- **[U]** unverified — could not be checked here (stated with the reason).

---

## 1. Executive Summary

**Headline:** the backend contains a strong, well-tested *foundation* (three-schema PostgreSQL design, a careful official-data loader, a strict YAML clinical-rule parser, a deterministic evaluation engine, a reproducible synthetic generator). But the **running API is not backed by the database at all**, and the **operational workflow half of the product (follow-up, appointments, referrals, outreach events, care-gap detail) has no API**. It is a read-only demo API over an in-memory regeneration of the synthetic dataset.

| Area | Status |
|---|---|
| Schemas / migrations (0001–0007) | Implemented; render cleanly to SQL offline (up and down). Live-DB behaviour **[U]** (see §12) |
| Official data loader | Implemented, idempotent by design, extensively tested (live tests skipped here **[U]**) |
| Clinical rule parsing + DB loader | Implemented; strict Boolean validation **[V]** |
| Deterministic evaluation engine | Implemented, pure, 12 tests; **2 correctness defects + 3 hard-coded-threshold deviations from YAML** |
| Synthetic generator | Implemented, deterministic **[V]**; **journey coverage is thin** (1 appointment, 1 referral, 0 component results) |
| `/api/v1` | 11 working GET/POST routes (13 incl. `/health*`); **none reads PostgreSQL** |
| AI explanation | Deterministic template only; LLM adapter exists but is **never wired** (`llm_provider=None`) |
| Outreach preview | Works, but **gates only on contact consent** — it will "allow" a message for a rule that does not exist |
| Follow-up / appointments / referrals / care-gap detail / facility detail | **Not implemented** |

**Overall backend readiness (MVP):** ~55 %. Frontend can integrate **now** against the existing read endpoints for Journeys 1, 3 (partly), 5; Journeys 2, 4 need new endpoints/fields.

**Safety headline (good):** the clinical-safety invariants requested in the brief are genuinely enforced in code and tests — unknown history → `unknown` (never due/overdue), unresolved/review-flagged rules → `requires_clinical_review`, `overdue` is never emitted (0 of 29,700 evaluations **[V]**), no LLM touches a decision, outreach is simulated-only.

**Safety headline (bad):** the outreach preview, a cancelled-referral → `completed` mapping, and a hard-coded constant "priority score" can each present misleading information to a user. See §15.

---

## 2. Repository and Backend Architecture Overview

```
backend/app/
  main.py                    FastAPI app, CORS (GET/POST/OPTIONS), mounts health + v1 routers
  api/health.py              GET /health, GET /health/db
  api/v1.py   (874 lines)    ALL v1 routes + in-memory index + facility derivation + request→fact mapping
  schemas/v1.py              Pydantic response/request models
  core/config.py             pydantic-settings (DATABASE_URL SecretStr, pool, rules_dir, data_dir)
  db/session.py              lazy engine, naming convention, SCHEMAS
  db/init.py                 alembic upgrade wrapper
  models/{official,clinical,synthetic}.py   SQLAlchemy 2.x models (402 / 561 / 1617 lines)
  services/clinical_loader/  parse.py (1009) + load.py (361)  YAML → clinical.* (idempotent, hash/version guards)
  services/official_loader/  parse.py (704) + load.py (443)   SCAD/SDI → official.* (advisory lock, quarantine)
  services/evaluation/engine.py (956)   deterministic rule engine (pure functions over dataclasses)
  services/explanation/service.py (415) explanation + outreach-preview service
  services/synthetic_generator/         generator.py (1249) + load.py (173) + data-card writer
backend/migrations/versions/0001…0007
data-pipeline/rule_loader/   (second, independent YAML loader/validator) + rules/*.yaml + 122 tests
```

**Request path today [V]:** `request → v1.py → lru_cache'd in-memory objects`. `_get_bundle()` re-parses the YAML (`v1.py:87-89`); `_get_dataset()` regenerates 550 patients with `seed=20261116` (`v1.py:97-99`); `_get_facilities()` re-parses raw GeoJSON (`v1.py:162-225`). **No route opens a DB session.** `get_engine()` is used only by `/health/db`.

**Architectural observations**
1. **Business logic in the router.** `v1.py` contains the DB-row→engine-fact mapping (`_build_patient_context`, 406-507), facility "usable" policy (173-178) and a simulated service overlay (190-191), and outreach/explanation assembly. These belong in services. **[V]**
2. **Two YAML parsers.** `data-pipeline/rule_loader` (122 tests) and `backend/app/services/clinical_loader/parse.py` both validate the same YAML independently. Drift risk; only one is the runtime path (backend). **[V]**
3. **No dependency injection / no sessions.** No `Depends(get_db)`; fine while no route uses the DB, but this is the main structural gap for the MVP workflows (§14).
4. **No logging** anywhere in `backend/app` (`grep logging` = 0 hits). **No auth**, no rate limits, no request-ID. **[V]**
5. **No circular imports found** (service → models only; API → services). **[V]** by import success + test run.
6. **Container build cannot serve `/api/v1`** (see D-9).

---

## 3. Existing Implemented Components

| Component | Evidence | Maturity |
|---|---|---|
| Alembic migrations 0001–0007 | `alembic upgrade head --sql` and `downgrade head:base --sql` both exit 0; 9 + 12 + 18 = 39 `CREATE TABLE` **[V]** | Complete (DB behaviour [U]) |
| Official loader (SCAD + SDI) | `official_loader/load.py`, 60 tests | Complete |
| Clinical YAML parser + DB loader | 54 rules / 249 items / 23 open questions / 8 conditions parsed **[V]** | Complete |
| Evaluation engine | `engine.py`; statuses emitted: eligible, not_eligible, due, upcoming, completed, unknown, insufficient_information, requires_clinical_review (never `overdue`) **[V]** | Functional, 2 defects |
| Synthetic generator + DB loader + data card | deterministic across two runs **[V]** | Functional, thin journeys |
| Explanation service | deterministic fallback; LLM adapter unwired | Partial |
| Outreach preview (simulated) | works; weak gating | Partial |
| `/api/v1` read API | 11 routes | Partial |

---

## 4. Database and Migration Audit

**Schema separation [V]:** `official` 9 tables, `clinical` 12 tables (+3 views), `synthetic` 18 tables (+4 views). Matches `docs/phase-3-database-design.md` decision D16 ("39 tables"). Version table in `public` (D7). ~200 `CHECK` constraints in the rendered SQL.

**Strengths [V from rendered SQL]**
- Database-enforced integrity, not just app code: `ck_*` constraints; generated `refusal_evidence_valid` column with composite FKs; `ck_consent_applies_to IN ('self','child_by_guardian')` and `(applies_to='child_by_guardian') = (guardian_id IS NOT NULL)`; observation-member-dimension triggers; append-only triggers (`reject_append_only_mutation`) on `consent`, `history_availability`, `eligibility_evaluation`, `evaluation_reason`, `evaluation_run`, `care_gap_review`, and six `clinical.*` tables.
- Synthetic reset requires a transaction-local GUC (`pulsereach.allow_synthetic_reset`).
- Views: `official.v_observation_current/leaf`, `v_facility_usable`, `v_indicator_year_shape`, `v_derived_total_additive`; `clinical.v_rule_current/authority/item_effective_authority`; `synthetic.v_consent_current`, `v_history_availability_current`, `v_eligibility_current`, `v_care_gap_effective_priority`.

**Findings**
| # | Finding | Evidence |
|---|---|---|
| DB-1 | **Migration 0007 builds tables from the live ORM models** (`Base.metadata.tables`, `CreateTable(tbl)`) rather than frozen DDL. Any later edit to `models/synthetic.py` silently changes what revision 0007 creates → non-reproducible history, and `alembic check` can never catch that drift. | `0007_…py:17-18, 63-64, 80-86` |
| DB-2 | **Down-migration of 0007 drops tables but is untested for data**; `downgrade base` ends with `DROP SCHEMA` (no `CASCADE`) — acceptable, but rollback on a populated DB is **[U]**. | `down.sql` |
| DB-3 | **No database views/tables are consumed by the API** (`v_consent_current`, `v_eligibility_current`, `v_facility_usable` unused). The API recomputes equivalents in Python. | `v1.py:162-225, 836` |
| DB-4 | `synthetic.care_gap`, `appointment`, `referral` are mutable but have **no status-history/event table**; follow-up recording (Journey 4) needs a place to write. `outreach_event` is the only event log. | design §5.5, §5.6-C |
| DB-5 | `evaluation_run.age_convention = 'unspecified'` is stored while the engine applies *completed-years/months* arithmetic (`engine.py:43-48`). Recorded provenance disagrees with actual behaviour (OQ-COMMON-AGE-CALC / D17-4 still open). | `generator.py:1120`, `engine.py:43` |
| DB-6 | `generation_run.rule_bundle_load_id` defaults to `1` (hard-coded) when generating in memory; aligned only in `_load_with_sa_conn` if a `clinical.rule_load` row exists. | `generator.py:122`, `load.py:51-60` |
| DB-7 | `load_synthetic_dataset(..., reset_existing_run=True)` **deletes the existing run by default** (via the reset GUC). Safe for synthetic data but a surprising default. No CLI exists to load synthetic data into the DB (`__main__` only writes the data card). | `load.py:100-110, 162`; `synthetic_generator/__main__.py` |

**Live behaviour [U]:** I could not execute any PostgreSQL-backed test. No local `psql`; I started a throw-away `postgres:17` container on a separate port, but `docker exec` and host-port connections both hung in this sandbox, so I removed it (an unrelated pre-existing container `pr-recon-pg` was left untouched). Therefore the 84 `live_db` tests, `alembic check`, trigger behaviour, and upgrade/downgrade on a real server are **unverified in this audit**.

**Doc ↔ implementation discrepancies (both directions)**
- `docs/api-contracts.md` says `/health/db` returns `"connected" | "not_configured" | "unreachable"`; code returns `"ok" | "not_configured" | "unavailable"` (`db/session.py:57-62`). *Doc stale.*
- `docs/api-contracts.md` example dashboard status counts (not_eligible 19,518; requires_clinical_review 3,983; eligible 3,691; unknown 772; completed 151; insufficient_information 108; upcoming 26) **do not match what the current generator/engine produce** (18,715 / 4,882 / 3,774 / 524 / 287 / 57 / 10; `due` 1,451 matches). *Doc stale (engine/generator changed after doc was written).* **[V]**
- `docs/architecture.md`, `requirements.md`, `user-journeys.md`, `data-dictionary.md` are 3-line placeholders. *Doc missing.*
- Design doc D6/D7/D11 are still marked "RECOMMENDED — awaiting owner confirmation" although the implementation already assumes them (plain lat/lon, Alembic, append-only evaluations). *Doc behind implementation.*
- The implementation applies decisions that the design doc lists as **OPEN**: D13 (licence-status mapping — API hard-codes "usable" statuses), D12/D14/D17 (see §8). *Implementation ahead of governance.*

---

## 5. Official Data Ingestion Audit

Inspected `official_loader/{parse,load}.py`, 60 + 30 + 33 tests (`test_official_loader.py`, `test_official_integrity.py`, `test_official_schema.py`), `data/processed/facilities/quality_report.json`. Large ingestion **not** re-run (instruction).

| Requirement | Finding |
|---|---|
| Manifest validation / checksums | Manifest sha256 recorded; `source_file.sha256` compared on every run; changed hash for a registered path ⇒ `FatalError` ("raw is immutable") (`load.py:169-171`). **[V code]** |
| Provenance | `source`, `source_file` (role, bytes, retrieved_at, fit_for_use), `loader_version`, `transform_version` stamped on observations/facilities. **[V code]** |
| Idempotency | Source/file rows skipped when identical, hard-fail when edited; observations compared file-by-file (identical ⇒ skip, otherwise `UnitError`, never partial); facilities refuse a second vintage. A test (`test_real_load_is_idempotent_a_rerun_inserts_and_changes_nothing`) asserts a rerun inserts nothing — **skipped here [U]**. |
| Concurrency | `pg_try_advisory_lock(LOCK_KEY)` for the whole run (`load.py:404-407`). **[V code]** |
| Quarantine | Per-unit transaction (`engine.begin()` per indicator unit); failing unit written to `plan.quarantine`, others still load; `status` becomes `INGESTED-WITH-QUARANTINE`. Dry-run parses every real file (test passes **[V]**). |
| Aggregate vs leaf | `row_role`, `v_observation_leaf`, `v_derived_total_additive`; raw `value_marker_raw` kept distinct from numeric `value` (D3 `-`/`:` meaning still OPEN, so markers are preserved not interpreted). **[V code]** |
| Facility coordinates | 5,339 features: ok 5,299 · swapped_repaired 31 · missing_placeholder 6 · out_of_bounds 3; 434 `unidentified`; geo_quality is stored, not silently fixed **[V]** (`quality_report.json`, my re-parse reproduces 5,339 / 5,299 / 31 / 6 / 3 / 4,905 identified). |
| Facility ≠ service/IFHAS inference | DB layer: correct. **API layer violates the spirit** — see D-6/D-7 (simulated service flags emitted next to real facility names). |

**Verdict:** loader is safe to run more than once **by design and by test, but this audit could not execute the live idempotency test** [U].

---

## 6. Clinical Rule Engine Audit (rules, loaders, validation)

**Rules present [V]:** 54 rules = IFHAS 29 (20 screening packages, 5 workflow timing, 4 programme eligibility) + Well-Child 25 (14 visit schedule, 4 developmental tiers, 2 follow-up windows, 2 policies, programme scope/status/timing). Authority: **47 authoritative; 4 verified-but-`requires_clinical_review`** (cervical Pap 25-29, cervical HPV 30-65, liquid biopsy 40-75, lung LDCT 55-75); **3 unresolved** (`IFHAS-PROG-AGE-CEILING`, `WCV-PROG-EFFECTIVE-DATE-TBD`, `WCV-TIMING-DUE-WINDOW`). 249 items (240 verified, 9 unresolved). 23 open questions, all `open`. `clinical_review_status = not_reviewed`. Counts match `docs/api-contracts.md`. ✔

| Check requested | Result |
|---|---|
| 1. All expected rules represented | Yes — 54 in YAML ↔ 54 parsed; DB loader cross-checks (`LV-2` guards) **[V code]**; DB side [U] |
| 2. YAML ↔ DB consistent | Loader has version-downgrade guard, content-sha256, bundle sha256, authority re-verification after load (`load.py:326-346`). Test exists, live part skipped [U] |
| 3. Booleans strictly validated | **Yes** — `_strict_bool` accepts only Python `bool` (`parse.py:169-172`) and is applied to `requires_clinical_review`, `machine_evaluable`, `one_time`, `is_diagnosis`, `is_screening_result_only`, `may_drive_decisions`. The data-pipeline loader tests parametrize `None, "", 0, 1, "true", "false", "True", "False", []` (`test_rule_loader.py:48-90`). **[V]** |
| 4. `"false"` → `True`? | **No** (rejected with `FatalError`). Note: the backend `parse.py` strict-bool path has fewer explicit negative tests than the data-pipeline one — add parity tests (T-12). |
| 5. Missing values | Engine returns `insufficient_information` with `GUARD-MISSING-DOB / -ATTRIBUTE` for missing DOB, sex, `thiqa_member`, `ever_smoked` (when a machine-evaluable condition needs it) **[V]** |
| 6. Age bands / boundaries | Completed-years/months arithmetic, inclusive bounds. **Deviation:** thresholds are hard-coded in the engine instead of read from the rule spec — `age_years < 18` / `> 75` (`engine.py:447-449, 943-945`) and `1 <= age_months <= 72` (`engine.py:632-634, 648, 803, 954`). The YAML has `min_years: 18` and `age_min/age_max` for these rules. Package bands *are* read from the rule (`age_min_years`/`age_max_years`). → YAML is not the sole source of truth for 3 thresholds. |
| 7. Version & source preserved | Every evaluation carries `rule_id`, `rule_version`; `RuleDetailOut` returns `source_name`, `source_version`, `source_reference`, `effective_date_*`; items carry per-item `source_reference`. ✔ |
| 8. Unresolved ⇒ no authoritative result | **Yes** — guard 1 in `_evaluate_single_rule` (`engine.py:392-408`) returns `requires_clinical_review` *before* any age/sex logic. 0 `overdue`, and all 3 unresolved + 4 review-flagged rules are `requires_clinical_review` for **all 550** patients **[V]**. |
| 9. Explainable reasons | `FiredReason` (reason_code, guard_id, item_category/code, detail) → stored in `evaluation_reason`; API exposes code/guard/item but **not `detail` text** or the `input_snapshot` (age, sex, history_state used). Evidence trace is therefore partial (T-9). |
| 10. Missing history / unknown | `not_available` ⇒ `unknown` + `GUARD-MISSING-HISTORY`, **no care gap** (tested; 524 `unknown`, 0 gaps from them) **[V]** |
| 11. Conflicts / open questions | `partial` history or mixed completion statuses ⇒ `requires_clinical_review` (`GUARD-CONFLICTING-RECORDS`). Well-Child past recommended age with no record ⇒ `requires_clinical_review`, never `overdue` (`engine.py:783-792`). ✔ |

**Rule engine defects found (verified by executing the engine):**
- **D-2:** a referral with status `cancelled` or `scheduled` evaluates the follow-up rule as **`completed`** (`engine.py:916-925`; probe: pending→`due`+gap, cancelled→`completed`, scheduled→`completed`). Only `status == 'completed'` (or a documented completion date) should produce `completed`.
- **D-3:** engine hard-codes age/month thresholds (above).
- **Design note:** for `history_state == 'available'` and no matching screening, the engine emits `due` + `no_documented_screening` gap. History availability is per-*pathway*, not per-package, so "available" is coarse evidence that *this particular package* was never done. This is defensible as the documented rule but is the single largest clinical-interpretation risk; it should be signed off (see §19).

---

## 7. Synthetic Data Generation Audit

**Reproducibility [V]:** two consecutive in-process runs with `seed=20261116, n=550` are identical for patients, evaluations and care gaps. Seeded `random.Random`; fixed `reference_date 2026-11-16`; IDs `SYNTH-<CODE>-n`; names end `(synthetic)`; Emirates IDs `SYNTH-EID-…`; e-mail `@example.invalid`.

**Provenance [V]:** `generation_run` stores `generator_version 0.1.0`, `spec_version 2.5.0`, `generation_seed`, `generator_commit` (**None when the working tree is dirty**, `git_commit_if_clean`), `parameters`, `rule_bundle_load_id`, `population_profile = labelled_alternative`, `clinically_validated = False`, data-card path. Data card + `demo_patients_50.json` fixture (50 patients, 137 care gaps) present. `data/synthetic/SYNTH-RUN-0001/data_card.md` row counts match what the generator now produces (e.g. evaluation_reason 10,413; ifhas 96; care_gap 1,451). ✔

**What the dataset contains [V]** — 550 patients (411 adults / 139 children), 139 guardians, **9 consents**, history rows (ifhas available 319 / not_available 54 / partial 38; well_child available 116 / not_available 19 / partial 4), 96 IFHAS screenings (94 complete, 2 partial), 5 Well-Child visits (4 attended, 1 not_attended), **0 component results**, 4 assessments, **1 referral (pending)**, **1 appointment (scheduled)**, 1 care-gap review, 4 outreach events.

**Gaps relative to the requested journey archetypes**

| Archetype | Present? | Evidence |
|---|---|---|
| Eligible for a supported programme | ✅ many | e.g. `SYNTH-PAT-000001` (45 y Thiqa female) |
| Not eligible under a supported rule | ✅ many | e.g. non-Thiqa / out-of-band patients |
| Documented care gap | ✅ 385 patients | 1,451 gaps |
| Incomplete screening history | ✅ | `partial` 42 patients, `not_available` 73 patient-pathways; e.g. `SYNTH-PAT-000030`, `-000033` |
| Evaluation blocked | ✅ | 4,882 `requires_clinical_review`, 57 `insufficient_information` (`-000005`, `-000006`) |
| Requires clinical review | ✅ | every patient (7 flagged rules) |
| **Follow-up in progress** | ⚠️ **1 example only** | appointment `SYNTH-APT-000001` for `SYNTH-PAT-000001`; 1 pending referral (`-000009`); 4 outreach events. No contact attempts / outcomes / notes |
| **Documented completion** | ⚠️ thin | 94 complete IFHAS screenings give `completed` evaluations, but **no appointment/referral that closes a gap**, and **0 `closed_completed` care gaps**; only 1 `closed_refused` gap |

**Other findings**
- **Consent coverage is tiny:** 545 of 550 patients have no `contact` consent (by design, D18 "absence ≠ granted"), so almost every outreach preview is blocked as `contact_consent_absent`. Good for safety, poor for demo — need ~30–50 granted-contact patients with open gaps.
- **Priority score is a constant:** every open gap for an AI-consenting patient gets `priority_score = 0.78`, `scored_by_model_version = "pulsereach-priority-0.1.0"` (`generator.py:913-919`). No such model exists. It is exposed via `CareGapOut.priority_score`. This is a fabricated model attribution (see D-5).
- **Facility link is not meaningful:** `facility_service_profile` has 3 simulated profiles (`facility_id` 1–3); the API facility list assigns `facility_id` by enumeration over 2,985 real facilities, so `registered_profile_id` cannot be joined to a facility in the API.
- Referential integrity is enforced by the schema; generator output → live DB load test is skipped here [U].

---

## 8. Evaluation Engine Audit

Pure, side-effect-free; 54 rules × 550 patients = 29,700 evaluations in ~0.5 s. 12 engine tests + generator/api tests exercise the guards.

| Invariant from the brief | Verdict |
|---|---|
| Programme eligibility ≠ preventive-care eligibility ≠ care gap | ✅ distinct rule types (`programme_eligibility` / `screening_package` / gap facts); gaps only created from package/visit/workflow logic |
| Elevated risk ≠ eligibility/gap | ✅ no risk input exists in the engine |
| Missing history never ⇒ not done / overdue | ✅ `unknown`, no gap |
| Unresolved rule ⇒ no authoritative output | ✅ |
| Review-flagged rules blocked | ✅ |
| Deterministic, no LLM | ✅ (engine imports nothing ML) |
| Traceability (id, version, reasons) | ✅ mostly; `detail`/`input_snapshot` not exposed through API |
| Refusal ≠ absence ≠ withdrawal | ✅ for refusal evidence (documented **and** signed; guardian for child) — provisional per D2; ⚠️ see D-4 for the contact-consent selection |
| Engine reads YAML thresholds | ⚠️ not for 18 / 75 / 1–72 (D-3) |
| `age_convention` recorded | ⚠️ "unspecified" vs completed-years (DB-5) |
| Item-level unresolved guard on IFHAS packages | Not exercised today: **no IFHAS package currently has unverified items** **[V]**, but `item_reasons` are computed and discarded for `screening_package` (`engine.py:412-422` used only in `visit_schedule`). Latent gap. |

**Clinical-decision dependencies baked into code (not silently resolved elsewhere):** age ceiling >75 ⇒ review (OQ-IFHAS-AGE-CEILING); Well-Child past recommended month ⇒ review (OQ-WCV-DUE-WINDOW); Well-Child `eligible` even though effective date is TBD (WCV-PROG-EFFECTIVE-DATE-TBD is separately flagged unresolved).

---

## 9. API Endpoint Inventory

All verified by TestClient probing and `/openapi.json` **[V]**. DB tables used: **none** — source is in-memory data from YAML + generator.

| # | Capability (brief §F) | Method & path | Request | Response | Validation / errors | Tests | Works? |
|---|---|---|---|---|---|---|---|
| – | Liveness | `GET /health` | – | `{status}` | – | test_db | ✅ |
| – | DB health | `GET /health/db` | – | `{status, database}` 503 if down | – | test_db | ✅ |
| 1 | Dashboard | `GET /api/v1/dashboard/summary` | – | `DashboardSummaryOut` | – | test_api_v1 | ✅ (no programme breakdown, no review/unknown *patient* counts, only evaluation-row counts) |
| 2 | People list | `GET /api/v1/patients` | `limit 1–200, offset, sex, region_id 1–3, pathway` | `PaginatedPatientsOut` | 422 on bad enums | yes | ⚠️ **no search, no sort, no status filters**; unknown query params (`?search=`) silently ignored (200) |
| 3 | Profile | `GET /api/v1/patients/{id}` | – | `PatientSummaryOut` | 404 | yes | ⚠️ demographics only; **no consents, no screening/visit history, no appointments/referrals** (engine context has them but not returned) |
| 4 | History | — | — | — | — | — | ❌ not exposed (`ifhas_screening`, `well_child_visit`, `component_result` unreachable) |
| 5/6/7 | Evaluations (IFHAS + WC), evidence | `GET /api/v1/patients/{id}/evaluations` | – | `PatientEvaluationsOut` (all 54 rules, reasons, gaps) | 404 | yes | ✅ (no `detail`, no `input_snapshot`) |
| 5/6 | Re-evaluate | `POST /api/v1/evaluations` | `{patient_id, look_ahead_days 0–365}` | `PatientEvaluationsOut` | 404 / 422 | yes | ✅ (ids `SYNTH-EVL-…` regenerated per call — **not persisted**, not stable) |
| 9 | Rules list/detail | `GET /api/v1/rules`, `GET /api/v1/rules/{rule_id}` | filters `pathway, verification_status, is_authoritative` | `PaginatedRulesOut`, `RuleDetailOut` (spec, items, OQ ids) | 404 / 422 | yes | ✅ — open-question *text* not returned (ids only); no `/open-questions` |
| 8 | Care-gap list | `GET /api/v1/care-gaps` | `status, gap_type, rule_id, limit, offset` | `PaginatedCareGapsOut` | 422 | yes | ⚠️ no patient filter, no detail route (`/care-gaps/{id}` → 404) |
| 10 | Facilities | `GET /api/v1/facilities` | `limit, offset` | `PaginatedFacilitiesOut` | – | yes | ⚠️ no detail/filter/coords/region name; overlay fields fabricated (D-6, D-7) |
| 11 | Follow-up mgmt | — | — | — | — | — | ❌ |
| 12 | Appointments | — | — | — | — | — | ❌ (`/appointments` → 404) |
| 13 | Referrals | — | — | — | — | — | ❌ (`/referrals` → 404) |
| 14 | Outreach preview | `POST /api/v1/outreach/preview` | `{patient_id, rule_id, channel, language}` | `OutreachPreviewOut` | 404 patient | yes | ⚠️ works but under-gated (D-1) |
| 15 | AI explanation | `POST /api/v1/explanations` | `{patient_id, rule_id}` | `ExplanationOut` | 404 | yes | ✅ deterministic text; LLM path unreachable |

**Method restriction:** CORS allows only `GET, POST, OPTIONS` — adding `PATCH/PUT` for follow-up will need a change.

---

## 10. AI Explanation Audit

| Item | Finding |
|---|---|
| LLM integration | `ExplanationService(llm_provider: Callable[[str], str] \| None)`; API instantiates it with `None` (`v1.py:228`) → **no LLM is ever called in the running backend** [V]. No SDK, model name, API key, timeout, or retry exists. |
| Prompt | One-line f-string with patient id, rule id/version, status, history, reason codes, guard ids, OQ ids (`service.py:287-292`). |
| Can AI change the result? | **No.** LLM text, if ever enabled, replaces only `summary_text`; `evaluation_status`, `is_authoritative`, `why_text`, citation, warnings are copied from the deterministic result (`service.py:301-314`). ✅ |
| Input minimisation | Strict: only a `SYNTH-PAT-\d{6,}` id + codes; privacy regex rejects `784-…` Emirates IDs, phones, e-mails (`service.py:21-24, 114-135`). ✅ — **but the regex check only scans a few fields, and `next_due_date` etc. are dates**, fine. |
| Output validation | Reject if empty, rule id absent, ID/phone/email, "% risk/chance/probability", diagnosis phrases, `overdue` when status ≠ overdue, "clinically approved" for non-authoritative. **Blocklist-based** → incomplete (e.g. invented intervals "every 3 years", numeric thresholds, "you must", "high risk" without a %). Does not verify the text agrees with `evaluation_status`. |
| Hallucination safeguard | Deterministic fallback on any validator failure or provider exception (exceptions swallowed silently — no log). |
| Logging / retention | None (no logging at all). |
| Person-level scoring permission | Explanation does not use scoring. `care_gap.priority_score` is gated by `ai_assisted_prioritisation` consent in the generator, but see D-5. |
| Minimum needed to enable LLM safely | (1) real provider adapter with timeout, (2) allow-list output check (must restate status/rule id; must not contain any number not present in the input), (3) log request id + mode + validator verdict (no PII), (4) golden tests per status, (5) config flag default **off**. |

---

## 11. Security, Consent and Governance Audit

**Consent**
- ✅ Outreach preview blocks on: deceased, no consent row (`contact_consent_absent`), `withdrawn`, any other non-`granted` state (`contact_consent_refused`), and invalid contact details. Absence / refusal / withdrawal produce **distinct** `blocked_reason`s **[V]**. `simulated_only` is hard-coded `True` and no transport code exists. ✅
- ❌ **D-1 / D-4:** gate considers only the *latest contact consent by list position* (`contact_consents[-1]`, `v1.py:836`), not `recorded_at`, **not scope** (`scope_pathway`/`scope_rule_id`), and ignores `screening_participation` refusals and `v_consent_current`. The DB view that does this correctly is unused.
- ❌ No check that the rule exists, is authoritative, that the patient has an **open care gap** for it, or that the evaluation is `due`. Probe: `rule_id="NOT-A-RULE"` → `allowed: true`; non-authoritative `IFHAS-PKG-CERVICAL-HPV-30-65` → `allowed: true`; message says the person "may be due for preventive screening". `rule_version` hard-coded `"1.0.0"` (`v1.py:853`). `language="ar"` returns English text under an "(ar)" label.
- ⚠️ `priority_score`/AI scoring: see D-5.

**Security**
- No authentication/authorisation, no rate limiting, no audit logging. Acceptable for a synthetic demo; must be explicit that it is **not** production-safe. `allow_credentials=True` with a configurable origin list — fine for local, review for deployment.
- `DATABASE_URL` is a `SecretStr`; `.env` is git-ignored; `/health/db` never returns connection details ✅.
- Input validation via Pydantic/Query constraints ✅. Unknown query params ignored silently (`?search=`).
- Synthetic labelling is consistent ✅ (`is_synthetic` everywhere, `SYNTH-` prefixes, data card). Responses include given/family names and synthetic phone/e-mail only in generator rows (the API returns names, not phone/e-mail) ✅.

**Governance claims.** The API/disclaimer text correctly says `clinical_review_status = not_reviewed`, synthetic, and "not clinically validated". No production-compliance claim found ✅. D18 states governance/legal review of consent is **not obtained**; UAE data-residency is not addressed anywhere in code or docs I inspected [A].

---

## 12. Testing and Reliability Audit

**Commands run (all non-destructive, no database):**

| Command (cwd) | Result | Runtime |
|---|---|---|
| `backend/.venv/bin/python -m pytest -q -rs --durations=10 -p no:cacheprovider` (`backend/`) | **143 passed, 0 failed, 84 skipped**, 1 warning | 23.98 s (pytest) / 25.2 s wall |
| `../backend/.venv/bin/python -m pytest -q -p no:cacheprovider` (`data-pipeline/`) | **122 passed, 0 failed, 0 skipped** | 8.10 s |
| `alembic upgrade head --sql` (dummy URL, offline, writes only to scratchpad) | exit 0 — 39 tables, 1,734 SQL lines | – |
| `alembic downgrade head:base --sql` (offline) | exit 0 | – |
| In-process probes (TestClient/engine, no network, no DB) | see §6–§11 | – |

**All 84 skipped tests** are `TEST_DATABASE_URL not set` (`test_official_schema` 33, `test_official_integrity` ~30, `test_official_loader` live tests, `test_clinical_schema/loader`, `test_synthetic_schema/generator`, `test_db`). **They are the tests that prove constraints, triggers, views, idempotency and the loaders against PostgreSQL; I could not run them (Docker networking hung in this sandbox) — so DB-level correctness is unverified here.** The commit's own docs claim `143 passed, 84 skipped`, which this audit reproduces exactly; it does not reproduce any live-DB result.

**Coverage by area**

| Area | Count | Note |
|---|---|---|
| API | 9 tests / 1 file | smoke-level; no test for: 404 on rule/care-gap, outreach for absent/withdrawn/unknown-rule, pagination bounds, `/health/db` 503 path via API client |
| Evaluation | 12 | good guard coverage; **no test for cancelled/scheduled referral**, hard-coded thresholds vs YAML |
| Explanation | 5 | ok; no LLM-path test through the API |
| Rule loader | 122 (data-pipeline) | strong, incl. strict-bool parametrisation |
| Official loader/integrity/schema | 123 | extensive; mostly live-DB |
| Synthetic generator/schema | 17 | determinism covered; **no journey-archetype coverage assertions** |
| Security / permissions | 0 dedicated | consent logic tested only indirectly |
| Migration tests | partial | upgrade/downgrade round-trip is live-DB only [U] |

**Slow tests (and why):** `test_reproducibility_and_seed_variation` 4.6 s call + 2.3 s setup (generates 550-patient datasets several times, 54 rules each); `test_dashboard_summary` 3.4 s (first call triggers `lru_cache` warm-up: YAML parse + dataset generation); `test_adult_eligible…` 2.1 s setup (bundle parse); `test_clinical_loader` ~1.3–1.6 s (re-parse). All fine in absolute terms. **Optimisation without weakening coverage:** make `parse_clinical_bundle()` and the default dataset session-scoped fixtures (`conftest.py` does not exist in `backend/tests`), and share the warm app between API tests.

**Reliability:** no logging; exceptions in the LLM path are swallowed; the first request after process start pays ~3 s (warm-up) and the app holds the whole dataset in memory per worker; `lru_cache` makes the API non-reloadable without restart.

---

## 13. Frontend Readiness Matrix

| Journey | Rating | What exists | Exact missing items |
|---|---|---|---|
| **1. Population overview** | **PARTIALLY READY** | `GET /dashboard/summary`: totals, adults/children, open/refused gap counts, evaluation-status counts (rule-level rows), rules summary, disclaimer | **Programme breakdown** (IFHAS vs Well-Child, per-package gap counts); **patient-level** counts of `unknown` / `requires_clinical_review` (current counts are *evaluation rows*, 29,700, not people); gaps by type/pathway; region split. Add `GET /api/v1/dashboard/summary` fields or `/dashboard/programmes`. |
| **2. People workspace** | **PARTIALLY READY** | `GET /patients` with sex/region/pathway filters, offset pagination; `history_by_pathway` in each item | `search` (name/ID), `sort`, filters by `evaluation_status` / `has_open_gap` / `history_status` / `age_band`; a per-person **evaluation-status roll-up** field (list rows contain none). |
| **3. Individual profile** | **PARTIALLY READY** | profile + all 54 evaluations with reason codes/guards + care gaps | Screening/visit history endpoint (`ifhas_screening`, `well_child_visit`, `component_result`, `assessment`); consent summary (state per type, scoped); `detail` text and input snapshot for evidence trace; guardian for children; `evaluations` filtered by pathway/status. |
| **4. Follow-up** | **NOT READY** | care-gap list only | `GET /care-gaps/{id}`; **recommended supported pathway** (target packages + facility with capability basis); **follow-up event write API** (`POST /care-gaps/{id}/follow-ups`); appointment & referral list/create/update; completion tracking (`closed_completed`); DB tables/events backing them (DB-4); DB-backed API with sessions. |
| **5. Rules & governance** | **READY** (minor) | `/rules`, `/rules/{id}` with source/version/effective-date triple/verification/review flag/OQ ids/items/spec | Open-question **text/status endpoint** (`/open-questions`, only ids now); `last_reviewed`; `clinical_review_status` per rule (only in dashboard). |
| **6. AI explanation** | **PARTIALLY READY** | `POST /explanations` deterministic, cites rule/version/source, never changes status | Real LLM wiring behind a flag (§10); stable evaluation id as input (current key is patient+rule); streaming not needed. Frontend can build against it today. |
| *Cross-cutting* | **BLOCKED BY GOVERNANCE / CLINICAL DECISION** (for specific content) | – | Programme-level recommendations beyond the 4 review-flagged packages, `overdue` semantics, and referral-refusal handling depend on §19 decisions (OQ-WCV-DUE-WINDOW, OQ-IFHAS-AGE-CEILING, D2-S4, D12–D14, D17). Frontend should render `requires_clinical_review`/`unknown` as first-class states. |

**Integration verdict:** the frontend can start integrating **now** against the 11 read/POST routes (stable Pydantic schemas, OpenAPI available at `/openapi.json`, CORS for `localhost:3000`). Mock the missing endpoints using the shapes proposed in §18.

---

## 14. Missing Functionality (summary)

1. DB-backed repository/service layer + `get_db` dependency (the API ignores PostgreSQL).
2. Follow-up/event recording, appointments, referrals, completion tracking (APIs and a state-transition/event table).
3. Care-gap detail; patient history; consent summary endpoints.
4. People search/sort/filter by status.
5. Population breakdown metrics for Journey 1.
6. Recommended-pathway endpoint tied to rule + facility capability (with correct "capability unknown/simulated" labelling).
7. Real (optional) LLM adapter and its output validator; logging.
8. Frozen migration DDL for 0007; synthetic-load CLI; seeded journey fixtures.
9. Packaging so the container can serve `/api/v1` (rules + data files).
10. Authentication/authorisation and audit logging (production only; out of MVP demo scope but must be disclosed).

---

## 15. Defects and Risks

### 15.1 Actual defects (verified)

| ID | Sev. | Defect | Where |
|---|---|---|---|
| **D-1** | P0 | Outreach preview returns `allowed: true` for a non-existent rule, for non-authoritative rules, and for patients with no open gap/`due` evaluation; message asserts "you may be due". Hard-coded `rule_version "1.0.0"`; `ar` language emits English. | `v1.py:822-874`, `service.py:316-414` |
| **D-2** | P0 | Referral with status `cancelled`/`scheduled` evaluates as `completed` (engine). | `engine.py:916-925` |
| **D-3** | P1 | Engine hard-codes 18 / 75 / 1–72 months instead of using rule spec; violates "YAML is source of truth". | `engine.py:447-449, 632-634, 648, 803, 943-954` |
| **D-4** | P1 | Contact-consent selection uses list order (`[-1]`) and ignores scope and `recorded_at`; DB view `v_consent_current` unused. | `v1.py:831-836` |
| **D-5** | P1 | Constant `priority_score = 0.78` attributed to a non-existent model `pulsereach-priority-0.1.0`, surfaced by the API as if scored. | `generator.py:913-919`, `CareGapOut` |
| **D-6** | P1 | Facility "usable" policy hard-coded in the router (`Active`, `Temporary Closure` kept; `About to Expire` 287 and `Preliminary - Active` 327 dropped) while decision **D13 is OPEN**; "Temporary Closure" being "usable" is questionable. | `v1.py:173-178` |
| **D-7** | P1 | `simulated_ifhas_service = is_primary and (region != 3 or idx % 2 == 1)` — arbitrary alternating rule invents IFHAS availability per real facility; `facility_id` is an enumeration index (not a DB key); `region_id or 1` silently defaults unknown regions. Brief: facility data must not infer unavailable services or IFHAS eligibility. | `v1.py:181-193` |
| **D-8** | P2 | Docs drift: dashboard example counts and `/health/db` strings differ from reality; placeholders for architecture/requirements/user-journeys/data-dictionary. | §4 |
| **D-9** | P1 | `backend/Dockerfile` builds from `backend/` only; `parse_clinical_bundle()` needs `data-pipeline/rules/` and facilities need `data/raw/abudhabi_sdi/` (resolved via `repo_root()`). In the compose image the first `/api/v1` call will raise. (Inferred from code + Dockerfile; **not run**, [A].) | `Dockerfile`, `clinical_loader/parse.py:118-136` |
| **D-10** | P2 | Migration 0007 depends on live ORM models (DB-1). | migrations |
| **D-11** | P2 | Unsupported query params silently ignored; `/evaluations` returns non-persistent ids; evaluation `age_convention` mismatch (DB-5). | – |
| **D-12** | P3 | `screening_package` branch discards computed `item_reasons` (latent). | `engine.py:412-422` |

### 15.2 Architectural risks
R-1 API/DB divergence (docs and ERD describe a DB the API never reads; two sources of truth). R-2 two YAML parsers. R-3 per-process in-memory dataset (no persistence of follow-up writes → any write API must go through the DB). R-4 `due` for "available history, no record" is coarse (per pathway). R-5 No logging/audit trail for a health-adjacent product. R-6 Governance: consent legal review and UAE data-residency outstanding.

### 15.3 Future enhancements
Auth/RBAC, rate limiting, audit log; evaluation persistence with stable ids; scoring-event table (U1); real facility capability data (needs D13/D1 governance); Arabic message templates; geospatial queries (D6).

---

## 16. Recommended Improvements (minimal, non-rewrite)

1. Add a thin **repository layer reading `v_*` views** and a `get_db` dependency; keep the in-memory path as a fallback mode (`DATA_SOURCE=memory|db`) so the frontend demo keeps working.
2. Fix D-1/D-2 in services (not router); move request→fact mapping out of `v1.py`.
3. Read thresholds from `bundle.rules[*].spec` (D-3) — pure refactor with tests.
4. Replace constant score with `priority_score = NULL` + `scoring_suppressed_reason = 'model_not_implemented'` unless a real documented scorer exists (D-5).
5. Remove the `idx % 2` overlay; return `simulated_*: null` and `capability_basis: "unknown"` until D13/D1 are governed; or read `synthetic.facility_service_profile` only for the 3 simulated profiles and label them.
6. Freeze 0007 DDL (generate from current metadata once, commit literal DDL).
7. Add `conftest.py` with session fixtures; a `docker-compose` test DB profile and a CI job that sets `TEST_DATABASE_URL` so the 84 live tests actually run.

---

## 17. Prioritized Implementation Roadmap

**Phase A — correctness/safety (P0), ~1–2 days:** T-01, T-02.
**Phase B — demo completeness (P1), ~1–1.5 weeks:** T-03 → T-11 (DB-backed read layer, history/consent/care-gap detail, search/sort, dashboard breakdown, follow-up/appointment/referral write path, journey fixtures).
**Phase C — hardening (P2):** T-12 → T-17.
**Phase D — future (P3):** T-18 → T-20.

---

## 18. Exact Tasks for Backend Developer

Complexity: S = ≤0.5 day, M = 1–2 days, L = 3+ days.

| ID | Pri | Current state | Files/modules | Missing / defective | Specific change | Depends on | Acceptance criteria | Tests required | Size |
|---|---|---|---|---|---|---|---|---|---|
| **T-01** | P0 | Outreach preview gated by latest contact consent only (D-1, D-4) | `app/api/v1.py:822-874`; `app/services/explanation/service.py:316-414`; new `app/services/outreach/` | No rule/gap/status/authority/scope checks; hard-coded version; language ignored | Resolve rule from bundle (404 if unknown); require **open care gap** for patient+rule **and** `evaluation_status in {due}` and `is_authoritative`; choose consent via `recorded_at` + scope (pathway/rule) matching `v_consent_current` semantics; use real `rule_version`; return `blocked_reason` for each failure (`rule_not_found`, `no_open_care_gap`, `rule_not_authoritative`, `contact_consent_*`); refuse `language='ar'` text unless an Arabic template exists (`blocked_reason: template_unavailable`) | – | `NOT-A-RULE` → 404; non-authoritative or non-due rule → `allowed:false`; absent/refused/withdrawn remain distinct; still `simulated_only:true` | unit + API tests for each blocked reason; consent ordering test (older `granted` after newer `withdrawn` list order); scope-mismatch test | M |
| **T-02** | P0 | Referral `cancelled`/`scheduled` ⇒ `completed` (D-2) | `engine.py:887-925` | Status not mapped | Map: `completed`→`completed`; `scheduled`/`initiated`→`upcoming` (or `due` per rule timing, with reason code); `cancelled`→ new reason `referral_cancelled` ⇒ `requires_clinical_review`; keep `pending` logic | clinical sign-off on cancelled semantics (§19-5) | probe in §6 returns the new statuses; no `completed` without `completed` status/date | parametrised engine test over all 5 referral statuses | S |
| **T-03** | P1 | API has no DB access | new `app/db/deps.py`, `app/repositories/*`, `app/api/v1.py` | No sessions, no repos | Add `get_db` dependency + repositories over `synthetic.*`, `clinical.*` (`v_rule_current`), `official.v_facility_usable`; env flag `DATA_SOURCE` (`memory` default, `db`); add CLI `python -m app.services.synthetic_generator.load` | DB available; T-14 | Same responses from both sources for all 11 routes (golden-diff test) | contract test comparing memory vs db payloads (live_db) | L |
| **T-04** | P1 | Profile lacks history/consent | `v1.py`, `schemas/v1.py` | No endpoints | Add `GET /patients/{id}/history` (screenings, visits, component results, assessments, guardians), `GET /patients/{id}/consents` (current per type/scope + full list) | T-03 (or memory) | Child profile shows guardian; consent states distinct | API tests incl. child + adult | M |
| **T-05** | P1 | Evidence trace incomplete | `engine.py` (`FiredReason.detail`, `input_snapshot`), `schemas/v1.py` | not exposed/persisted | Expose `detail`, `input_snapshot` (age, sex, history_state), `engine_version`, `look_ahead_days` in `EvaluationItemOut` (+ `evaluation_reason.detail` persisted if column missing → migration) | – | Every non-trivial status has human-readable `detail` | schema test; snapshot test | S–M |
| **T-06** | P1 | People list minimal | `v1.py:321-347` | No search/sort/status filters | Add `q` (name or id substring), `sort` (`family_name`, `age`, `open_gaps`), `evaluation_status`, `has_open_gap`, `history_status`; add `evaluation_summary` per row; reject unknown params (`extra=forbid` dependency) | – | 422 on unknown param; filters combine; stable ordering | API tests per filter; pagination boundary | M |
| **T-07** | P1 | No care-gap detail | `v1.py`, `schemas/v1.py` | no route | `GET /care-gaps/{id}` with evaluation reasons, rule citation, linked appointment/referral/outreach events, **recommended pathway** (rule's package + facilities flagged `capability_basis`) ; add `patient_id` filter to list | T-05 | 404 on unknown; includes rule version & source | API tests | M |
| **T-08** | P1 | Journey 1 metrics missing | `v1.py:279-318` | row-level counts only | Add per-**patient** counts by worst-status, by pathway, gaps by type/pathway, unknown/review counts; keep existing fields | – | numbers reconcile to dataset (sum rules) | reconciliation test | S |
| **T-09** | P1 | No workflow writes | new routes `POST /care-gaps/{id}/follow-ups`, `GET/POST/PATCH /appointments`, `GET/POST/PATCH /referrals`; CORS methods; `synthetic.*` models; new migration `0008` (follow_up_event table; status-transition constraints) | no APIs/tables for follow-up | Persist events (append-only) with `recorded_by`, `outcome`, `contact_consent_id` (required unless suppressed — mirror D18 CHECK); status transitions validated in service; reject outreach-type events without applicable consent | T-03, T-01, schema decision on follow-up table (§19) | Event writes visible in care-gap detail; gap `closed_completed` only via documented completion | live_db tests for CHECK/triggers; service tests for transitions | L |
| **T-10** | P1 | Thin journeys | `generator.py`, fixtures, data card | 1 appointment, 1 referral, 0 component results, 0 `closed_completed`, 4 contact grants | Add deterministic scenarios (no random drift of existing ids): ≥5 follow-up-in-progress (granted consent + appointment/outreach), ≥5 completed (gap closed by screening), ≥2 declined/cancelled referrals, ≥3 component results, ≥30 contactable patients with open gaps; update `spec_version`/data card/counts | T-09 schema | Archetype table in §7 has ≥3 patients per row; seed reproducible; data card regenerated | generator test asserting each archetype | M |
| **T-11** | P1 | Facility policy hard-coded & fabricated overlay (D-6/7) | `v1.py:162-225`; `official.v_facility_usable` | – | Move to a service; read `v_facility_usable` once D13 mapped, otherwise return all `identified`+`geo_quality ok` with raw `license_status_raw` and **no** capability flags (`capability_basis: "unknown"`); real facility key (`source_layer`,`source_object_id`) as id; add `GET /facilities/{id}`, filters (`region_id`, `facility_type`, `q`), coordinates + `geo_quality` | D13 | no `idx % 2` logic; unknown region not defaulted | API test asserting no simulated flags unless profile exists | M |
| **T-12** | P2 | Config thresholds | `engine.py` | D-3 | Derive 18/75/1–72 from rule spec (`IFHAS-PROG-ELIG-MIN-AGE.min_years`, `WCV-PROG-SCOPE.age_min/max`); ceiling stays "review" until OQ resolves; parity negative tests for backend `_strict_bool` | – | changing YAML value changes result without code edit | engine + loader tests | S–M |
| **T-13** | P2 | Constant score (D-5) | `generator.py:905-950`; `schemas` | – | Null scores + `scoring_suppressed_reason='model_not_implemented'`; or implement documented non-clinical scorer with data card | product decision (§19) | no `pulsereach-priority-*` string without a scorer | generator + API tests | S |
| **T-14** | P2 | 84 tests never run in CI | CI config (none), `backend/tests/conftest.py` (none) | No CI, no compose test profile | Add Postgres service to CI; `TEST_DATABASE_URL`; session fixtures for bundle/dataset | – | CI shows 0 skipped for `live_db` | the existing 84 | M |
| **T-15** | P2 | Mig 0007 coupled to models (DB-1) | `0007_…py` | – | Replace `Base.metadata` usage with literal DDL (dump from `alembic upgrade --sql`) | T-14 | `alembic check` clean; DDL identical to current | migration round-trip test | S |
| **T-16** | P2 | No logging / LLM off | `app/core/logging.py`, `explanation/service.py` | – | Structured logging (request id, no PII); log LLM fallbacks; optional provider behind `EXPLANATION_LLM_ENABLED=false`; allow-list validator (§10) | model/provider decision | fallback reasons logged; numeric-token guard | explanation tests (golden per status) | M |
| **T-17** | P2 | Container can't serve API (D-9) | `Dockerfile`, `infrastructure/docker-compose.yml` | rules/data not in image | Build from repo root context or mount `data-pipeline/rules` + `data/raw/abudhabi_sdi` and set `RULES_DIR`/`DATA_DIR`; fail fast at startup if bundle missing | – | `docker compose up` then `/api/v1/rules` 200 | smoke test | S |
| **T-18** | P3 | Docs drift (D-8) | `docs/api-contracts.md`, `architecture.md`, `requirements.md`, `user-journeys.md`, `data-dictionary.md`, design D6/D7/D11 | stale/placeholder | Regenerate API examples from the app; replace placeholders; record D6/D7/D11 confirmation | owner | docs match `/openapi.json` | doc check script | S |
| **T-19** | P3 | `item_reasons` dropped in packages (D-12) | `engine.py` | latent | Include item-level unresolved reasons for packages | – | no behaviour change today | engine test with synthetic unverified item | S |
| **T-20** | P3 | No auth/audit | app-wide | – | AuthN/Z, rate-limit, audit trail; data-residency review | governance | n/a for MVP | – | L |

---

## 19. Dependencies on Clinical / Governance Decisions

| # | Decision | Needed for | Status |
|---|---|---|---|
| 1 | **OQ-WCV-DUE-WINDOW** — meaning of "overdue" for Well-Child | any `overdue` output; today everything past the visit month is `requires_clinical_review` | open (unresolved rule `WCV-TIMING-DUE-WINDOW`) |
| 2 | **OQ-IFHAS-AGE-CEILING** — upper age (engine uses >75 ⇒ review) | T-12 | open |
| 3 | **OQ-COMMON-AGE-CALC / D17-4** — age convention (engine uses completed years) | DB-5, T-12 | open |
| 4 | **D17-1/-2** guard precedence; `partial` history handling | engine ordering (currently: authority → review flag → attributes → history) | open — clinical |
| 5 | **D2-S2…S5** refusal evidence (documented + signed, guardian, declined referral) and **cancelled-referral** semantics | engine refusal logic, T-02, T-09 | provisional |
| 6 | **D12** working-day calendar (engine approximates working days as ×7/5) | referral deadline | open |
| 7 | **D13** licence-status mapping; **D1/D15** facility naming and capability overlay governance | T-11 | open / governance not obtained |
| 8 | **D14** rule-applicability policy (engine evaluates all 54 rules for everyone) | engine/UX | open — clinical |
| 9 | **Coarse `due` for "available history, no record"** — clinical sign-off that per-pathway availability suffices to assert a gap | engine | needs sign-off |
| 10 | **D18** — governance/legal review of consent for outreach/AI; UAE data-residency | any non-simulated use | not obtained |
| 11 | **Product decision** on priority scoring (real scorer vs remove) | T-13 | open |
| 12 | Clinical review of all 54 rules (`clinical_review_status: not_reviewed`) | any clinical-validity claim | not done — **no clinical validation exists** |

---

## 20. Final MVP Readiness Assessment

- **Foundation:** strong. The hardest correctness properties (no `overdue`, unknown-history safety, unresolved-rule blocking, strict Booleans, provenance, reproducible synthetic data) are implemented **and** tested.
- **MVP shape:** the demo API works as a read-only showcase for Journeys 1, 3, 5, 6. It does **not** yet deliver the product's follow-up/appointments/referrals/completion loop (Journey 4) or a database-backed backend.
- **Blocking before demo (P0/P1):** T-01, T-02 (safety correctness), then T-09/T-10 (a working follow-up story) plus T-03/T-04/T-06/T-07/T-08 for frontend breadth. Realistic effort: ~2–3 developer-weeks.
- **Not claimed:** clinical validation, regulatory compliance, production security, data-residency compliance. None is supported by evidence in this repository.
- **Unverified in this audit:** every PostgreSQL-dependent behaviour (84 skipped tests, live migrations, triggers, idempotent re-run), Docker image behaviour, the `frontend/` code.

*Method note:* all probes ran in-process with no network and no database writes; scratch files lived in the session scratchpad. A temporary Docker container created for a live-DB attempt was removed; the pre-existing `pr-recon-pg` container was not touched.
