# PulseReach — agent notes

## Backend verification (`backend/`)

- Offline suite: `.venv/bin/python -m pytest -q -p no:cacheprovider` (PostgreSQL tests skip without `TEST_DATABASE_URL`).
- Live PostgreSQL suite: start a disposable server, e.g.
  `docker run -d --rm --name pulsereach-test-pg -e POSTGRES_DB=pulsereach_test -e POSTGRES_USER=pulsereach -e POSTGRES_PASSWORD=pulsereach_test_password -p 55432:5432 postgres:17`,
  then run pytest with `TEST_DATABASE_URL` and `DATABASE_URL` set to
  `postgresql+psycopg://pulsereach:pulsereach_test_password@127.0.0.1:55432/pulsereach_test` (~15 min).
- Data pipeline: `cd data-pipeline && ../backend/.venv/bin/python -m pytest -q -p no:cacheprovider`.
- Fresh DB bootstrap: `python -m app.db.init --seed`; image: `docker build -f backend/Dockerfile .` from the repo root.

## Identity / RBAC / portal (`backend/app/core/auth.py`, `app/services/identity/`, migration 0011)

- `AUTH_MODE=users` is the default; `tests/conftest.py` sets `AUTH_MODE=legacy` + cheap scrypt for the
  pre-existing regression suites. Users-mode suites import fixtures from `tests/identity_fixtures.py`
  (`world`): `test_auth.py`, `test_rbac.py`, `test_tenant_isolation.py`, `test_patient_portal.py`,
  `test_localization.py`, `test_audit_events.py`; live PG: `test_identity_live_pg.py`.
- Every `/api/v1` route must declare `require(...)`/`authenticated`/`public_endpoint` (meta-test in `test_rbac.py`).
- Memory mode keeps identity data in an in-process SQLite DB (`store.py`); never nest two `identity_session()`s.
- Identity tables use their own MetaData (`app/models/identity.py`); keep migration 0011 DDL in sync (live test compares).
- New user-facing strings go in `app/core/i18n.py` MESSAGES with both `en` and `ar` (catalog test).
- Demo users: `python -m app.services.identity seed-demo`; first admin: `create-admin`.

## AI layer (`backend/app/services/ai/`)

- Tests: `tests/test_ai_service.py`, `tests/test_ai_explanations.py`, `tests/test_ai_outreach.py` (providers mocked via `httpx.post`; no live calls).
- Outreach drafts: all consent/channel/language/next-step checks live in `app/services/outreach/drafting.py` and run before any
  provider call; channel permission is derived from the person's `preferred_channel` (consent has no channel/expiry columns).
- Live provider needs `LLM_ENABLED=true`, `LLM_PROVIDER` (`openai_compatible`|`anthropic`), `LLM_MODEL`, `LLM_API_KEY`
  (optional `LLM_BASE_URL`); check `GET /api/v1/ai/status` (`availability`) and `GET /api/v1/ai/audit`.
- Bump the prompt version in `prompts.py` whenever a template's wording changes.

## Programme summary (`app/services/programmes.py`, `GET /api/v1/programmes/{pathway}/summary`)

- Pure builder + repository inputs (`list_programme_members`, `list_programme_gaps`, `evaluation_reference_dates`; memory and PG).
  Tests: `tests/test_programme_summary.py`; live PG parity: `tests/test_programme_summary_live_pg.py`.
- `/patients` with `pathway` scopes `has_open_care_gaps`/`history_status` to that programme (both repositories).
- Trends are drawn only when persisted evaluation runs cover the previous window; previous counts are `null` otherwise.

## Population intelligence (BE-33, `backend/app/services/population/`, migration 0012)

- Tests: `tests/test_population_engine.py` (pure engine, privacy, alert sync), `tests/test_population_api.py`
  (users mode, `world` fixture; reset with `reset_population_store()` + `get_population_service().reset()`);
  live PG: `tests/test_population_live_pg.py` (memory/PostgreSQL facts parity).
- `facts.py` has two providers (PostgreSQL `GROUP BY` and memory) with identical definitions; change both and
  keep the parity test green. The engine (`engine.py`) is pure; privacy is applied only in `views.py`/`privacy.py`.
- `population` tables use their own MetaData (`app/models/population.py`); keep migration 0012 DDL in sync.
  Memory mode stores them in a separate in-process SQLite DB (`population/store.py`).
- New synthetic tables must be added to `load.DELETE_ORDER`, `seed._RECONCILED_TABLES` and the schema tests.
- Condition scenarios live in `synthetic_generator/conditions.py` on a separate RNG stream; never change the
  main generator's random sequence.

## Gemini provider and AI copilot (migration 0015, docs/ai-gemini.md)

- `LLM_ENABLED=true LLM_PROVIDER=gemini GEMINI_API_KEY=…` (key only in untracked `backend/.env` or Secret Manager
  `pulsereach-gemini-api-key`; never in `.env.example`). `GeminiProvider` in `provider.py`; retries only timeouts/network/429/5xx
  (daily quota 429 → `quota_exhausted`, no retry). Tests: `tests/test_gemini_provider.py` (httpx mocked; patch `provider._sleep`).
- Free-text questions: `guardrails.screen_question` (emergency / prompt_injection / other_person / clinical_question → fixed answer,
  no provider call); output guard `validate_portal_answer`; question text never stored (length + SHA-256 only).
- Portal-wide guide `POST /api/v1/portal/assistant` (feature `portal_assistant`, prompt `portal-assistant-v1`); recommendation
  assistant adds topics `meaning`/`question` (prompt `patient-assistant-v2`).
