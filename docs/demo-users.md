# Demo users (synthetic, local development and QA only)

Demo identities are created by `app.services.identity.demo.seed_demo` — at API startup in memory mode
(`DEMO_IDENTITY_SEED=true`) or with `python -m app.services.identity seed-demo` in PostgreSQL mode.
All names are marked synthetic and every address uses the reserved `.invalid` TLD. Seeding is
idempotent and never changes an existing password. See `authentication-and-rbac.md` §9–10.

## Password

Every demo account shares the passphrase given in `DEMO_IDENTITY_PASSWORD` when the API is started
(PostgreSQL mode without the variable prints random per-user passwords once). The local QA setup
below uses:

| Setting | Value |
|---|---|
| `DEMO_IDENTITY_PASSWORD` | `Demo-QA-Passphrase-77` |

This value is for a disposable, memory-mode, synthetic-data API on your machine only. Never use it,
or `DEMO_IDENTITY_SEED`, in a shared or deployed environment.

## Accounts

Two organizations split the synthetic population by region: `demo-org-a` (region 1, Abu Dhabi) and
`demo-org-b` (regions 2 and 3). Each has one user per role.

| Email | Role | Patient scope | What to try |
|---|---|---|---|
| `admin.a@demo.pulsereach.invalid` | SYSTEM_ADMIN | none (no patient data) | Home = Administration console (users & roles, assignments, portal links, audit log, population aggregation); no patient or clinical workspaces |
| `manager.a@demo.pulsereach.invalid` | POPULATION_HEALTH_MANAGER | all patients of org A | Home = Population overview; Programmes, People; Follow-up overview and workload; care-team assignments and population aggregation; create/update follow-ups; patient requests; no outreach drafting, no appointment scheduling |
| `coordinator.a@demo.pulsereach.invalid` | CARE_COORDINATOR | 20 assigned patients | Home = My worklist (own follow-ups, new patient requests, upcoming appointments); Panel insights over assigned patients; full coordination: follow-ups, contact attempts, outreach draft and review, patient requests, appointments, referrals, documented completion |
| `clinician.a@demo.pulsereach.invalid` | CLINICIAN | 10 assigned patients | Home = My patients (assigned patients with open gaps, follow-ups, visits); Panel insights; create follow-ups, update appointments and referrals, documented completion; no patient requests tab, no task updates, no outreach |
| `patient.a@demo.pulsereach.invalid` | PATIENT | own linked record | Patient portal (overview, recommended care, appointments + change requests, messages/replies, requests, health record); only `/api/v1/portal/*` is ever called |
| `admin.b@demo.pulsereach.invalid` | SYSTEM_ADMIN | none | Org B administration |
| `manager.b@demo.pulsereach.invalid` | POPULATION_HEALTH_MANAGER | all patients of org B | Never sees org A patients, tasks or requests (isolation check) |
| `coordinator.b@demo.pulsereach.invalid` | CARE_COORDINATOR | 20 assigned patients (org B) | Org B coordination |
| `clinician.b@demo.pulsereach.invalid` | CLINICIAN | 10 assigned patients (org B) | Org B clinical workflow |
| `patient.b@demo.pulsereach.invalid` | PATIENT | own linked record (org B) | Portal only |

The frontend only shapes navigation by role; the backend enforces every permission and patient scope.

## Start the local QA stack

```bash
# backend (memory mode, demo identities seeded at startup)
cd backend
DATA_SOURCE=memory DEMO_IDENTITY_SEED=true DEMO_IDENTITY_PASSWORD=Demo-QA-Passphrase-77 \
  CORS_ORIGINS=http://localhost:3100 .venv/bin/python -m uvicorn app.main:app --port 8001

# frontend
cd frontend
NEXT_PUBLIC_API_URL=http://localhost:8001 npx next dev -p 3100
```

Open <http://localhost:3100> and sign in with any account above. Memory mode resets all identities,
follow-ups and requests when the API restarts. Repeated failed sign-ins lock an account briefly
(brute-force protection); restart the memory-mode API to clear it.
