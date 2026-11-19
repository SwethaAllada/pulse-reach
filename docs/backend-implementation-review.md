# PulseReach — Backend Implementation Review (pre-Phase 4 audit)

**Audit date:** 2026-11-19 · **Branch audited:** `siri_dev_pr` @ `9ab38b1` (= `origin/siri_dev_pr`) · **Baseline:** `7412411` (merge-base with `main`) · **Type:** read-only, independent audit. The only file written to the repository is this report.

**Evidence labels:** **[V]** verified by executing code, tests, probes or CI logs in this audit · **[C]** verified by reading code only · **[U]** could not be verified (reason stated) · **[R]** risk requiring further validation (not a confirmed defect).

---

## 1. Executive verdict

| Scope | Verdict |
|---|---|
| **Document 1** — `docs/backend-implementation-audit.md` (tasks T-01…T-20) | **NOT READY** |
| **Document 2** — `docs/frontend-uiux-design-proposal.md` §12 + §14.1 backend handoff contract (H-1…H-13) | **NOT READY** |
| **Combined backend readiness for Phase 4 (Follow-up & Outreach)** | **NOT READY** |

The teammate delivered a large amount of real, mostly well-structured work: outreach gating (T-01) and referral status mapping (T-02) are correct and well tested; history, consents, evidence fields, People search/sort/filters, care-gap detail and dashboard breakdowns exist; the fabricated priority score and facility capability heuristic are gone; 0007 is frozen; logging and request IDs exist. **Read-only, memory-mode (`DATA_SOURCE=memory`) frontend integration for Journeys 1, 2, 3, 5 is viable today.**

Phase 4 is built on the parts that are not ready:

1. **Completion can be recorded without real completion evidence.** `POST /care-gaps/{id}/follow-ups` with `close_gap=true` accepts *any* screening, visit or referral belonging to the patient, including a **`partial`** screening for a **different rule**. The probe closed `IFHAS-PKG-VISION-40-75` as `closed_completed` using a partial screening of another package. The evaluation for the same rule stays `due`. **[V]** (F-01, Critical)
2. **The PostgreSQL path cannot be populated or proven.** The seed CLI fails with an `ImportError` (F-02). CI on this branch is **red: 8 failed / 264 passed** (F-03). The only "DB parity" test runs on SQLite with every FK, CHECK and computed column stripped (F-04). `PostgresFollowUpRepository` has **no tests**. The default Docker Compose mode (`DATA_SOURCE=db`) therefore returns 503 on every `/api/v1` route [C].
3. **Workflow writes do not preserve lifecycle history.** Appointment and referral `PATCH` overwrite status and datetime in place, with no event row. Appointment and referral writes do not create follow-up events and do not change gap or evaluation state (F-06, F-07).
4. **Some documented deliverables are missing:** facility filters, detail and coordinates (T-11 / H-10); recommended pathway in care-gap detail (T-07 / H-6); review-decision API (H-8); rule-vs-record origin split (H-7); open-questions endpoint (H-12); applicability marker (H-13); data card regeneration (T-10); startup fail-fast (T-17); LLM flag wiring and fallback logging (T-16).

Clinical-safety invariants that were already correct are **still intact** [V]:
- Missing history gives `unknown` with no gap.
- Unresolved and review-flagged rules give `requires_clinical_review`.
- `overdue` is never produced.
- Cancelled, scheduled and declined referrals are never `completed`.
- Outreach is never authorised by absent consent.
- No LLM is reachable.

---

## 2. Documents reviewed

Neither document exists on `siri_dev_pr`. Both live on `main` and were authored by the repository owner. They were identified from Git history (`git log --all --diff-filter=A -- docs`):

| # | File (on `main`) | Commit | Role in this audit |
|---|---|---|---|
| Doc 1 | `docs/backend-implementation-audit.md` (439 lines) | `c4f009d` "Backend report", 2026-11-17 | §18 *Exact Tasks for Backend Developer* T-01…T-20 with acceptance criteria and required tests; defects D-1…D-12, DB-1…DB-7 |
| Doc 2 | `docs/frontend-uiux-design-proposal.md` (1,188 lines) | `23566f1` "Frontend design doc", 2026-11-18 | §12 screen-to-capability map, §12.2 blocked visuals, §13 safeguards, **§14.1 Backend handoff contract H-1…H-13** |

Both documents reference `docs/api-contracts.md`, `docs/phase-3-database-design.md` (D-decisions), `data-pipeline/rules/common/status_definitions.yaml` (reason codes and guards) and the rule YAML files. These were consulted where a requirement depended on them.

Doc 1 sets the priorities: P0 is T-01 and T-02; P1 is T-03…T-11; P2 is T-12…T-17; P3 is T-18…T-20. P3 is listed below but is not counted against readiness.

---

## 3. Implementation scope

- **Branch / status:** `siri_dev_pr`. The working tree was clean before the audit. Local HEAD equals `origin/siri_dev_pr`. The branch merges cleanly into `main` (`git merge-tree` exit 0). `main` contains the frontend work (`a2f77db`, `f2f7eb9`, `3ed95f6`) that is absent here.
- **Teammate commits (Siri Nandan Chilamkurthy, 23 commits, `6b0645d`…`9ab38b1`):** T-01 `6b0645d`, T-02 `db742ed`, T-03 `4d2b5b6` and `12dbdb6`, T-04 `220c8b1`, T-05 `a7d2a01`, T-06 `c2618af`, T-07 `7c28e58`, T-08 `852987f`, Sprint C fixes `82bef57`, T-09 `708675a`, T-10 `636e6de`, Sprint D fixes `9c7dc23`, T-11 `1298038`, T-12 `190ceb4`, T-13 `071500f`, T-14 `af79cac`, T-15 `cae465d`, T-16 `55fd179`, T-17 `fed47e5`, Sprint E fixes `1071fb9` and `69219f2`, docs `9ab38b1`.
- **Pre-existing code (not attributed):** `7412411` / `e23e37e` (schemas 0001–0007, engine, generator, loaders, original `v1.py`). On `main`: frontend commits by SwethaAllada.
- **Diff `7412411..HEAD`:** 37 files, +8,061 / −970. Nothing was deleted.
  - **New:**
    - `app/repositories/read_repo.py` (2,567 lines)
    - `app/repositories/followup_repo.py` (914)
    - `app/services/outreach/service.py` (281)
    - `app/services/followup/service.py` (184)
    - `app/core/logging.py`
    - `app/db/deps.py`
    - `app/services/synthetic_generator/seed.py`
    - `migrations/versions/0008_add_care_gap_follow_up_event.py`
    - `.github/workflows/ci.yml`
    - `tests/conftest.py`
    - 9 new test files
  - **Modified:**
    - `api/v1.py` (rewritten as a thin router, 584 lines)
    - `schemas/v1.py`
    - `engine.py`
    - `generator.py`
    - `models/synthetic.py` (+`CareGapFollowUpEvent`)
    - `0007` (frozen DDL)
    - `main.py`
    - `config.py`
    - `Dockerfile`
    - `docker-compose.yml`
    - `demo_patients_50.json`
    - `docs/api-contracts.md`
