# PulseReach — GCP Deployment Runbook (hackathon, ~10 days, synthetic data only)

Not a production or clinical deployment. **Deployed 2026-11-20** in project `pulsereach-hackathon-2026`
(number `871361479060`), region **`asia-south1`** for everything. Pass `--region`/`--location`
explicitly (local gcloud defaults differ: `compute/region=us-central1`).

| | URL |
|---|---|
| Web UI | <https://pulsereach-web-871361479060.asia-south1.run.app> |
| API | <https://pulsereach-api-871361479060.asia-south1.run.app> |
| Liveness / DB readiness | `/health` · `/health/db` (503 when the DB is unreachable) |

Cloud Run URLs are derived from service name + project number + region: redeploys never change them.

## 1. Resources

| Piece | Resource | Configuration |
|---|---|---|
| Backend (FastAPI) | Cloud Run service `pulsereach-api` | `backend/Dockerfile` (context = repo root); 1 vCPU / 1 GiB, min 0 / max 2, concurrency 40, timeout 60 s, startup CPU boost |
| Frontend (Next.js) | Cloud Run service `pulsereach-web` | `frontend/Dockerfile` (multi-stage, `output: "standalone"`, Node 22 slim, non-root); 1 vCPU / 512 MiB, min 0 / max 2 |
| Migrate / seed / roles | Cloud Run job `pulsereach-init` | same backend image; runs once on demand, never from the service |
| Database | Cloud SQL `pulsereach-db` | PostgreSQL 16, Enterprise, `db-g1-small`, zonal, 10 GB SSD + auto-increase, daily backups 20:30 UTC (7 kept), PITR (3 days of logs), deletion protection, `ssl-mode=TRUSTED_CLIENT_CERTIFICATE_REQUIRED`, no authorized networks (only the Cloud SQL connector can connect) |
| Database `pulsereach` | users | `pulsereach_owner` (Cloud SQL built-in user; owns the schema; used **only** by the init job) · `pulsereach_app` (runtime login role created by `app.db.runtime_role`: SELECT/INSERT/UPDATE/DELETE on the app schemas, read-only `public`, no DDL/TRUNCATE/CREATEROLE) |
| Images | Artifact Registry `asia-south1-docker.pkg.dev/pulsereach-hackathon-2026/pulsereach` | `backend:<tag>`, `web:<tag>` |
| AI | Gemini via **Vertex AI express** endpoint | project API key "API key 1" (restricted to `aiplatform.googleapis.com`), model `gemini-3.5-flash-lite` |

### Secrets (Secret Manager, automatic replication)

| Secret | Contents | Readable by |
|---|---|---|
| `pulsereach-database-url` | `postgresql+psycopg://pulsereach_app:…@/pulsereach?host=/cloudsql/pulsereach-hackathon-2026:asia-south1:pulsereach-db` | `pulsereach-api`, `pulsereach-init` |
| `pulsereach-db-owner-url` | same, as `pulsereach_owner` | `pulsereach-init` only |
| `pulsereach-gemini-api-key` | the Vertex AI express key | `pulsereach-api` only |
| `pulsereach-demo-password` | shared password of the synthetic demo accounts | `pulsereach-init` only (and project owners) |

Passwords were generated inside a pipe (`openssl rand`) and never printed. Secrets are bound per
secret (`roles/secretmanager.secretAccessor`), never project-wide.

### Service accounts (no JSON keys)

| Account | Roles |
|---|---|
| `pulsereach-api@` | `roles/cloudsql.client` (project); accessor on `pulsereach-database-url`, `pulsereach-gemini-api-key` |
| `pulsereach-init@` | `roles/cloudsql.client`; accessor on `pulsereach-db-owner-url`, `pulsereach-database-url`, `pulsereach-demo-password` |
| `pulsereach-web@` | none (serves static/SSR pages only) |
| `pulsereach-build@` | `roles/artifactregistry.writer`, `roles/logging.logWriter`, `roles/storage.objectViewer` (Cloud Build source tarballs) |

The default compute service account (which has Editor) is not used by any PulseReach workload.

### Monitoring and cost controls

- Billing budget **"PulseReach hackathon (Rs 20k)"**: ₹20,000 on this project, alerts at 25/50/90/100 %
  actual and 100 % forecasted spend (an alert, not a cap).
- Uptime checks `pulsereach-web` (`/`) and `pulsereach-api` (`/health/db`), every 15 min from 3 regions.
- Alert policies "PulseReach uptime check failing" and "PulseReach Cloud Run 5xx" (> 5 in 5 min),
  notifying the email channel "PulseReach owner email".

