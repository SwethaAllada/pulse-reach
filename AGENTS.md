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

## Environment gotcha (macOS + Podman)

If PostgreSQL round trips through the published port take hundreds of ms, Podman's `gvproxy`
is wedged (high CPU). Restart the machine with the same Podman install that created it
(`/opt/podman/bin/podman machine stop && /opt/podman/bin/podman machine start`); a mismatched
Homebrew `podman` fails to start the `libkrun` machine.

Docker builds through the forwarded socket also wedge `gvproxy` (build context uploads at ~0.5 MB/min).
Build inside the VM instead, then start Compose without building:
`/opt/podman/bin/podman machine ssh "cd $PWD && podman build -f backend/Dockerfile -t prdeploy-backend:latest . && podman tag prdeploy-backend:latest prdeploy-db-init:latest"`,
then `docker compose -p prdeploy --env-file <env> -f infrastructure/docker-compose.yml up -d --no-build`.