- **New or changed endpoints (11 new):**
  - `GET /patients/{id}/history`
  - `GET /patients/{id}/consents`
  - `GET /care-gaps/{id}`
  - `POST /care-gaps/{id}/follow-ups`
  - `GET`, `POST /appointments` and `PATCH /appointments/{id}`
  - `GET`, `POST /referrals` and `PATCH /referrals/{id}`
  - Extended query parameters on `GET /patients` and `GET /care-gaps`
  - Extended fields on `EvaluationItemOut` and `DashboardSummaryOut`
- **Exists only in documentation, not in code:**
  - `python -m app.cli.seed` (claimed in `docs/api-contracts.md:147`; there is no `app/cli`).
  - "repository parity" for `followup_repo` (no DB test exists).
  - `backend: 187 passed, 85 skipped` (true offline only; CI on PostgreSQL is red).

---

## 4. Validation performed

| Command (cwd) | Result | Completeness |
|---|---|---|
| `backend/.venv/bin/python -m pytest -q -rs -p no:cacheprovider` (`backend/`) | **187 passed, 0 failed, 85 skipped**, 1 warning (12.1 s). All 85 skips are `TEST_DATABASE_URL not set`. | Offline only |
| `../backend/.venv/bin/python -m pytest -q -p no:cacheprovider` (`data-pipeline/`) | **122 passed** | Complete |
| `gh run view 44457754078 --log-failed` (CI on `siri_dev_pr`, PR run, 2026-11-19) | `alembic upgrade head` **success on PostgreSQL 16** (0001→0008 logged). Test step **8 failed, 264 passed, 0 skipped**. Data-pipeline step **skipped**. Run `44359757884` (push of `9ab38b1`) also 8 failed / 264 passed. | Live DB evidence, third-party run |
| `alembic upgrade head --sql` / `downgrade head:base --sql` (dummy URL, output to `/tmp`) | Both exit 0. 41 `CREATE TABLE` (39 + `care_gap_follow_up_event` + `alembic_version`). | Offline render |
| `python -c "import app.services.synthetic_generator.seed"` | **ImportError:** `cannot import name 'load_clinical_bundle'` | Complete |
| `uvicorn app.main:app` (memory mode, port 8765) | Startup OK. `/health` 200, `/api/v1/rules` 200, dashboard 200 (1.8 kB), evaluations 200 (57.6 kB/patient), CORS preflight `PATCH` 200 | Complete for memory mode |
| `uvicorn` with `RULES_DIR=/tmp/pr_audit_no_rules` | Startup **succeeds**. `/health` 200, `/api/v1/rules` **500** (no fail-fast) | Complete |
| In-process probe `/tmp/pr_audit_probe.py` (TestClient, memory mode) | See §§7–9 | Complete for memory mode |
| Disposable `postgres:17` container `pr-audit-pg-disposable` on `127.0.0.1:55439` | Container created, but host connections timed out and `docker exec` / `docker logs` hung (Podman engine unresponsive). Container removed with `docker rm -f`. Unrelated containers were not touched. | **Not achieved [U]** |
| Lint / type check | No `ruff`, `mypy` or `flake8` in `backend/.venv`; the repository declares none. Not run, and no dependencies were installed. | **Not run [U]** |
| `docker build` / `docker compose up` | Not executed; Docker engine unresponsive in this environment. | **[U]** |

**Not independently verified [U]:**
- Live behaviour of `PostgresFollowUpRepository`.
- Trigger behaviour of `care_gap_follow_up_event`.
- Live downgrade.
- `alembic check` drift.
- The Docker image.

CI evidence covers upgrade-to-head only.

---

## 5. Requirements-to-code traceability matrix

### 5.1 Document 1 (T-01…T-20)