## 2. Backend environment (production)

| Variable | Value |
|---|---|
| `AUTH_MODE` | `users` (**never `legacy`**) |
| `DATA_SOURCE` | `db` |
| `DATABASE_URL` | secret `pulsereach-database-url` (runtime role) |
| `CORS_ORIGINS` | `https://pulsereach-web-871361479060.asia-south1.run.app` only |
| `TRUSTED_PROXY_HOPS` | `1` |
| `SELF_REGISTRATION_ENABLED` | `false` |
| `ALLOW_UNPROTECTED_WRITES` | `false` |
| `LOG_LEVEL` | `INFO` |
| `DB_MAX_OVERFLOW` | `5` (2 instances × (5 + 5) connections, within `db-g1-small` limits) |
| `LLM_ENABLED` / `LLM_PROVIDER` | `true` / `gemini` |
| `GEMINI_API_KEY` | secret `pulsereach-gemini-api-key` |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` (leave `LLM_MODEL` unset; it overrides) |
| `GEMINI_BASE_URL` | `https://aiplatform.googleapis.com/v1/publishers/google` (Vertex AI express: same `models/{model}:generateContent` + `x-goog-api-key` contract). With a Google AI Studio key, unset it (default `generativelanguage` v1beta). |
| `LLM_MAX_OUTPUT_TOKENS` | `1024` |

Not set: `DEMO_IDENTITY_SEED`, `NEXT_PUBLIC_ALLOW_LEGACY_BACKEND`, `LLM_API_KEY`, `WRITE_API_KEY`.
Frontend: only the build arg `NEXT_PUBLIC_API_URL=https://pulsereach-api-871361479060.asia-south1.run.app`
(public URL; the Dockerfile refuses non-`https://` values). No AI setting or secret reaches the frontend.
`/docs` and `/openapi.json` stay public (no data; every API route needs a token) — accepted limitation.

## 3. Build and deploy

```bash
P=pulsereach-hackathon-2026; R=asia-south1; PN=871361479060
TAG=$(git rev-parse --short HEAD)-$(date -u +%Y%m%d%H%M)
AR=$R-docker.pkg.dev/$P/pulsereach
BUILD_SA=projects/$P/serviceAccounts/pulsereach-build@$P.iam.gserviceaccount.com
BUILD_OPTS="--project=$P --region=$R --service-account=$BUILD_SA --default-buckets-behavior=regional-user-owned-bucket --ignore-file=.dockerignore"

# backend (from repo root; .dockerignore keeps secrets, tests and frontend out of the upload)
cat > /tmp/cb-backend.yaml <<EOF
steps: [{name: gcr.io/cloud-builders/docker, args: [build, -f, backend/Dockerfile, -t, $AR/backend:$TAG, .]}]
images: [$AR/backend:$TAG]
options: {logging: CLOUD_LOGGING_ONLY, machineType: E2_HIGHCPU_8}
EOF
gcloud builds submit . --config=/tmp/cb-backend.yaml $BUILD_OPTS

# frontend (from frontend/)
cat > /tmp/cb-web.yaml <<EOF
steps: [{name: gcr.io/cloud-builders/docker, args: [build, --build-arg, NEXT_PUBLIC_API_URL=https://pulsereach-api-$PN.$R.run.app, -t, $AR/web:$TAG, .]}]
images: [$AR/web:$TAG]
options: {logging: CLOUD_LOGGING_ONLY, machineType: E2_HIGHCPU_8}
EOF
(cd frontend && gcloud builds submit . --config=/tmp/cb-web.yaml $BUILD_OPTS)
```

`package-lock.json` resolves through a private npm mirror; `frontend/Dockerfile` rewrites those
URLs to `registry.npmjs.org` inside the build (same tarballs, integrity-checked).

**Init job** (idempotent: migrates, loads the official register and seeds only when empty, then
(re)applies the runtime role grants and the synthetic demo identities; never reseeds):

```bash
# take an on-demand backup first
gcloud sql backups create --instance=pulsereach-db --project=$P --description="pre-migration $TAG"
gcloud run jobs update pulsereach-init --region=$R --project=$P --image=$AR/backend:$TAG
gcloud run jobs execute pulsereach-init --region=$R --project=$P --wait
```

