# PulseReach — agent notes

## Backend verification (`backend/`)

- Offline suite: `.venv/bin/python -m pytest -q -p no:cacheprovider` (PostgreSQL tests skip without `TEST_DATABASE_URL`).
- Live PostgreSQL suite: start a disposable server, e.g.
  `docker run -d --rm --name pulsereach-test-pg -e POSTGRES_DB=pulsereach_test -e POSTGRES_USER=pulsereach -e POSTGRES_PASSWORD=pulsereach_test_password -p 55432:5432 postgres:17`,
  then run pytest with `TEST_DATABASE_URL` and `DATABASE_URL` set to
  `postgresql+psycopg://pulsereach:pulsereach_test_password@127.0.0.1:55432/pulsereach_test` (~15 min).
- Data pipeline: `cd data-pipeline && ../backend/.venv/bin/python -m pytest -q -p no:cacheprovider`.
- Fresh DB bootstrap: `python -m app.db.init --seed`; image: `docker build -f backend/Dockerfile .` from the repo root.

## Environment gotcha (macOS + Podman)

If PostgreSQL round trips through the published port take hundreds of ms, Podman's `gvproxy`
is wedged (high CPU). Restart the machine with the same Podman install that created it
(`/opt/podman/bin/podman machine stop && /opt/podman/bin/podman machine start`); a mismatched
Homebrew `podman` fails to start the `libkrun` machine.