| ID | Requirement (abridged) | Implementation location | Status | Test coverage / evidence | Finding |
|---|---|---|---|---|---|
| T-01 | Outreach: 404 on unknown rule; block non-authoritative, no open gap and not-`due`; consent by `recorded_at` + scope; real `rule_version`; `template_unavailable` for `ar` | `services/outreach/service.py:59-101` (`resolve_applicable_contact_consent`), `:131-281` (`preview_outreach`); `api/v1.py:457-496` | **Complete** | 9 tests in `test_outreach_service.py` (ordering, scope mismatch, `ar`, privacy, API 404). Probe: `NOT-A-RULE` 404; `CERVICAL-HPV` → `rule_not_authoritative`; `ar` → `template_unavailable`; 33 allowed patients; blocked reasons distinct [V] | `screening_participation` refusal not consulted (accepted by T-01 wording). Precedence returns `rule_not_authoritative` before `no_open_care_gap`. |
| T-02 | Referral `cancelled` → review; `scheduled`/`initiated` → `upcoming`; never `completed` without completion | `engine.py:192-221`, used at `:906-911`, `:993-997` | **Complete** | 8-case parametrised test `test_evaluation_service.py:530-578` [V] | New reason codes not in vocabulary (F-11). `declined` not parametrised. |
| T-03 | `get_db` + repositories; `DATA_SOURCE`; seed CLI; golden memory-vs-db diff for all routes | `db/deps.py`, `repositories/read_repo.py`, `seed.py` | **Partial / Incorrect** | Seed CLI ImportError [V]. "Parity" test runs on stripped SQLite (`test_read_repository.py:95-139`). Live parity test fails in CI (503 "no seeded run") [V] | F-02, F-03, F-04 |
| T-04 | `GET /patients/{id}/history` (screenings, visits, components, assessments, guardians); `GET /patients/{id}/consents` (current + full) | `api/v1.py:191-210`; `read_repo.py:1302-1463` | **Complete (memory) / Unverifiable (db)** | `test_sprint_c_api.py:15-82`; child probe returned 1 guardian [V] | Referrals not in history (doc lists them; minor) |
| T-05 | Expose `detail`, `input_snapshot`, `engine_version`, `look_ahead_days`; persist detail if needed | `schemas/v1.py:96-116`; `read_repo.py:360-459` | **Partial** | Fields present [V] | `reason_detail` is a generic template, not the engine's `FiredReason.detail` (F-12). `input_snapshot` is recomputed at read time from current data and not persisted, so it is not a historical snapshot. |
| T-06 | `q`, `sort`, `evaluation_status`, `has_open_gap`, `history_status`; `evaluation_summary`; 422 on unknown params | `api/v1.py:100-166`; `read_repo.py:788-915`, `:1709-1844` | **Complete (renamed)** | `test_sprint_c_api.py:126-182`; `?search=` → 422 [V] | Names differ from doc (`sort_by`/`sort_dir`, `has_open_care_gaps`). Unknown-param rejection only on `/patients` (`/care-gaps?search=` → 200 [V]). |
| T-07 | `GET /care-gaps/{id}` with reasons, rule citation, linked appointment/referral/outreach, **recommended pathway**; `patient_id` filter; 404 | `api/v1.py:381-389`; `read_repo.py:1168-1229`, `:2251-2341` | **Partial** | 404 [V]; detail keys [V] | No recommended pathway object (only a static notice string). Referrals linked heuristically by `trigger_rule_id`. `closed_by_ifhas_screening_id`, `_well_child_visit_id` and `_referral_id` are **not exposed** (F-09). |
| T-08 | Per-patient counts by **worst status**, by pathway, gaps by type/pathway, unknown/review counts; reconcile | `read_repo.py:643-742` | **Partial** | `test_sprint_c_api.py:216` | `patient_status_counts` is non-exclusive (sums to 2,208 for 550 patients) and not worst-status. `review_flagged_patients_count = 550` [V] (F-10). |
| T-09 | Follow-up events (append-only, `recorded_by`, outcome, consent); appointment/referral GET/POST/PATCH; CORS PATCH; migration 0008 with transition constraints; gap `closed_completed` only via documented completion; live-DB tests | `followup_repo.py`, `services/followup/service.py`, `0008`, `main.py:79` | **Partial / Incorrect** | Memory-mode API tests only (`test_followup_service.py`). **No test for `PostgresFollowUpRepository`.** Bad-evidence closure probe → 201 [V] | F-01, F-05, F-06, F-07, F-08, F-13, F-14 |
| T-10 | ≥5 in progress, ≥5 completed, ≥2 declined/cancelled referrals, ≥3 component results, ≥30 contactable; `spec_version` + **data card regenerated** | `generator.py`; `test_synthetic_journeys.py` | **Partial** | Counts [V]: 6 scheduled appointments, 5 `closed_completed`, 1 declined + 1 cancelled, 5 component results, 33 contactable; `spec_version 2.6.0` | `data/synthetic/SYNTH-RUN-0001/data_card.md` unchanged since `7412411` (still 1 appointment, 0 component results). The declined and cancelled referrals point at package rules, so they never exercise T-02 logic. Live load of the new dataset never succeeds in CI (F-03). |
| T-11 | Facility policy in a service; no `idx % 2`; `capability_basis: "unknown"`; real key; **`GET /facilities/{id}`; filters `region_id`, `facility_type`, `q`; coordinates + `geo_quality`** | `read_repo.py:262-329`, `:2343-2381` | **Partial** | `idx % 2` removed [V] | `/facilities/1` → 404 and `?region_id=3` ignored (2,985 = 2,985) [V]. No coordinates or `geo_quality`. "Usable" licence policy still hard-coded (D-6 / D13 open). Governance notice still says "SIMULATED overlay". Fallback fabricates 3 facilities with `simulated_ifhas_service=True` if SDI files are absent (F-15). |
| T-12 | Derive 18 / 75 / 1–72 from rule spec (`IFHAS-PROG-ELIG-MIN-AGE.min_years`, `WCV-PROG-SCOPE.age_min/max`); strict-bool parity | `engine.py:241-266` | **Partial** | `test_evaluation_service.py:580-705` [V] | WCV bounds come from min/max of visit `recommended_age_months`, not `WCV-PROG-SCOPE.spec.age_min/age_max`. Upper IFHAS bound is max of package `age_max_years`. Silent hard-coded fallbacks (18/75/1/72) remain. |
| T-13 | Null scores + `scoring_suppressed_reason='model_not_implemented'` | `generator.py` | **Complete** | 0 non-null scores; 1,444 `model_not_implemented`, 6 `ai_consent_refused` [V] | — |
| T-14 | Postgres in CI; `TEST_DATABASE_URL`; session fixtures; "CI shows 0 skipped" | `.github/workflows/ci.yml`; `tests/conftest.py` | **Incorrect** | CI 0 skipped but **8 failed** [V] | F-03. `pg_test_engine` fixture is unused. CI sets `DATABASE_URL`, which breaks `test_db.py::test_build_engine_without_url_raises`. |
| T-15 | Freeze 0007 DDL; `alembic check` clean; round-trip test | `0007` (`_FROZEN_DDL_STATEMENTS`) | **Partial** | Static string test only (`test_synthetic_schema.py` `test_migration_0007_uses_frozen_static_ddl`). Upgrade to head succeeds live in CI [V] | No round-trip test. `alembic check` not run. 0008 constraint names are double-prefixed and hashed (`ck_care_gap_follow_up_event_ck_care_gap_follow_up_event_5812`) and do not match ORM naming, which is likely drift [R]. |
| T-16 | Structured logging (request id, no PII); **log LLM fallbacks**; provider behind flag default off; **allow-list validator** | `core/logging.py`; `main.py:35-74`; `config.py:26` | **Partial** | `test_observability.py` (3 tests) [V] | `llm_enabled` is only logged; `ExplanationService(llm_provider=None)` is unconditional (`v1.py:71`). `services/explanation/` unchanged, so no fallback logging and no allow-list validator. |
| T-17 | Image contains rules + data; `RULES_DIR` / `DATA_DIR`; **fail fast if bundle missing**; `docker compose up` → `/api/v1/rules` 200 | `Dockerfile`; `docker-compose.yml` | **Partial / Unverifiable** | Static file-content test only (`test_docker_packaging.py`). Missing rules → startup OK, then 500 [V] | F-16, F-17 |
| T-18 (P3) | Docs match OpenAPI | `docs/api-contracts.md` | Partial | — | Claims non-existent `app.cli.seed` and misstated test results. Architecture / requirements placeholders remain. |
| T-19 (P3) | Item reasons for packages | — | Missing (P3) | — | — |
| T-20 (P3) | Auth / audit | — | Missing (P3) | — | `recorded_by` is free text supplied by the client. |

