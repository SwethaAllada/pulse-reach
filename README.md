# PulseReach

AI-assisted precision prevention and population-health platform. It identifies people with elevated preventive-health risk or unmet preventive-care needs, explains why they are flagged, recommends preventive-care pathways, supports personalized outreach, and tracks whether care is completed.

**MVP pathways:** (1) adult comprehensive preventive screening, (2) child Well-Child Visits.

> All development and demos use **synthetic data only**. Never commit real patient data or credentials.

## Architecture

| Directory | Purpose |
|---|---|
| `frontend/` | Next.js (App Router), React, TypeScript, Tailwind CSS |
| `backend/` | FastAPI, SQLAlchemy, PostgreSQL (OpenAPI docs at `/docs`) |
| `data-pipeline/` | Ingestion, validation, transformation (Pandas) |
| `ml/` | Experiments, evaluation, model code |
| `data/` | Local synthetic/raw/processed datasets (git-ignored) |
| `docs/` | Requirements, architecture, data dictionary, API contracts, user journeys |
| `infrastructure/` | Docker Compose and deployment config (target: GCP Cloud Run) |

## Setup

Prerequisites: Node 20+, Python 3.12+, Docker.

```bash
cp .env.example .env                 # root: Postgres settings for Docker Compose
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```

### PostgreSQL (+ backend) via Docker
```bash
docker compose --env-file .env -f infrastructure/docker-compose.yml up -d db        # database only
docker compose --env-file .env -f infrastructure/docker-compose.yml up --build      # database + backend
```

### Backend (local, without Docker)
```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head          # needs DATABASE_URL in backend/.env; creates the official/clinical/synthetic schemas
python -m app.services.official_loader                 # official sources and facility register
python -m app.services.synthetic_generator.seed        # clinical rules + synthetic data; exit 2 on failure
DATA_SOURCE=db uvicorn app.main:app --reload --port 8000   # omit DATA_SOURCE for the in-memory demo
pytest                        # set TEST_DATABASE_URL to also run the live-PostgreSQL test
```
Health check: <http://localhost:8000/health> (process) · <http://localhost:8000/health/db> (database, 503 if unavailable) · Swagger: <http://localhost:8000/docs>

### Frontend
```bash
cd frontend
npm install
npm run dev
```
Open <http://localhost:3000>.

## Git workflow

- `main` – stable; `develop` – integration.
- Feature branches off `develop`: `feature/frontend-setup`, `feature/backend-setup`, `feature/data-pipeline`, `feature/api-integration`.
- Open PRs into `develop`; merge `develop` into `main` for releases.
