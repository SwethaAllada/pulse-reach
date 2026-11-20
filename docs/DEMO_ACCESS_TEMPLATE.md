# PulseReach — Demo Access (template, no passwords)

[Docs index](README.md) · [Demo script](DEMO_SCRIPT.md) · [Roles](USER_ROLES_AND_WORKFLOWS.md)

All accounts are **synthetic** demo identities created by
`backend/app/services/identity/demo.py` (`seed_demo`). They use the reserved `.invalid` domain and
hold only synthetic data. **Passwords are not in this file.** Authorised judges receive them
privately (`DEMO_ACCESS_PRIVATE.md`, git-ignored, shared through a private channel).

| Item | Value |
|---|---|
| Application URL | `<PENDING — no deployment exists yet>` |
| API URL | `<PENDING>` |
| Password | `<shared privately>` |
| Verification | All 10 accounts signed in successfully against a local memory-mode backend on 2026-11-20 |

## Accounts

Organisation A = **Demo Health Network A (synthetic)** (`demo-org-a`, region 1 Abu Dhabi, 379 people).
Organisation B = **Demo Health Network B (synthetic)** (`demo-org-b`, regions 2–3, 171 people).

| Display name | Role | Org | Login | Patient scope | Demo workflow |
|---|---|---|---|---|---|
| Demo Admin A (synthetic) | SYSTEM_ADMIN | A | `admin.a@demo.pulsereach.invalid` | none | Users and roles, assignments, portal links, audit log, aggregation |
| Demo Manager A (synthetic) | POPULATION_HEALTH_MANAGER | A | `manager.a@demo.pulsereach.invalid` | all 379 | Population overview, map, alerts, programmes, follow-up oversight |
| Demo Coordinator A (synthetic) | CARE_COORDINATOR | A | `coordinator.a@demo.pulsereach.invalid` | 20 assigned | Worklist, tasks, patient requests, simulated outreach, appointments |
| Demo Clinician A (synthetic) | CLINICIAN | A | `clinician.a@demo.pulsereach.invalid` | 10 assigned | Evidence review, documented completion, referrals, population map |
| Demo Patient A (synthetic) | PATIENT | A | `patient.a@demo.pulsereach.invalid` | own record `SYNTH-PAT-000001` | Portal: recommendations, assistant, appointments, messages, requests |
| Demo Admin B (synthetic) | SYSTEM_ADMIN | B | `admin.b@demo.pulsereach.invalid` | none | Org B administration |
| Demo Manager B (synthetic) | POPULATION_HEALTH_MANAGER | B | `manager.b@demo.pulsereach.invalid` | all 171 | Isolation check: never sees org A |
| Demo Coordinator B (synthetic) | CARE_COORDINATOR | B | `coordinator.b@demo.pulsereach.invalid` | 20 assigned | Org B coordination |
| Demo Clinician B (synthetic) | CLINICIAN | B | `clinician.b@demo.pulsereach.invalid` | 10 assigned | Org B clinical workflow |
| Demo Patient B (synthetic) | PATIENT | B | `patient.b@demo.pulsereach.invalid` | own record `SYNTH-PAT-000024` (prefers Arabic) | Portal in Arabic |

## Patient linking

Already done by the seed through the normal workflow (coordinator invitation + date-of-birth
verification). No action is needed. To demo linking a new account, a coordinator issues
`POST /patients/{id}/portal-invitations` and the patient redeems it in the portal.

## Rules for judges

- Five wrong passwords lock an account for 15 minutes. Please use your own assigned account where possible.
- Memory-mode demos reset all identities and workflow data on restart.
- If the hackathon platform requires **public** credentials, this needs explicit review by the
  team first. Prefer the coordinator/clinician/patient accounts (synthetic data, limited scope),
  and never publish an administrator password.