### 5.2 Document 2 (§14.1 handoff contract)

| ID | Contract | Status | Evidence / gap |
|---|---|---|---|
| H-1 | Gated outreach preview, real version, `template_unavailable` | **Complete** | as T-01 [V] |
| H-2 | Cancelled/scheduled referral ≠ completed | **Complete** | as T-02 [V] |
| H-3 | `GET /patients/{id}/history`, `/consents` | **Complete (memory)** | as T-04 |
| H-4 | `detail` + `input_snapshot` on `EvaluationItemOut` | **Partial** | F-12. The §12.2 wording "Inputs used by the engine" is not yet truthful, because the snapshot is reconstructed at read time. |
| H-5 | People search/sort/status filters, `evaluation_summary`, unknown params rejected | **Complete (renamed params)** | as T-06; the frontend must use `sort_by` / `has_open_care_gaps` |
| H-6 | Care-gap detail incl. linked events and **recommended pathway**; `patient_id` filter | **Partial** | No pathway object; closing evidence not exposed |
| H-7 | Person-level aggregates incl. worst status and **unknown/review split by origin (rule vs record)** | **Partial** | No origin split; `review_flagged_patients_count` = 550/550 [V], the exact metric §13.3 says is misleading |
| H-8 | Follow-up, appointment, referral **and review** write/read APIs; CORS PATCH | **Partial** | No `care_gap_review` API (`POST /care-gaps/{id}/reviews` → 404 [V]); no follow-up list route; F-01, F-06 |
| H-9 | Journey data thresholds | **Complete (counts)** | as T-10; data card stale |
| H-10 | Facility filters, coordinates, detail, honest capability basis | **Partial** | as T-11 |
| H-11 | Priority nulled with `scoring_suppressed_reason` | **Complete** | as T-13 |
| H-12 | `/open-questions` endpoint | **Missing** | `GET /api/v1/open-questions` → 404 [V] |
| H-13 | Rule-applicability marker per evaluation | **Missing** | No field on `EvaluationItemOut` |

**Summary:**
- Doc 1 P0–P2 (T-01…T-17): 5 Complete (T-01, T-02, T-04, T-06, T-13), 9 Partial, 2 Incorrect (T-03, T-14), 1 Partial/Incorrect (T-09).
- Doc 2: 5 Complete, 6 Partial, 2 Missing.

---

## 6. Technical depth assessment

### 6.1 Architecture

**Strengths [C]:**
- The router is now thin: `v1.py` delegates to `ReadRepository` / `FollowUpRepository`.
- Outreach and transition rules live in services (`OutreachService`, `FollowUpService`) and not in the router.
- Repositories are selected by an explicit `DATA_SOURCE`, with no silent fallback from DB to memory.
- No circular imports (the suite imports cleanly).

**Weaknesses:**
- **Two full parallel implementations.** Every read and write is implemented twice: Memory at `read_repo.py:745-1299` and `followup_repo.py:135-436`, Postgres at `read_repo.py:1562-2567` and `followup_repo.py:439-914`.
  - Business validation such as evidence lookup is duplicated, not shared.
  - The two copies already diverge. In DB mode the composite FKs reject a non-performed screening (returned as 503). In memory mode the same request is accepted (F-01, F-05).
- **Domain logic in repositories.** Gap-closure evidence resolution, outreach-to-event mapping and rule-meta fallbacks live in repository classes, not in `FollowUpService`.
- **`POST /evaluations` still assembles results in the router** (`v1.py:213-321`), duplicating the repository's evaluation-to-DTO mapping. It mints IDs locally (F-18).
- **Repositories raise `HTTPException`.** This couples persistence to transport, and the repositories cannot be reused from CLI or worker code.
- **Memory "writes" mutate the process-wide `lru_cache`d dataset** (`followup_repo.py:192-193`, `:299`, `:412-413`). Writes are per-worker, lost on restart, and leak between tests.
- **Silent fallbacks:**
  - `FollowUpService.evaluate_outreach_consent` (`services/followup/service.py:144-165`) fabricates `is_authoritative: True`, an open gap `SYNTH-GAP-000001` and a `due` evaluation when callers omit them. Current callers pass real values, and the outreach service still blocks on missing `verification_status`, but the default is unsafe [R].
  - The memory repo falls back to `pathway: "ifhas"` for an unknown rule (`followup_repo.py:155`).

### 6.2 Data model and database

- **0008 `care_gap_follow_up_event`:**
  - Correct composite FK to `care_gap`, append-only trigger, and indexes on `(care_gap_id, recorded_at)` and `(patient_id, recorded_at)` [C, upgrade verified in CI].
  - Gaps:
    - `contact_consent_id` has **no FK** to `synthetic.consent`. `outreach_event` enforces `consent.grants_contact` via a composite FK; this table does not, so a non-granted or unrelated consent id is accepted at DB level (F-13).
    - No CHECK on `outcome_status` values.
    - No CHECK tying `completion_documented` to `documented_evidence` / `evidence_reference`.
    - No status-transition constraints for appointments or referrals, which T-09 required.
    - `follow_up_id` is the sole PK, as elsewhere.
- **Reset path broken by 0008.** `synthetic_generator/load.py:19-38` `DELETE_ORDER` omits `care_gap_follow_up_event`. With the FK `ON DELETE RESTRICT`, re-seeding a run that has any follow-up events will fail [C] (F-08).
- **Lifecycle history.** Appointments and referrals remain mutable rows with no history table (DB-4 in Doc 1 is unresolved for these). `care_gap` closure is an in-place `UPDATE`; only the follow-up event preserves the "why".
- **DB-level evidence is weaker than the business rule.** `fk_care_gap_closed_by_referral_id_referral` (`models/synthetic.py:1335-1349`) only requires `referral.is_initiated` (`initiated_date IS NOT NULL`). An **initiated-then-cancelled** referral therefore satisfies the DB constraint for `closed_completed` on *any* gap type [C].
- **Rule identity in DB mode.** The repository keys rules by `rule_id` only (`read_repo.py:1881`, `:2200`) and counts all versions (`:1631`). This is latent until a second rule version is loaded [R].

