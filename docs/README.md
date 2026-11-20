# PulseReach documentation

> **Identify who needs preventive care, understand why, connect them to the right pathway and measure whether care was completed.**

PulseReach is a population-health and preventive-care coordination platform for two Abu Dhabi
pathways: **IFHAS adult screening** and **Well-Child visits**. All patient data is **synthetic**.
It is a hackathon build: not clinically validated, not independently security-reviewed, and not
claimed to be compliant with any regulation.

## Status legend (used in every document)

| Label | Meaning |
|---|---|
| **Implemented & verified** | Code exists and was exercised by tests and/or a live run on 2026-11-20 |
| **Implemented, not fully verified** | Code and mocked tests exist; no live end-to-end evidence |
| **Planned / not implemented** | Documented intent only |

## Hackathon documentation package

| Document | For | Contents |
|---|---|---|
| [PULSEREACH_OVERVIEW.md](PULSEREACH_OVERVIEW.md) | Everyone | Problem, solution, product journey, status at a glance |
| [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) | Engineers, judges | Components, request flow, data layer, external services |
| [DATA_PIPELINE_AND_WORKFLOW.md](DATA_PIPELINE_AND_WORKFLOW.md) | Engineers, health evaluators | Source → evaluation → care gap → engagement → completion → reporting; geography and facilities |
| [AI_ARCHITECTURE_AND_SAFETY.md](AI_ARCHITECTURE_AND_SAFETY.md) | Judges, safety reviewers | Gemini provider, guardrails, fallback, audit, safety boundaries |
| [SECURITY_AND_PRIVACY.md](SECURITY_AND_PRIVACY.md) | Security reviewers | Authentication, RBAC, isolation, privacy, limitations |
| [USER_ROLES_AND_WORKFLOWS.md](USER_ROLES_AND_WORKFLOWS.md) | Product evaluators | Five roles, permission matrix, workflows, patient journey |
| [API_AND_DATABASE_REFERENCE.md](API_AND_DATABASE_REFERENCE.md) | Developers | Main API groups with permissions; schemas and relationships |
| [GCP_DEPLOYMENT_AND_OPERATIONS.md](GCP_DEPLOYMENT_AND_OPERATIONS.md) | Operators | Target GCP architecture (pending), local run, health checks, rollback |
| [DEMO_SCRIPT.md](DEMO_SCRIPT.md) | Presenters | Timed demo walkthrough per role |
| [DEMO_ACCESS_TEMPLATE.md](DEMO_ACCESS_TEMPLATE.md) | Judges | Demo accounts without passwords |

`DEMO_ACCESS_PRIVATE.md` (git-ignored) holds the synthetic demo passphrase and is shared privately.

## Diagrams (`diagrams/`, Mermaid)

| File | Shows |
|---|---|
| [system-architecture.mmd](diagrams/system-architecture.mmd) | Frontend, backend services, schemas, external services |
| [data-pipeline-flow.mmd](diagrams/data-pipeline-flow.mmd) | Data lifecycle; where the deterministic engine and AI operate |
| [authentication-and-rbac.mmd](diagrams/authentication-and-rbac.mmd) | Login, token rotation, permission and scope checks |
| [patient-engagement-journey.mmd](diagrams/patient-engagement-journey.mmd) | Care gap to documented completion |
| [ai-request-flow.mmd](diagrams/ai-request-flow.mmd) | AI request, guardrails, fallback, audit |
| [deployment-architecture.mmd](diagrams/deployment-architecture.mmd) | Planned GCP topology |

## Detailed engineering references (pre-existing)

| Topic | Document |
|---|---|
| Authentication, RBAC, isolation (design detail) | [authentication-and-rbac.md](authentication-and-rbac.md) |
| Gemini provider configuration, error kinds, smoke test | [ai-gemini.md](ai-gemini.md) |
| Patient portal API and engagement workflow | [patient-portal-api.md](patient-portal-api.md) |
| Geospatial population intelligence | [geospatial-population-intelligence.md](geospatial-population-intelligence.md) |
| Clinical rule foundation and open questions | [clinical-rules.md](clinical-rules.md) |
| Data sources and acquisition | [data-sources.md](data-sources.md), [data-acquisition-report.md](data-acquisition-report.md) |
| Database design and ERDs | [phase-3-database-design.md](phase-3-database-design.md), [erd/](erd/) |
| GCP runbook (step-by-step commands) | [deployment-gcp.md](deployment-gcp.md) |
| Deployment security checklist | [deployment-security-checklist.md](deployment-security-checklist.md) |
| Localisation | [localization-and-language-support.md](localization-and-language-support.md), [localization-glossary.md](localization-glossary.md) |
| Demo users (local QA) | [demo-users.md](demo-users.md) |
| Security audit | [security-and-access-control-audit.md](security-and-access-control-audit.md) |
