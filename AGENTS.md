# PulseReach — agent notes

## Backend verification (`backend/`)

- Offline suite: `.venv/bin/python -m pytest -q -p no:cacheprovider` (PostgreSQL tests skip without `TEST_DATABASE_URL`).
- Live PostgreSQL suite: start a disposable server, e.g.
  `docker run -d --rm --name pulsereach-test-pg -e POSTGRES_DB=pulsereach_test -e POSTGRES_USER=pulsereach -e POSTGRES_PASSWORD=pulsereach_test_password -p 55432:5432 postgres:17`,
  then run pytest with `TEST_DATABASE_URL` and `DATABASE_URL` set to
  `postgresql+psycopg://pulsereach:pulsereach_test_password@127.0.0.1:55432/pulsereach_test` (~15 min).
- Data pipeline: `cd data-pipeline && ../backend/.venv/bin/python -m pytest -q -p no:cacheprovider`.
- Fresh DB bootstrap: `python -m app.db.init --seed`; image: `docker build -f backend/Dockerfile .` from the repo root.

## AI layer (`backend/app/services/ai/`)

- Tests: `tests/test_ai_service.py`, `tests/test_ai_explanations.py`, `tests/test_ai_outreach.py` (providers mocked via `httpx.post`; no live calls).
- Outreach drafts: all consent/channel/language/next-step checks live in `app/services/outreach/drafting.py` and run before any
  provider call; channel permission is derived from the person's `preferred_channel` (consent has no channel/expiry columns).
- Live provider needs `LLM_ENABLED=true`, `LLM_PROVIDER` (`openai_compatible`|`anthropic`), `LLM_MODEL`, `LLM_API_KEY`
  (optional `LLM_BASE_URL`); check `GET /api/v1/ai/status` (`availability`) and `GET /api/v1/ai/audit`.
- Bump the prompt version in `prompts.py` whenever a template's wording changes.

## Environment gotcha (macOS + Podman)

If PostgreSQL round trips through the published port take hundreds of ms, Podman's `gvproxy`
is wedged (high CPU). Restart the machine with the same Podman install that created it
(`/opt/podman/bin/podman machine stop && /opt/podman/bin/podman machine start`); a mismatched
Homebrew `podman` fails to start the `libkrun` machine.

Docker builds through the forwarded socket also wedge `gvproxy` (build context uploads at ~0.5 MB/min).
Build inside the VM instead, then start Compose without building:
`/opt/podman/bin/podman machine ssh "cd $PWD && podman build -f backend/Dockerfile -t prdeploy-backend:latest . && podman tag prdeploy-backend:latest prdeploy-db-init:latest"`,
then `docker compose -p prdeploy --env-file <env> -f infrastructure/docker-compose.yml up -d --no-build`.