### 6.3 Business logic

| Rule | Authoritative location | Verdict |
|---|---|---|
| Outreach gating | `OutreachService.preview_outreach` | Correct; deterministic; consent resolution tested for ordering and scope [V] |
| Referral status → evaluation | `engine._evaluate_non_pending_referral` | Correct [V]. `initiated` maps to `upcoming` with `next_due_date = initiated_date` (a past date). Semantically odd but documented. |
| Gap completion | Repository code (memory and PG) | **Incorrect:** no check of evidence status (`complete` / `attended` / `completed`), evidence rule == gap rule, gap-type compatibility, or evidence date (F-01) |
| Appointment transitions | `FollowUpService._APPOINTMENT_TRANSITIONS` | Correct as a state machine [V] (`attended`→`scheduled` → 422). `attended` does not create a follow-up event or evidence. |
| Referral transitions/dates | `FollowUpService` | Correct date ordering [V]; creating with `status=completed` → 422 [V] |
| Outreach follow-up event | Repositories | Records `outcome_status="sent"` for a simulated-only product [V] (F-14). Suppresses an attempt as `template_unavailable` for Arabic-preferring patients, which conflates template availability with authorisation [C]. |
| Age / month bounds | `engine.py:241-266` | Partially YAML-driven (see T-12) |
| Dashboard aggregation | `_build_dashboard_summary_out` | Does not double-count, but `eligible_or_due_patients` merges programme `eligible` with package `due` / `upcoming`. IFHAS shows **550** people, including all **139 children**, because `IFHAS-PROG-ELIG-THIQA` / `-SEX-BY-PACKAGE` evaluate `eligible` regardless of age [V]. This mixes programme eligibility with preventive-care need (F-10). |

### 6.4 API contract

- **Consistent:** paginated envelopes (`total`, `limit`, `offset`, `items`), `is_synthetic`, Pydantic validation, 404 on unknown ids, 422 on invalid enums and transitions [V].
- **Inconsistent:**
  - Parameter names deviate from both documents (`sort_by`, `has_open_care_gaps`).
  - Unknown-param rejection only on `/patients`.
  - `POST /evaluations` accepts `look_ahead_days: null` (200) [V].
  - Write errors in PG mode surface as **503 "PostgreSQL write failed"** for what are really 409/422 conditions (IntegrityError from CHECK/FK or an id collision).
  - Several handlers echo raw exceptions: `detail=f"PostgreSQL query failed: {exc}"` (`read_repo.py:1638`, `:1828`, `:1862`, `:1940`…; `followup_repo.py:649`, `:738`, `:764`, `:913`). This leaks SQL text and bound parameters to clients (F-19).
- **Frontend needs not met:**
  - Closing evidence ids are not exposed (F-09).
  - No follow-up list endpoint; events are only nested in care-gap detail.
  - `GET /patients/{id}/evaluations` returns about 58 kB per person (all 54 rules), with no pathway or status filter (Doc 1 §13 asked for one).
- **Idempotency:** none for POSTs. A retried `POST /appointments` or `/follow-ups` creates duplicates.
- **ID minting:** `MAX(id)+1` (`followup_repo.py:62-69`, `:596-600`, `:692`, `:857`) is not concurrency-safe. Two concurrent writers collide on the PK and the second gets 503 [C]. Memory mode uses `len(list)+1`.

### 6.5 Data integrity and lifecycle

- **Status changes erase history.** Verified: create → `rescheduled` (new datetime) → `attended`. The final row keeps only the last datetime. No event was written on the gap, and the gap stayed `open` after `attended` [V].
- **State diverges across tables.** After closure the gap is `closed_completed` but the matching evaluation remains `due` [V]. The outreach preview then reports `no_open_care_gap` while the evaluation still says `due`. Nothing re-evaluates or links writes to evaluations. This is expected for an append-only evaluation design, but no "evaluation superseded by follow-up" signal exists for Phase 4.
- **Failed transactions:** PG writes roll back on `SQLAlchemyError` [C]. Memory writes have no transactions (gap fields are mutated before the event row is appended).

### 6.6 Security and safety (PulseReach-specific)

| Invariant | Status |
|---|---|
| Clinical eligibility deterministic and source-grounded | ✅ [V] engine pure; rule id/version on every evaluation |
| Programme eligibility ≠ clinical risk/need | ⚠️ engine keeps them distinct; **dashboard merges them** (F-10) |
| Missing history ≠ completed care | ✅ [V] (`unknown`, no gap; 64 unknown-history patients) |
| Scheduled/cancelled/refused referrals ≠ completed | ✅ in engine [V]; ❌ **in gap closure** (F-01: partial screening accepted; DB accepts initiated-then-cancelled referral) |
| Outreach authorisation not inferred from missing consent | ✅ [V] (`contact_consent_absent` 1,267) |
| LLM cannot override rules | ✅ no LLM reachable; flag not wired |
| Unsupported facility availability / priority not presented as fact | ✅ score removed [V]; ⚠️ fallback fabricated facilities and stale "SIMULATED overlay" notice (F-15) |
| Synthetic data not mistaken for real | ✅ `is_synthetic`, `SYNTH-` ids, `(synthetic)` names |
| AuthN/Z, audit identity | ❌ none (P3 / T-20); `recorded_by` is client-asserted |
| SQL injection | ✅ bound parameters everywhere; `DELETE FROM synthetic.{tbl}` uses constant names |
| Secrets | ✅ `DATABASE_URL` `SecretStr`; ⚠️ image build copies `backend/` with no root `.dockerignore` (F-17) |
| Regulatory compliance | Not claimed; no evidence exists |

### 6.7 Performance