The job (created once) runs
`sh -c "python -m app.db.init --seed && python -m app.db.runtime_role && python -m app.services.identity seed-demo"`
with `DATABASE_URL=pulsereach-db-owner-url`, `RUNTIME_DATABASE_URL=pulsereach-database-url`,
`DEMO_IDENTITY_PASSWORD=pulsereach-demo-password`, `AUTH_MODE=users`, `DATA_SOURCE=db`, 2 vCPU / 2 GiB,
30 min timeout, no retries. Because the password comes from the secret, the job log shows
`<DEMO_IDENTITY_PASSWORD>`, never a password. Verify the revision:
`gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="pulsereach-init"' --project=$P --limit=20`.

**Services** (deploy the backend and the frontend independently; env vars persist across `--image` updates):

```bash
gcloud run deploy pulsereach-api --region=$R --project=$P --image=$AR/backend:$TAG
gcloud run deploy pulsereach-web --region=$R --project=$P --image=$AR/web:$TAG
```

First-time flags used for the API: `--service-account=pulsereach-api@$P.iam.gserviceaccount.com
--add-cloudsql-instances=$P:$R:pulsereach-db --allow-unauthenticated --cpu=1 --memory=1Gi
--min-instances=0 --max-instances=2 --concurrency=40 --timeout=60 --cpu-boost
--set-secrets=DATABASE_URL=pulsereach-database-url:latest,GEMINI_API_KEY=pulsereach-gemini-api-key:latest
--set-env-vars=<§2>`. Web: `--service-account=pulsereach-web@… --allow-unauthenticated --port=8080
--cpu=1 --memory=512Mi --min-instances=0 --max-instances=2 --cpu-boost`.

The backend refuses to start if the rule bundle is missing or the DB holds no matching seeded load
(`app/core/startup.py`), so a broken revision never receives traffic; Cloud Run keeps the previous
revision serving.

## 4. Demo accounts

`{admin,manager,coordinator,clinician,patient}.{a,b}@demo.pulsereach.invalid` (organizations
`demo-org-a` / `demo-org-b`; patients `SYNTH-PAT-000001` / `SYNTH-PAT-000024`). One shared password,
read privately by an owner — never paste it into documents, chat or tickets:

```bash
gcloud secrets versions access latest --secret=pulsereach-demo-password --project=$P
```

5 wrong passwords lock an account for 15 minutes. To rotate: add a secret version, then delete the
accounts' passwords via the admin UI or set new ones (seed-demo never changes existing passwords).

## 5. Smoke tests

```bash
API=https://pulsereach-api-871361479060.asia-south1.run.app
curl -fsS $API/health; curl -fsS $API/health/db
curl -s -o /dev/null -w '%{http_code}\n' $API/api/v1/patients                     # 401
curl -s -o /dev/null -w '%{http_code}\n' -X OPTIONS -H 'Origin: https://evil.example' \
  -H 'Access-Control-Request-Method: GET' $API/api/v1/me                          # 400
PW=$(gcloud secrets versions access latest --secret=pulsereach-demo-password --project=$P)
TOKEN=$(curl -fsS -X POST $API/api/v1/auth/login -H 'Content-Type: application/json' \
  -d "{\"email\":\"manager.a@demo.pulsereach.invalid\",\"password\":\"$PW\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'); unset PW
curl -fsS -H "Authorization: Bearer $TOKEN" $API/api/v1/ai/status   # availability, last_provider_error
```

Verified on 2026-11-20: health/db ok; 401 without a token and for bad credentials; all five roles
log in; org A/B managers get 404 for the other organization's patient; patient and admin tokens
get 403 on `/patients`; CORS refuses foreign origins and allows the web origin; AI status
`last_call_succeeded`; the web bundle targets the HTTPS API and contains no `localhost` URL or key.

## 6. Logs and diagnosis

```bash
gcloud run services logs read pulsereach-api --region=$R --project=$P --limit=100
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="pulsereach-api" AND severity>=ERROR' --project=$P --limit=50
gcloud logging read 'resource.type="cloud_run_revision" AND jsonPayload.request_id="<X-Request-ID>"' --project=$P   # one request
```

Every response carries `X-Request-ID`; the HTTP log line records method, path, status and duration
(no bodies, tokens or patient content). Typical failures: `/health/db` 503 → instance stopped or the
`DATABASE_URL` secret wrong; startup "does not match the deployed rule bundle" → rules changed, run
the init job (and see §7 for reseeding); AI `last_provider_error=auth` → key revoked or restricted to
the wrong API; `bad_request` → model name.

## 7. Rollback and recovery

```bash
gcloud run revisions list --service=pulsereach-api --region=$R --project=$P     # last Ready revision = last healthy
gcloud run services update-traffic pulsereach-api --to-revisions=<previous>=100 --region=$R --project=$P
```

