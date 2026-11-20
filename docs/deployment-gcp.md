# PulseReach — GCP Deployment Runbook (hackathon, ~10 days, synthetic data only)

Not a production or clinical deployment. Target project: `pulsereach-hackathon-2026`
(billing enabled; Cloud Run, Cloud SQL Admin, Secret Manager, Artifact Registry and Cloud Build
APIs enabled; **no services, jobs, SQL instances, secrets or registries existed on 2026-11-20**).
Nothing in this document has been executed against GCP yet — every step needs explicit approval.

## 1. Architecture (smallest that fits)

| Piece | Service | Notes |
|---|---|---|
| Backend (FastAPI) | Cloud Run service `pulsereach-api` | `backend/Dockerfile` (build context = repo root) |
| Migrations / seed / admin | Cloud Run job `pulsereach-init` | same image; runs once, never from the service |
| Database | Cloud SQL PostgreSQL 16, `db-g1-small`, 10 GB SSD | Cloud SQL connector socket; automated backups on |
| Frontend (Next.js) | Cloud Run service `pulsereach-web` | `gcloud run deploy --source frontend` (buildpacks) |
| Secrets | Secret Manager | DB URL, LLM key; never `--set-env-vars` |

Use **one region** for everything (e.g. `us-central1`, cheapest; `me-central1` is closest to Abu
Dhabi but costs more). Note the local gcloud defaults differ (`artifacts/location=asia-south1`,
`run`/`compute` `us-central1`) — pass `--region`/`--location` explicitly.

## 2. Environment variables (backend, production)

| Variable | Value | Secret? |
|---|---|---|
| `AUTH_MODE` | `users` (**never `legacy`** on an exposed URL) | no |
| `DATA_SOURCE` | `db` | no |
| `DATABASE_URL` | `postgresql+psycopg://pulsereach:<pw>@/pulsereach?host=/cloudsql/<PROJECT>:<REGION>:pulsereach-db` | **yes** |
| `CORS_ORIGINS` | the frontend `https://…run.app` origin only (never `*`) | no |
| `TRUSTED_PROXY_HOPS` | `1` (Cloud Run appends the client address to `X-Forwarded-For`) | no |
| `SELF_REGISTRATION_ENABLED` | `false` for judging | no |
| `DEMO_IDENTITY_SEED` | unset/`false` (memory mode only) | no |
| `ALLOW_UNPROTECTED_WRITES` | `false` | no |
| `POPULATION_MIN_CELL_SIZE` | `5` (default; do not lower) | no |
| `LOG_LEVEL` | `INFO` | no |
| `LLM_ENABLED` | `false`, or `true` with the four below | no |
| `LLM_PROVIDER` / `LLM_BASE_URL` / `LLM_MODEL` | Gemini: `openai_compatible` / `https://generativelanguage.googleapis.com/v1beta/openai` / a Flash model | no |
| `LLM_MAX_OUTPUT_TOKENS` | `2048` for Gemini (thinking tokens count against the budget; too low → empty output → deterministic fallback) | no |
| `LLM_API_KEY` | Gemini API key | **yes** |

Frontend build-time: `NEXT_PUBLIC_API_URL=https://<api-url>`; never set
`NEXT_PUBLIC_ALLOW_LEGACY_BACKEND` (the production build refuses it).

There is no FastAPI debug mode; `/docs` and `/openapi.json` stay public (no data, every API route
needs a token) — accepted limitation.

## 3. One-time setup (requires approval)

```bash
P=pulsereach-hackathon-2026; R=us-central1
gcloud artifacts repositories create pulsereach --repository-format=docker --location=$R --project=$P
gcloud sql instances create pulsereach-db --database-version=POSTGRES_16 --tier=db-g1-small \
  --region=$R --storage-size=10 --backup-start-time=02:00 --project=$P
# public IP with NO authorized networks: only the IAM-authorised Cloud Run connector can connect
gcloud sql databases create pulsereach --instance=pulsereach-db --project=$P
gcloud sql users create pulsereach --instance=pulsereach-db --password="$(openssl rand -hex 24)" --project=$P
printf '%s' 'postgresql+psycopg://pulsereach:<pw>@/pulsereach?host=/cloudsql/'$P':'$R':pulsereach-db' \
  | gcloud secrets create pulsereach-database-url --data-file=- --project=$P
printf '%s' '<gemini-key>' | gcloud secrets create pulsereach-llm-key --data-file=- --project=$P   # optional
# grant the Cloud Run runtime service account roles/secretmanager.secretAccessor and roles/cloudsql.client
```

## 4. Build and deploy