All findings are [C], or [V] where timed.
- Memory mode: first dashboard 0.26 s after warm-up; evaluations 0.04 s [V].
- DB dashboard: loads all 29,700 evaluation rows plus all gaps, patients and history into Python on **every request**, and counts rule items via `len(select(RuleItem.rule_id).all())` (`read_repo.py:1594-1632`). This is linear in population with no caching. Acceptable at 550 people, but it is the first bottleneck at real scale.
- People list in DB mode: three batched queries; no N+1 [C].
- Startup: `lru_cache` YAML parse and 550-patient generation per worker process; memory writes are not shared between workers.

---

## 7. Database and migration assessment

| Check | Result |
|---|---|
| Ordering | 0001→0008 linear; `0008.down_revision = "0007"` [C] |
| Fresh upgrade on PostgreSQL | **Succeeds** (CI log: "Running upgrade 0007 -> 0008") [V] |
| Downgrade | Offline SQL renders [V]; live downgrade [U] (CI test `test_upgrade_and_downgrade_preserve_tables_and_data` fails on a stale assertion expecting head `0005`) |
| 0007 frozen DDL | Yes; no `app.models` / `Base.metadata` import [V] |
| 0008 style | Uses `op.create_table` (not ORM-derived, acceptable). Constraint names are double-prefixed by the naming convention → ORM / migration name drift [R] |
| ORM ↔ DB consistency | `alembic check` not run [U] |
| Seeding | Broken CLI (F-02). Reset omits the new table (F-08). The live load test fails before loading (fixture omits `official.region.scad_label`, `test_synthetic_schema.py:497-506`) [V CI] |
| Docker init | No migration or seed step in the image or Compose; the backend in `DATA_SOURCE=db` would serve 503 until seeded manually, which is impossible with the CLI as-is [C] |

---

## 8. Test quality and execution

- **Strong:**
  - T-01 outreach tests cover each blocked reason, ordering and scope.
  - T-02 parametrised referral mapping.
  - T-12 threshold derivation and strict-bool negatives.
  - The 122 data-pipeline tests.
- **Weak or misleading:**
  - `test_postgres_read_repository_matches_memory_repository_on_seeded_subset` uses SQLite and strips CHECK, FK, computed columns, server defaults and NOT NULL (`test_read_repository.py:123-139`). Rows are inserted by hand, not via `load_synthetic_dataset`. It proves query shape only, not PostgreSQL behaviour, constraints or the loader.
  - `test_live_postgres_read_repository_parity` (`:286-297`) assumes a pre-seeded DB and only asserts `total_patients >= 1`. It fails in CI.
  - `test_docker_packaging.py` and `test_ci_workflow.py` assert file contents, not behaviour.
  - `test_migration_0007_uses_frozen_static_ddl` is a string search, not the required round trip.
  - Follow-up tests are memory-only and mutate the cached global dataset, so they are order-dependent [R]. The "good close" case uses a valid screening, so the bad-evidence path (F-01) is untested.
  - No test for `PostgresFollowUpRepository`, the 0008 trigger, or the `outreach_attempted ⇒ contact_consent_id` CHECK.
- **CI failures** (all 8, run `44457754078`) are listed below. These are mostly pre-existing official-phase live tests that were never run before T-14. They assert a pre-0006 database (no clinical or synthetic tables; head `0005`) and are incompatible with CI pre-migrating to head. The teammate enabled them without reconciling them.
  1. `test_clinical_schema::test_live_clinical_migration_views_and_append_only`
  2. `test_db::test_build_engine_without_url_raises` (CI sets `DATABASE_URL`)
  3. `test_official_integrity::test_exactly_the_designed_views_triggers_and_functions_exist`
  4. `test_official_integrity::test_upgrade_and_downgrade_preserve_tables_and_data`
  5. `test_official_loader::test_real_ingestion_populates_the_nine_tables_and_quarantines_nothing`
  6. `test_official_schema::test_schema_placement`
  7. `test_read_repository::test_live_postgres_read_repository_parity`
  8. `test_synthetic_schema::test_live_synthetic_migration` (region fixture)
- **Requirements with no meaningful test:**
  - Gap-closure evidence validity.
  - PG follow-up writes.
  - Synthetic reset after follow-ups.
  - Memory-vs-DB parity for writes.
  - Facility filters / detail (not implemented).
  - Startup fail-fast.
  - LLM-flag behaviour.
  - Concurrency / id collisions.

---

## 9. Runtime and deployment

- **Memory mode:** starts, serves all routes, and returns JSON logs with `X-Request-ID` [V].
- **DB mode:** fails clearly with 503 when unconfigured or unreachable (tested) [V]. It cannot be seeded through the documented CLI (F-02).
- **Startup:** no validation of the rules bundle or SDI data; a missing `RULES_DIR` yields 500 at first request (F-16) [V].
- **Docker (not executed [U]):**
  - The build context is the repo root, and **no root `.dockerignore`** exists, so `COPY backend/` includes `backend/.venv` (189 MB, host-specific binaries), `__pycache__`, and any developer `backend/.env` [C] (F-17).
  - Compose defaults to `DATA_SOURCE=db` with no migrate or seed step, so `/api/v1/rules` would not return 200 as T-17 requires. In DB mode it queries `clinical.rule` on an unmigrated DB, giving 503 [C].
- **Health:** `/health` and `/health/db` are unchanged; there is no readiness check for the rules bundle or seeded run.

---

## 10. Cross-document integration gaps and Phase 4 risks

1. **Naming drift:** Doc 1/Doc 2 use `sort` and `has_open_gap`; the code uses `sort_by` and `has_open_care_gaps`. The frontend on `main` was built against the documents (§12) and must be adapted. `main` and `siri_dev_pr` have not been integrated.
2. **Two follow-up concepts:** `outreach_event` (pre-existing, consent-FK-enforced, has `delivery_status` and `response`) and `care_gap_follow_up_event` (new, no consent FK, `outcome_status="sent"`). Phase 4 will have to choose one. The new table is weaker on the D18 consent guarantee.
3. **No link between workflow writes and evaluation state.** Evaluations are append-only per run. Follow-up writes never produce a new evaluation or reason, so Phase 4 "completion tracking" will show `due` next to `closed_completed`.
4. **Review decisions:** `care_gap_review` exists in the schema; no API. Doc 2 H-8 and §13.2-7 require it for Phase 4.
5. **Origin of review:** Doc 2 §13.3 requires rule-vs-record origin; the backend provides only aggregated "review-flagged = 550".
6. **IDs from `POST /evaluations`** (`SYNTH-EVL-000001`, `SYNTH-GAP-000001`…) collide with persisted IDs of other patients. Verified: patient 201's stored first evaluation is `SYNTH-EVL-010801`, recomputed `SYNTH-EVL-000001`; stored gap `SYNTH-GAP-000521`, recomputed `SYNTH-GAP-000001`. A Phase 4 UI that links a recomputed gap to `/care-gaps/{id}` would open **another patient's gap** (F-18).
7. **Memory vs DB write semantics differ** (F-05), so a demo in memory mode will behave differently from a deployed DB.

