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
| Secrets | Secret Manager | `pulsereach-database-url`, `pulsereach-gemini-api-key`; never `--set-env-vars` |
| AI (optional) | Google Gemini API (native provider, `LLM_PROVIDER=gemini`) | key from Google AI Studio; see §3a and `docs/ai-gemini.md` |

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
| `LLM_ENABLED` | `false` (default), or `true` to enable AI with the rows below | no |
| `LLM_PROVIDER` | `gemini` (native Gemini API; selection is explicit, no silent switching) | no |
| `GEMINI_API_KEY` | from Secret Manager `pulsereach-gemini-api-key` via `--set-secrets` (§3a) | **yes** |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` (default; `LLM_MODEL`, if set, overrides it — leave `LLM_MODEL` unset) | no |
| `GEMINI_BASE_URL` | unset (default `https://generativelanguage.googleapis.com/v1beta`) | no |
| `GEMINI_THINKING_LEVEL` | unset (model default) or `minimal`/`low` to save tokens and latency | no |
| `LLM_MAX_OUTPUT_TOKENS` | `1024` for Gemini (thinking tokens count against it; `MAX_TOKENS` → `truncated` → deterministic fallback) | no |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` / `LLM_TOTAL_TIMEOUT_SECONDS` | defaults `20` / `2` / `45` (keep the total below the Cloud Run `--timeout=60`) | no |
| `LLM_API_KEY` / `LLM_BASE_URL` | unset (used only by `openai_compatible` / `anthropic`) | — |

Frontend build-time: `NEXT_PUBLIC_API_URL=https://<api-url>`; never set
`NEXT_PUBLIC_ALLOW_LEGACY_BACKEND` (the production build refuses it). No AI key or AI setting is
ever given to the frontend service or to any `NEXT_PUBLIC_*` variable.

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
# Cloud Run runtime service account (dedicated, no keys): used by the API service and init job
gcloud iam service-accounts create pulsereach-run --display-name="PulseReach Cloud Run runtime" --project=$P
SA=pulsereach-run@$P.iam.gserviceaccount.com
gcloud projects add-iam-policy-binding $P --member=serviceAccount:$SA --role=roles/cloudsql.client
gcloud secrets add-iam-policy-binding pulsereach-database-url --member=serviceAccount:$SA \
  --role=roles/secretmanager.secretAccessor --project=$P
```

## 3a. Gemini API key (optional AI; requires approval)

Architecture: **Google AI Studio Gemini API key → Secret Manager secret
`pulsereach-gemini-api-key` → Cloud Run backend env var `GEMINI_API_KEY`
(`--set-secrets=GEMINI_API_KEY=pulsereach-gemini-api-key:latest`) → `GeminiProvider`**
(`backend/app/services/ai/provider.py`, REST `models/{model}:generateContent`, key sent only in
the `x-goog-api-key` header). Details, error kinds and the smoke test: `docs/ai-gemini.md`.

Rules:

- No service-account keys and no JSON key downloads: Cloud Run reads the secret as its runtime
  service account; nobody needs a credential file.
- The Gemini key is never in source, `.env.example`, frontend config, `NEXT_PUBLIC_*`, Docker
  images, build args (`--build-arg`, `--set-build-env-vars`), Cloud Build configs, `--set-env-vars`,
  shell history or logs. Never commit `.env`; local development uses an untracked `backend/.env`
  (`git check-ignore -v backend/.env` must report it as ignored).
- Only the API service mounts the secret (the init job does not need it), and only the runtime
  service account gets `roles/secretmanager.secretAccessor`, on this one secret only.

**1. Create and restrict the key (console, Google AI Studio).** Sign in at
<https://aistudio.google.com/apikey> → *Create API key* → choose the existing project
`pulsereach-hackathon-2026` (so usage is billed and budget-alerted there, not in a new project).
Copy the key once, straight into step 2; do not paste it anywhere else. Then restrict it:

```bash
gcloud services api-keys list --project=$P            # note the KEY_ID (uid) of the new key
gcloud services api-keys update <KEY_ID> --project=$P \
  --api-target=service=generativelanguage.googleapis.com   # Gemini API only
```

(Application restrictions by IP are not practical: Cloud Run egress has no static IP without a
VPC connector + Cloud NAT.) Check the Gemini API terms for the project's tier: free-tier prompts
may be used to improve Google products; data here is synthetic, but a paid (billing-enabled)
tier is preferred.

**2. Store it in Secret Manager from stdin** (the key is never on a command line or in history):

```bash
read -rs GEMINI_KEY_INPUT        # paste the key, press Enter (nothing is echoed)
printf '%s' "$GEMINI_KEY_INPUT" | gcloud secrets create pulsereach-gemini-api-key \
  --replication-policy=automatic --data-file=- --project=$P
unset GEMINI_KEY_INPUT
```

**3. Grant only the runtime service account, only on this secret:**

```bash
gcloud secrets add-iam-policy-binding pulsereach-gemini-api-key \
  --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor --project=$P