- Staff copilot `app/api/copilot.py` + `app/services/copilot.py` (feature `staff_copilot`, prompt `staff-copilot-v1`, strict JSON via
  `parse_copilot_output`): `/ai/copilot/patients/{id}/coordination` (followups.read), `/clinical-review` (ai.explain+care_gaps.read),
  `/ai/copilot/population` (insights.read). Tests: `tests/test_staff_copilot.py`. Frontend: `components/copilot/`, `components/portal/portal-assistant.tsx`.
- Head migration is `0015`.

## Patient portal assistant (Phase 9, migration 0014)

- `POST /api/v1/portal/recommendations/{id}/assistant` `{topic: why|meaning|next_steps|prepare_questions|appointments|question}`:
  facts/fallback in `app/services/portal_assistant.py`, generation via `AIService.patient_assistant` (prompt
  `patient-assistant-v2`, guard `validate_portal_answer`). Only de-identified portal facts reach the model.
  AI audit feature `patient_assistant` (migration 0014 widens `ck_ai_audit_record_feature`). Tests: `tests/test_patient_assistant.py`.
- Portal `format_datetime` renders UTC with a ` UTC` suffix (matches staff views).
- Frontend: `/portal/*` requests issued before `allowPortalRequests(true)` wait in `waitForPortal` (child effects run before
  the AuthProvider effect; prod builds otherwise hang the portal). Regression test in `lib/api/client.test.ts`.
- Browser QA without the dev lock: `NEXT_PUBLIC_API_URL=http://localhost:8031 npm run build && npx next start -p 3130`.

## Environment gotcha (macOS + Podman)

If PostgreSQL round trips through the published port take hundreds of ms, Podman's `gvproxy`
is wedged (high CPU). Restart the machine with the same Podman install that created it
(`/opt/podman/bin/podman machine stop && /opt/podman/bin/podman machine start`); a mismatched
Homebrew `podman` fails to start the `libkrun` machine.

Without restarting the machine (e.g. a running `prdeploy` stack), run the live suite *inside* the VM
next to a disposable DB (~0.3 ms round trips, full suite ~7 min), reusing an image with the pinned deps:
`docker run --rm --network container:pulsereach-test-pg -v "$PWD":/repo:ro -w /repo/backend -e PYTHONDONTWRITEBYTECODE=1
-e PULSE_REACH_REPO_ROOT=/repo -e RULES_DIR=/repo/data-pipeline/rules -e DATA_DIR=/repo/data -e TEST_DATABASE_URL=… -e DATABASE_URL=…
--entrypoint python prdeploy-backend:latest -m pytest -q -p no:cacheprovider` (URLs use `127.0.0.1:5432` inside the namespace).
Live fixtures that set `DATA_SOURCE=db` must clear `get_identity_engine`/`get_population_engine` caches on teardown
(`test_live_backend_completion._clear_store_engines`), or later memory-mode suites error.

Deployment: `docs/deployment-gcp.md`; behind Cloud Run set `TRUSTED_PROXY_HOPS=1` (not uvicorn `--forwarded-allow-ips='*'`).

Docker builds through the forwarded socket also wedge `gvproxy` (build context uploads at ~0.5 MB/min).
Build inside the VM instead, then start Compose without building:
`/opt/podman/bin/podman machine ssh "cd $PWD && podman build -f backend/Dockerfile -t prdeploy-backend:latest . && podman tag prdeploy-backend:latest prdeploy-db-init:latest"`,
then `docker compose -p prdeploy --env-file <env> -f infrastructure/docker-compose.yml up -d --no-build`.

## Coordination (Phase 5, migration 0013)

- Backend: task `priority`, `contact_attempt` events, `GET /follow-up-tasks/summary`, `GET /care-team`,
  `GET /facility-service-profiles`, appointment filters. Tests: `tests/test_coordination.py` (memory, users mode);
  live PG: `test_identity_live_pg.py::test_task_priority_contact_attempts_and_summary_in_db_mode`,
  `test_live_backend_completion.py` appointment/service-profile parity. Head revision is now `0014`.
- FastAPI dependency classes cannot resolve `from __future__` string annotations (classes have no `__globals__`):
  use a function dependency (see `task_filters` in `app/api/engagement.py`).
- Frontend: `lib/coordination/` (model + hooks; writes call `invalidateCoordination()` so every coordination read
  refetches), `components/coordination/`, profile section `coordination-section.tsx`. Tests:
  `components/coordination/coordination.test.tsx`, `lib/coordination/*.test.ts*`; fixtures in `test/fixtures.ts`
  (`resetCoordinationFixtures()`). Lint forbids sync setState in effects and `Date.now()` in render.

## Frontend localization (`frontend/lib/i18n/`, `docs/localization-and-language-support.md` §6)

- New UI strings go in `lib/i18n/messages/en.ts` *and* `ar.ts` (typed; `lib/i18n/catalog.test.ts` checks parity,
  placeholders and untranslated entries). Terms: `docs/localization-glossary.md`.
- In render use `useLocale()`/`useT()` and pass the translator to label helpers; module `t()` only in handlers/async
  (hydration of streamed boundaries happens after the locale switch).
- Logical CSS only (`ms-/pe-/start-/end-/border-e/text-start`); add converted files to `CONVERTED` in `catalog.test.ts`.
- Tests: `lib/i18n/catalog.test.ts`, `components/i18n/language.test.tsx`; `test/setup.ts` resets the locale.
- Visual QA in Arabic: set `localStorage["pulsereach-locale"]="ar"` (plus `pulsereach-locale-unsynced=1` to keep it over
  the account preference at sign-in). Ports 3100/8001/8011 may already be in use by other local stacks.