---

## 11. Findings (ranked by impact)

| ID | Sev | Requirement | Location | Observed | Expected | Evidence | Recommended correction |
|---|---|---|---|---|---|---|---|
| **F-01** | **Critical** | T-09 "gap `closed_completed` only via documented completion"; brief safety invariant | `followup_repo.py` `MemoryFollowUpRepository.create_follow_up:162-194`; `PostgresFollowUpRepository.create_follow_up:498-557` | Any screening, visit or referral of the patient closes any gap. A `partial` screening of another rule closed `IFHAS-PKG-VISION-40-75` (201, `closed_completed`; evaluation still `due`). In PG, an initiated-then-cancelled referral satisfies the FK. | Evidence must be completed (`complete` / `attended` / `completed` with date), for the same `rule_id` / `rule_version`, compatible with `gap_type`, and dated on or after `identified_date`. | Probe [V]; FK definition `models/synthetic.py:1335-1349` [C] | Move evidence validation into `FollowUpService`, used by both repos; add tests for each invalid evidence kind |
| **F-02** | **High** | T-03 seed CLI | `services/synthetic_generator/seed.py:16,28` | `ImportError: load_clinical_bundle`; also calls `load_synthetic_dataset(..., replace=)`, but the parameter is `reset_existing_run` | Working seed command | [V] | Use `clinical_loader.load.run(engine)` and `reset_existing_run=`; add a CLI smoke test against PG |
| **F-03** | **High** | T-14 | `.github/workflows/ci.yml`; stale live tests | CI red: 8 failed / 264 passed; data-pipeline step skipped | Green CI with live DB | gh run `44457754078` [V] | Isolate per-test DBs or update stale assertions; don't set `DATABASE_URL` globally; fix region fixture; seed before parity test |
| **F-04** | **High** | T-03 golden diff "same responses from both sources for all routes" | `test_read_repository.py:95-139` | Parity on stripped SQLite; no PG parity for writes | Live PG parity incl. writes | [C] | Run parity on PG via the real loader; cover follow-up routes |
| **F-05** | **High** | T-09 | Memory vs PG repos | Divergent validation (memory accepts what PG FKs reject, and PG returns 503 not 422) | One authoritative rule set | [C] + F-01 probe | Shared service validation before persistence; map IntegrityError to 409/422 |
| **F-06** | **High** | Doc 1 DB-4; brief "status update must not erase earlier decisions" | `followup_repo.py` `update_appointment:714-739`, `update_referral:883-914` (and memory equivalents) | In-place overwrite; no event; prior datetime lost | Append-only status history (or a follow-up event per change: `appointment_updated`, `referral_updated` already exist in the CHECK list but are never written) | Probe [V] | Write a `care_gap_follow_up_event` (or a dedicated history table) per create/update in the same transaction |
| **F-07** | **High** | T-09 "event writes visible in care-gap detail"; H-8 | Same | Appointment/referral writes produce no follow-up event; `attended` does not touch the gap | Linked timeline | Probe: `follow_up_events_on_gap` only shows the outreach event [V] | As F-06 |
| **F-08** | **High** | Data lifecycle / reseed | `synthetic_generator/load.py:19-38` | `care_gap_follow_up_event` missing from `DELETE_ORDER`; FK `RESTRICT` | Reset works after follow-ups | [C] (live [U]) | Add the table first in `DELETE_ORDER`; add a live reset-after-write test |
| **F-09** | **Medium** | T-07 / H-6 traceability | `schemas/v1.py:119-137` `CareGapOut` | `closed_by_ifhas_screening_id`, `closed_by_well_child_visit_id`, `closed_by_referral_id` not exposed | Completion evidence visible | Probe keys [V] | Add fields |
| **F-10** | **Medium** | T-08 / H-7; Doc 2 §13.3 | `read_repo.py:643-742` | `review_flagged_patients_count` 550/550; no origin split; non-exclusive status counts (sum 2,208); IFHAS "eligible_or_due" 550 incl. 139 children | Worst-status per person; rule vs record origin; programme eligibility separate from need | Probe [V] | Compute worst status by documented precedence; split review by reason code; separate programme-eligibility from package due/upcoming |
| **F-11** | **Medium** [R] | T-02 + DB vocabulary | `engine.py:192-221`; `status_definitions.yaml:93-102` | New `reason_code`s (`referral_cancelled`, `referral_status_unresolved`, `missing_completion_evidence`) are not in the `clinical.reason_code` vocabulary that `eligibility_evaluation.reason_code` / `evaluation_reason.reason_code` reference by FK | Codes registered in YAML vocabulary | [C]; not triggered by the current dataset [V] | Add codes to YAML (versioned) or reuse `conflicting_records`; add a load test with a cancelled workflow referral |
| **F-12** | **Medium** | T-05 / H-4 | `read_repo.py:360-459` | `reason_detail` is a generic template; engine `detail` discarded; snapshot reconstructed from current data | Engine detail persisted/exposed; snapshot as evaluated | [V] sample output | Persist `FiredReason.detail` (migration) and snapshot at evaluation time |
| **F-13** | **Medium** | D18 consent integrity | `0008:42-57`; `models/synthetic.py:1620-1668` | No FK on `contact_consent_id`; no outcome/evidence CHECKs | Composite FK to `consent.grants_contact` like `outreach_event` | [C] | Add FK + CHECKs in a new migration |
| **F-14** | **Medium** | Simulated-only outreach; D18 | `followup_repo.py:211-217`, `:588-594` | `outcome_status="sent"`; Arabic-preferring patients' attempts suppressed as `template_unavailable` | "recorded/simulated" outcome; template availability separate from authorisation | Probe [V] | Rename outcome; gate on consent/authority only for logging attempts |
| **F-15** | **Medium** | T-11 / H-10 | `read_repo.py:103-107`, `:262-329`; `api/v1.py:392-398` | No filters/detail/coords; hard-coded licence policy; fallback fabricates 3 facilities with `simulated_ifhas_service=True`; notice still claims simulated overlay | As T-11 | Probe [V] | Implement T-11 fully; remove fabricated fallback (fail instead) |
| **F-16** | **Medium** | T-17 fail-fast | `main.py:21-29` | Startup OK, first call 500 when rules missing | Fail at startup | [V] | Parse the bundle (and in db mode check the seeded run) in lifespan |
| **F-17** | **Medium** | T-17 / secrets hygiene | `backend/Dockerfile`; missing root `.dockerignore` | Build would copy `backend/.venv`, caches, and any `backend/.env` | Lean image without secrets | [C] (build [U]) | Root `.dockerignore`; add migrate + seed to Compose |
| **F-18** | **Medium** | D-11 / id stability | `api/v1.py:243,296` | Recomputed ids collide with other patients' stored ids | Non-persisted results clearly namespaced or stable | Probe [V] | Mark ephemeral ids (e.g. `EPHEMERAL-…`) or return stored ids |
| **F-19** | **Medium** | Security (info disclosure) | `read_repo.py` (≈20 handlers), `followup_repo.py:649,738,764,913` | Raw SQLAlchemy errors returned in 503 detail | Generic message, details logged with request id | [C] | Replace with generic detail + `logger.exception` |
| **F-20** | **Medium** | Concurrency | `followup_repo.py:62-69,596-600,692,857` | `MAX()+1` ids; no idempotency | Sequence-backed ids; idempotency key for POST | [C] [R] | DB sequence or UUID-suffix ids |
| **F-21** | **Low** | T-16 | `v1.py:71`; `config.py:26` | `llm_enabled` is not wired; no fallback logging / allow-list validator | As T-16 | [C] | Wire flag; log validator verdicts |
| **F-22** | **Low** | T-12 | `engine.py:241-266` | WCV bounds from visit months, not `WCV-PROG-SCOPE.spec`; hard-coded fallbacks | Read named spec fields; fail if absent | [C] | Read `age_min/age_max`; raise on missing |
| **F-23** | **Low** | T-10 | `data/synthetic/SYNTH-RUN-0001/data_card.md` | Stale counts | Regenerated | [V] | Regenerate |
| **F-24** | **Low** | T-15 | `0008` constraint names | Double-prefixed/hashed names vs ORM names | Consistent names; `alembic check` clean | Offline SQL [V] | Use `op.f()` / bare names; run `alembic check` in CI |
| **F-25** | **Low** | T-18 | `docs/api-contracts.md:147` and test summary | Claims `python -m app.cli.seed` and "187 passed" as the backend result | Accurate docs | [V] | Correct docs |
| **F-26** | **Low** | Architecture | `services/followup/service.py:144-165`; `followup_repo.py:155` | Unsafe defaults (authoritative=True, fabricated gap, `pathway="ifhas"`) | Require inputs; raise | [C] | Remove defaults |

