# PulseReach — Product Overview

[Docs index](README.md) · [Architecture](SYSTEM_ARCHITECTURE.md) · [Data pipeline](DATA_PIPELINE_AND_WORKFLOW.md) · [Demo script](DEMO_SCRIPT.md)

> **Identify who needs preventive care, understand why, connect them to the right pathway and measure whether care was completed.**

## 1. Problem

Preventive programmes such as adult screening and childhood well-child visits depend on many
separate actors and systems:

- **Population teams** see aggregate coverage but not which people are behind a number.
- **Care teams** work from lists that do not explain *why* a person is flagged or which standard
  applies.
- **Patients** rarely see what is recommended for them, or have a simple way to respond.
- **Completion** is often recorded inconsistently, so it is hard to tell whether outreach led to
  care being completed.

The result is missed screenings, duplicated outreach and programme metrics nobody can trust.

## 2. Solution

PulseReach connects these steps in one platform with a strict rule: **eligibility and care gaps
come from a deterministic, source-cited rules engine. AI only explains or drafts, and a person
always decides.**

| Step | What PulseReach does | Where |
|---|---|---|
| 1. Understand the population | Area-level metrics, trends, hotspots and alerts over synthetic records, with small-cell suppression | Population workspace, `/population/*` |
| 2. Identify preventive-care gaps | 54 versioned rules transcribed from DoH IFHAS V10 and Well-Child V10 evaluate every person | Evaluation engine |
| 3. Explain the evidence | Every gap cites `rule_id`, `rule_version`, source section and reason codes | Profile evidence trace, explanations |
| 4. Assign care coordination | Org ownership, staff–patient assignments, follow-up tasks with priority | Admin, Follow-up workspace |
| 5. Connect patients to pathways | Verified portal linking, patient-visible tasks, recommendations, appointment requests | Patient portal |
| 6. Support follow-ups | Contact attempts, patient responses, requests, simulated outreach drafts with human review | Coordination |
| 7. Track completion | Gaps close only with validated `completion_documented` evidence | Care gap follow-ups |
| 8. Measure outcomes | Programme summaries, preventive coverage, follow-up completion rate | Programmes, Population |

## 3. Deterministic evaluation and AI

| | Deterministic engine | AI layer (Gemini, optional) |
|---|---|---|
| Decides eligibility, due dates, care gaps | **Yes** | **Never** |
| Output | Statuses, reason codes, care gaps with provenance | Plain-language explanations, summaries, draft text |
| Off switch | Always on | `LLM_ENABLED=false` (default) → deterministic templates |
| Validation | Rule loader, guards, tests | Guardrails reject unsafe output → deterministic fallback |
| Writes clinical data | Yes, through the evaluation run | No |

Details: [AI_ARCHITECTURE_AND_SAFETY.md](AI_ARCHITECTURE_AND_SAFETY.md).

## 4. Status at a glance (2026-11-20)

| Capability | Status |
|---|---|
| Rule bundle (54 rules, 47 authoritative), deterministic engine, care gaps | Implemented & verified |
| Synthetic population (550 people, seed `SYNTH-RUN-0001`, reference date 2026-11-16) | Implemented & verified |
| Users, five roles, RBAC, org isolation, audit log | Implemented & verified (offline + live PostgreSQL tests) |
| Patient portal, follow-ups, requests, appointments, referrals | Implemented & verified (tests; local runtime) |
| Population intelligence, alerts, facility directory and map | Implemented & verified (tests; local runtime) |
| English / Arabic with RTL | Implemented & verified (catalog tests); full manual visual QA not run |
| AI explanations, outreach drafts, patient assistant, portal guide, staff copilot | Implemented, not fully verified — mocked provider only; **no live Gemini call made** |
| Staff copilot and portal guide (migration 0015) | Implemented, **uncommitted** in the working tree |
| GCP deployment | **Planned / not deployed** — no GCP resources exist |
| Real message delivery (SMS / e-mail / push) | Not implemented, by design (outreach is simulated) |
| Statistical hotspot detection, area boundaries, patient locations | Not implemented |

## 5. Scope and limitations

- Synthetic data only. No real patient data has been loaded or used.
- Clinical rules are transcriptions of published standards with `clinical_review_status =
  not_reviewed`. Unresolved criteria are recorded as open questions (`OQ-*`) instead of being guessed.
- Population rates come from synthetic data and are not Abu Dhabi prevalence figures. Hotspots
  are threshold rules, not confirmed outbreaks.
- UAE data-residency suitability of GCP hosting is not established (`OQ-GOV-DATA-RESIDENCY`).