```bash
IMG=$R-docker.pkg.dev/$P/pulsereach/backend:$(git rev-parse --short HEAD)
cat > /tmp/cloudbuild.yaml <<EOF
steps: [{name: gcr.io/cloud-builders/docker, args: [build, -f, backend/Dockerfile, -t, $IMG, .]}]
images: [$IMG]
EOF
# Without a .gcloudignore, Cloud Build uploads per .gitignore, which excludes data/ (the image
# needs it). Reuse the Docker context rules for this upload (do not commit secrets into data/):
cp .dockerignore .gcloudignore
gcloud builds submit . --project=$P --region=$R --config=/tmp/cloudbuild.yaml

COMMON="--region=$R --project=$P --image=$IMG --add-cloudsql-instances=$P:$R:pulsereach-db \
  --set-secrets=DATABASE_URL=pulsereach-database-url:latest \
  --set-env-vars=AUTH_MODE=users,DATA_SOURCE=db,SELF_REGISTRATION_ENABLED=false"

# migrations + official register + synthetic seed: once, idempotent, never reseeds a seeded DB
gcloud run jobs create pulsereach-init $COMMON --command=python --args=-m,app.db.init,--seed --max-retries=0
gcloud run jobs execute pulsereach-init --region=$R --project=$P --wait

gcloud run deploy pulsereach-api $COMMON --allow-unauthenticated --port=8000 \
  --cpu=1 --memory=1Gi --min-instances=1 --max-instances=2 --concurrency=40 --timeout=60 \
  --set-env-vars=CORS_ORIGINS=https://<web-url>,TRUSTED_PROXY_HOPS=1
  # add for AI: --set-env-vars=LLM_ENABLED=true,LLM_PROVIDER=openai_compatible,LLM_BASE_URL=...,LLM_MODEL=...,LLM_MAX_OUTPUT_TOKENS=2048
  #             --update-secrets=LLM_API_KEY=pulsereach-llm-key:latest

gcloud run deploy pulsereach-web --source=frontend --region=$R --project=$P --allow-unauthenticated \
  --set-build-env-vars=NEXT_PUBLIC_API_URL=https://<api-url> --min-instances=0 --max-instances=2
# then redeploy the API with the final web origin in CORS_ORIGINS
```

`--max-instances=2` caps cost and keeps the per-process login rate limiter meaningful; persistent
per-account lockout is the authoritative brute-force control.

## 5. Accounts

```bash
# first administrator (password prompted; or PULSEREACH_ADMIN_PASSWORD from Secret Manager)
gcloud run jobs execute pulsereach-init … --args=-m,app.services.identity,create-admin,--email,<email>
# synthetic judge accounts (PostgreSQL mode prints random per-user passwords ONCE — store them safely)
gcloud run jobs execute pulsereach-init … --args=-m,app.services.identity,seed-demo
```

Demo accounts are shared by judges: 5 wrong passwords lock an account for 15 minutes
(`LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_SECONDS`). Hand out one account per judge where possible.

## 6. Health checks and smoke tests

```bash
API=https://<api-url>
curl -fsS $API/health                    # {"status":"ok"}
curl -fsS $API/health/db                 # {"database":"ok"}; 503 if the DB is unreachable
curl -s -o /dev/null -w '%{http_code}\n' $API/api/v1/patients        # 401 (no token)
TOKEN=$(curl -fsS -X POST $API/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"manager.a@demo.pulsereach.invalid","password":"<pw>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -fsS -H "Authorization: Bearer $TOKEN" "$API/api/v1/programmes/ifhas/summary" | head -c 300
curl -fsS -H "Authorization: Bearer $TOKEN" "$API/api/v1/ai/status"   # needs platform.status
curl -s -o /dev/null -w '%{http_code}\n' -H 'Origin: https://evil.example' -X OPTIONS \
  -H 'Access-Control-Request-Method: GET' $API/api/v1/me   # 400 (origin not allowed)
```

The backend refuses to start if the rule bundle is missing or the DB holds no matching seeded load
(`app/core/startup.py`), so a broken revision never receives traffic; Cloud Run keeps the
previous revision serving.

## 7. Rollback

```bash
gcloud run revisions list --service=pulsereach-api --region=$R --project=$P
gcloud run services update-traffic pulsereach-api --to-revisions=<previous>=100 --region=$R --project=$P
```

Schema rollback is not automatic: destructive downgrades are refused unless
`-x allow_data_loss=true`. For a bad data state restore the Cloud SQL backup to a **new**
instance and repoint the `pulsereach-database-url` secret. Never run the reseed command
(`app.services.synthetic_generator.seed`) against the judging database — it deletes follow-up,
workflow and AI audit history.

## 8. Shutdown and cleanup after judging

```bash
gcloud run services delete pulsereach-web pulsereach-api --region=$R --project=$P
gcloud run jobs delete pulsereach-init --region=$R --project=$P
gcloud sql instances delete pulsereach-db --project=$P        # deletes automated backups too
gcloud secrets delete pulsereach-database-url --project=$P; gcloud secrets delete pulsereach-llm-key --project=$P
gcloud artifacts repositories delete pulsereach --location=$R --project=$P
# revoke the Gemini key in Google AI Studio; set a billing budget alert before go-live
```

## 9. Estimated 10-day cost (list prices, us-central1; verify in the GCP pricing calculator)

| Item | Estimate |
|---|---|
| Cloud SQL `db-g1-small` + 10 GB SSD + backups | ≈ $9–11 (`db-f1-micro`: ≈ $4) |
| Cloud Run API, 1 vCPU / 1 GiB, `min-instances=1` | ≈ $5–18 (idle min-instance vs. busy) |
| Cloud Run web, scale to zero | ≈ $0–3 |
| Cloud Build, Artifact Registry, Secret Manager, Logging | ≈ $0–2 (mostly free tier) |
| Gemini Flash (optional, judge-scale traffic) | ≈ $0–5 |
| **Total** | **≈ $15–40** |

Set a budget alert (e.g. $50) on the billing account before deployment.