---

## 12. Missing requirements (not implemented at all)

- `GET /facilities/{id}`, facility filters, coordinates and `geo_quality` (T-11 / H-10).
- Recommended-pathway object in care-gap detail (T-07 / H-6).
- Care-gap review write/read API (H-8).
- `/open-questions` (H-12).
- Applicability marker (H-13).
- Rule-vs-record review origin split (H-7).
- Startup fail-fast (T-17).
- LLM flag wiring, fallback logging and allow-list validator (T-16).
- Migration round-trip test and `alembic check` (T-15).
- Data card regeneration (T-10).
- Working seed CLI (T-03).
- PG tests for follow-up writes (T-09).
- P3: T-19, T-20 (not counted against readiness).

---

## 13. Recommended remediation order

1. **F-01 / F-05:** centralise gap-closure evidence validation in `FollowUpService` and use it from both repositories. Add negative tests for partial or not-attended screenings, mismatched rules, and pending, cancelled or declined referrals.
2. **F-02, F-08, F-03, F-04:** fix the seed CLI and the reset order, make CI green, and run real PostgreSQL parity tests, including all write routes and the 0008 trigger and CHECKs.
3. **F-06 / F-07 / F-13 / F-14:** append-only lifecycle events for every appointment and referral change, written in the same transaction; a consent FK on follow-up events; a non-misleading outcome vocabulary. Decide whether `outreach_event` or `care_gap_follow_up_event` is the Phase 4 outreach log.
4. **F-10, F-09, F-12, F-18:** truthful aggregates (worst status, origin split, programme eligibility separated from need); expose closing evidence; persist the engine's detail and snapshot; namespace ephemeral ids.
5. **F-11:** register the new reason codes in versioned YAML.
6. **F-19 / F-20:** stop leaking error details; use sequence-backed ids and add idempotency.
7. **T-11, H-8 review API, H-12, H-13, F-15, F-16, F-17**, then the Low items.

---

## 14. Readiness for Phase 4

**Highest-priority fixes required before Phase 4 starts:**
1. F-01: completion evidence validation (Critical).
2. F-02 + F-08: working seed and reseed for `DATA_SOURCE=db`.
3. F-03 + F-04: green CI with live PostgreSQL tests covering `PostgresFollowUpRepository`.
4. F-06 / F-07: append-only history for appointment and referral changes, linked to the care gap.
5. F-13 / F-14: consent FK and an honest outcome vocabulary on follow-up events.

**What can proceed now:** frontend integration of the read surfaces in memory mode:
- Population (with the F-10 caveat: do not show "550 need review").
- People.
- Person history, consents and evidence (label snapshots "current record").
- Gated outreach preview.
- Rules.

**What must wait for the fixes above:**
- Any follow-up, completion or outcome UI.
- Any DB-backed deployment.

**Not claimed:** clinical validation, regulatory or data-residency compliance, production security. The live behaviour of the DB write path, the downgrade path and the Docker image is **unverified** in this audit (§4).

---

*Method note.* All probes ran in-process against `DATA_SOURCE=memory`. Memory-mode writes affected only the probe process's cache; no file or database was written. Probe scripts and logs lived in `/tmp`. A disposable PostgreSQL container was started and then removed; it never became reachable. CI evidence was read with `gh run view`. No application code, test, migration, dependency or configuration was modified, and nothing was committed or pushed.