Same for `pulsereach-web`. Old revisions are kept until deleted. **Disable Gemini** without touching
the app (deterministic templates take over):
`gcloud run services update pulsereach-api --region=$R --project=$P --update-env-vars=LLM_ENABLED=false`.

Schema rollback is not automatic (destructive downgrades are refused unless
`-x allow_data_loss=true`). For a failed migration or bad data: restore the pre-migration backup or a
PITR point to a **new** instance (`gcloud sql instances clone pulsereach-db pulsereach-db-restore
--point-in-time=<RFC3339> --project=$P`, or `gcloud sql backups restore <id>
--restore-instance=<new-instance>`), then repoint both DB URL secrets and redeploy. Never run the
reseed command (`app.services.synthetic_generator.seed`) against the judging database — it deletes
follow-up, workflow and AI audit history. Restores and reseeds need explicit approval.

## 8. Gemini key

The key in use is the existing project API key "API key 1" (Vertex AI express, restricted to
`aiplatform.googleapis.com`), copied into `pulsereach-gemini-api-key` straight from
`gcloud services api-keys get-key-string … | gcloud secrets create … --data-file=-` (never printed).
It never appears in source, `.env.example`, images, build args, `--set-env-vars`, the frontend or logs.

Rotate: create a new key (console → APIs & Services → Credentials, restrict to `aiplatform.googleapis.com`),
`gcloud services api-keys get-key-string <NEW_UID> --format='value(keyString)' | tr -d '\n' |
gcloud secrets versions add pulsereach-gemini-api-key --data-file=- --project=$P`, then
`gcloud run services update pulsereach-api --region=$R --project=$P --update-secrets=GEMINI_API_KEY=pulsereach-gemini-api-key:latest`,
check `/ai/status`, then disable the old secret version and delete the old key.

To use a Google AI Studio key instead: store it with `read -rs K; printf '%s' "$K" | gcloud secrets
versions add pulsereach-gemini-api-key --data-file=-; unset K`, and
`--remove-env-vars=GEMINI_BASE_URL` on the API. Details: `docs/ai-gemini.md`.

## 9. Cost (list prices, asia-south1, 10 days)

| Item | Estimate | Idle cost? |
|---|---|---|
| Cloud SQL `db-g1-small` (~$0.035–0.042/h) + 10 GB SSD + backups/PITR logs | ≈ ₹800–1,100 | **yes** (runs 24/7) |
| Cloud Run API + web, scale to zero, ≤ 2 instances each | ≈ ₹0–800 | no (uptime checks wake the API ~every 15 min; negligible) |
| Artifact Registry (~1 GB images) | ≈ ₹10–30 | yes (storage) |
| Secret Manager (4 secrets), Cloud Build (few builds), Logging/Monitoring (free tiers) | ≈ ₹0–200 | minimal |
| Gemini `gemini-3.5-flash-lite` (judge-scale, ≤ 1024 output tokens, ≤ 3 attempts) | ≈ ₹0–500 | no |
| **Total** | **≈ ₹1,000–2,700** (budget ₹20,000) | |

Risks: max instances bound Cloud Run; Gemini spend scales with use (disable via §7 if alerts fire).

## 10. Shutdown and cleanup after judging (requires approval; irreversible)

```bash
gcloud run services delete pulsereach-web pulsereach-api --region=$R --project=$P
gcloud run jobs delete pulsereach-init --region=$R --project=$P
gcloud sql instances patch pulsereach-db --no-deletion-protection --project=$P
gcloud sql instances delete pulsereach-db --project=$P        # deletes automated backups too
gcloud secrets delete pulsereach-database-url --project=$P
gcloud secrets delete pulsereach-db-owner-url --project=$P
gcloud secrets delete pulsereach-gemini-api-key --project=$P
gcloud secrets delete pulsereach-demo-password --project=$P
gcloud artifacts repositories delete pulsereach --location=$R --project=$P
for sa in api init web build; do gcloud iam service-accounts delete pulsereach-$sa@$P.iam.gserviceaccount.com --project=$P; done
gcloud monitoring uptime list-configs --project=$P   # delete pulsereach-web / pulsereach-api
# also: the two alert policies, the budget (Billing → Budgets), and the API key if no longer needed
```

To pause cheaply instead: `gcloud sql instances patch pulsereach-db --activation-policy=NEVER --project=$P`
(storage is still billed; the API then reports `/health/db` 503).