gcloud secrets get-iam-policy pulsereach-gemini-api-key --project=$P   # exactly that one binding
```

**4. Deploy with AI enabled** — see §4 (`API_SECRETS` / `AI_ENV`).

**5. Verify** (`$API` and `$TOKEN` as in §6; the token needs `platform.status`, e.g. the
population health manager):

```bash
curl -fsS -H "Authorization: Bearer $TOKEN" "$API/api/v1/ai/status"
# expect llm_enabled=true, status="enabled", configured_provider="gemini", provider="gemini",
# availability="configured_unverified" until the first AI call, then "last_call_succeeded".
# "misconfigured" -> secret/model missing; "last_call_failed" -> see last_provider_error (an
# error kind such as auth, rate_limited, truncated; never provider text).
curl -fsS -H "Authorization: Bearer $TOKEN" "$API/api/v1/insights/population" | head -c 300   # aggregates only
```

**6. Rotate** (new key first, then retire the old one):

```bash
# create a second key in Google AI Studio (step 1), then:
read -rs GEMINI_KEY_INPUT
printf '%s' "$GEMINI_KEY_INPUT" | gcloud secrets versions add pulsereach-gemini-api-key --data-file=- --project=$P
unset GEMINI_KEY_INPUT
# secrets exposed as env vars are resolved when an instance starts: roll a new revision
gcloud run services update pulsereach-api --region=$R --project=$P \
  --update-secrets=GEMINI_API_KEY=pulsereach-gemini-api-key:latest
# verify /ai/status (step 5), then retire the old material
gcloud secrets versions list pulsereach-gemini-api-key --project=$P
gcloud secrets versions disable <old-version> --secret=pulsereach-gemini-api-key --project=$P
gcloud services api-keys delete <OLD_KEY_ID> --project=$P     # or delete it in Google AI Studio
```

**7. Disable AI** (deterministic templates take over; no secret change needed):

```bash
gcloud run services update pulsereach-api --region=$R --project=$P --update-env-vars=LLM_ENABLED=false
```

**8. Revoke** (suspected leak): delete the key in Google AI Studio (or `gcloud services api-keys
delete <KEY_ID> --project=$P`) — this takes effect at Google immediately and the backend falls
back with `last_provider_error=auth` — then disable AI (step 7) and destroy the secret version
(`gcloud secrets versions destroy <version> --secret=pulsereach-gemini-api-key --project=$P`).
Cleanup after judging: §8.

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
  --service-account=$SA"
BASE_ENV="AUTH_MODE=users,DATA_SOURCE=db,SELF_REGISTRATION_ENABLED=false"

# migrations + official register + synthetic seed: once, idempotent, never reseeds a seeded DB
# (the job gets the database secret only, never the Gemini key)
gcloud run jobs create pulsereach-init $COMMON --set-secrets=DATABASE_URL=pulsereach-database-url:latest \
  --set-env-vars=$BASE_ENV --command=python --args=-m,app.db.init,--seed --max-retries=0
gcloud run jobs execute pulsereach-init --region=$R --project=$P --wait

# Without AI: API_SECRETS=DATABASE_URL=pulsereach-database-url:latest and AI_ENV=LLM_ENABLED=false
API_SECRETS="DATABASE_URL=pulsereach-database-url:latest,GEMINI_API_KEY=pulsereach-gemini-api-key:latest"
AI_ENV="LLM_ENABLED=true,LLM_PROVIDER=gemini,GEMINI_MODEL=gemini-3.5-flash-lite,LLM_MAX_OUTPUT_TOKENS=1024"
gcloud run deploy pulsereach-api $COMMON --allow-unauthenticated --port=8000 \
  --cpu=1 --memory=1Gi --min-instances=1 --max-instances=2 --concurrency=40 --timeout=60 \
  --set-secrets=$API_SECRETS \
  --set-env-vars=$BASE_ENV,CORS_ORIGINS=https://<web-url>,TRUSTED_PROXY_HOPS=1,$AI_ENV

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
gcloud secrets delete pulsereach-database-url --project=$P
gcloud secrets delete pulsereach-gemini-api-key --project=$P    # replaces the old pulsereach-llm-key
gcloud artifacts repositories delete pulsereach --location=$R --project=$P
gcloud iam service-accounts delete pulsereach-run@$P.iam.gserviceaccount.com --project=$P
# revoke the Gemini key: delete it in Google AI Studio, or
gcloud services api-keys list --project=$P && gcloud services api-keys delete <KEY_ID> --project=$P
# set a billing budget alert before go-live
```

Earlier drafts of this runbook used a secret named `pulsereach-llm-key` (Gemini through
`openai_compatible`). It is no longer used; if it was ever created, delete it as well
(`gcloud secrets delete pulsereach-llm-key --project=$P`).

## 9. Estimated 10-day cost (list prices, us-central1; verify in the GCP pricing calculator)

| Item | Estimate |
|---|---|
| Cloud SQL `db-g1-small` + 10 GB SSD + backups | ≈ $9–11 (`db-f1-micro`: ≈ $4) |
| Cloud Run API, 1 vCPU / 1 GiB, `min-instances=1` | ≈ $5–18 (idle min-instance vs. busy) |
| Cloud Run web, scale to zero | ≈ $0–3 |
| Cloud Build, Artifact Registry, Secret Manager, Logging | ≈ $0–2 (mostly free tier) |
| Gemini API, `gemini-3.5-flash-lite` (optional, judge-scale traffic; ≤ 1024 output tokens per call, ≤ 3 attempts) | ≈ $0–5 |
| **Total** | **≈ $15–40** |

Set a budget alert (e.g. $50) on the billing account before deployment.
