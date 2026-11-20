# PulseReach — Demo Script (~12 minutes)

[Docs index](README.md) · [Demo access](DEMO_ACCESS_TEMPLATE.md) · [Roles](USER_ROLES_AND_WORKFLOWS.md)

**Setup:** a running stack (local memory mode per [GCP_DEPLOYMENT_AND_OPERATIONS.md §10](GCP_DEPLOYMENT_AND_OPERATIONS.md#10-running-locally),
or the deployed URL once it exists). Use org A accounts. Point out the synthetic-data banner at the start.
AI is off unless `LLM_ENABLED=true`. Every AI panel then shows the deterministic version, which
is itself a safety feature worth showing.

## 0. Opening (30 s)

"Identify who needs preventive care, understand why, connect them to the right pathway and
measure whether care was completed. Rules decide. AI explains. People act."

## 1. Population health manager — `manager.a` (3 min)

1. **Population overview** (`/`): 379 people, open care gaps by programme, unknown history,
   review-flagged records. Open the AI population briefing and note that it is labelled as a draft or as standard text.
2. **Population** (`/population`): map with OpenFreeMap tiles and published facility points;
   choose diabetes → Mussafah shows an increasing trend (synthetic scenario). Point out the area extent
   label ("published facility-point extent, not a boundary") and that `—` means suppressed (k = 5).
3. **Alerts**: acknowledge an alert, then show its append-only history.
4. **Programmes** (`/programmes`): IFHAS summary → rule detail with the DoH source section and
   PDF page, verification status and open questions.

## 2. Care coordinator — `coordinator.a` (3 min)

1. **My worklist**: 20 assigned patients only. Try another patient's URL to show it returns not-found.
2. Open a patient → **care gaps** with the evidence trace (`rule_id`, version, reasons).
3. **Coordination copilot** summary. Its suggested next steps are deterministic.
4. **Create a patient-visible follow-up task** (template `screening_invitation`, priority high).
5. **Outreach panel**: preview → draft (banner `SIMULATED OUTREACH PREVIEW`) → approve, which records
   `simulated_not_sent`. Nothing is delivered.
6. **Log a contact attempt** (documented only, nothing is sent).

## 3. Patient — `patient.a` (3 min)

1. **Portal home**: counts, recommended care, new message from the care team.
2. **Recommendation detail**: patient-friendly evidence and timeline. Ask the assistant
   *"Why am I seeing this?"* and *"Help me prepare questions"*. Type an emergency-style question to
   show the escalation answer (no model call).
3. **Reply** `need_help` and **request an appointment** with preferred dates.
4. Switch the language to **العربية** and show the full RTL layout. Optionally sign in as `patient.b`, who prefers Arabic.

## 4. Back to coordinator → clinician (2 min)

1. `coordinator.a`: the request appears; respond (`staff_response` is visible to the patient,
   `internal_note` is not); schedule the appointment.
2. `clinician.a`: open the same patient, review the gap, then **document completion** with evidence.
   The gap closes as `closed_completed`. Try completing the task without evidence and show it is
   refused (`422`).
3. `patient.a`: the timeline shows the completion.

## 5. Administrator and security (30 s)

`admin.a`: users and roles, assignments, the **audit log** (every action above, with actor and
outcome), AI audit (fingerprints only). Point out that `/patients` returns 403 for admins and
that `manager.b` never sees org A.

## Talking points for judges

- Deterministic, source-cited rules; unresolved criteria are encoded as open questions, not guesses.
- AI is optional, grounded and validated, falls back safely, is audited, and never decides or sends anything.
- Backend-enforced RBAC, organisation isolation and assignment scope; append-only audit.
- Honest limits: synthetic data, not clinically validated, GCP deployment pending, no live Gemini call yet.
