# PulseReach — Patient Portal API and Engagement Workflow

All endpoints require `AUTH_MODE=users` and `Authorization: Bearer <access token>`. Data is
synthetic. Nothing in this API sends SMS, e-mail, WhatsApp or push messages: "visible to the
patient" means visible in the portal, and outreach remains `simulated_not_sent`.

## 1. Patient identity and account linking

A patient account can see data only after it is linked to exactly one patient record through a
controlled, verified workflow. A patient can never choose a patient id.

1. The patient registers (`POST /api/v1/auth/register`) or receives an account; it has no role,
   organization or data yet.
2. A staff member with `patient_links.invite` **and access to that patient** issues a one-time
   invitation: `POST /api/v1/patients/{patient_id}/portal-invitations` → `{code: "XXXX-XXXX-XXXX",
   expires_at, delivery: "out_of_band_not_sent"}`. The code is shown once (60 bits, unambiguous
   alphabet, stored as SHA-256), expires after `PATIENT_INVITATION_TTL_SECONDS` (7 days) and
   replaces any earlier unused code for that patient. Hand it over in person or through an
   approved channel.
3. The patient redeems it: `POST /api/v1/portal/link {invitation_code, date_of_birth}`. Both must
   match (the date of birth is compared with the clinical record). Every wrong date of birth counts
   against the invitation; after `PATIENT_INVITATION_MAX_ATTEMPTS` (5) it is revoked. All failures
   return the same `400 link.invitation_invalid`. Rate-limited per user.
4. On success the account gets a `PATIENT` membership in the patient's organization and an active
   `identity.patient_link`. Sign in again to obtain a token carrying the patient role.

Guarantees (database-enforced where possible): at most one active link per patient record and per
account (partial unique indexes); staff accounts cannot be linked (`403 link.staff_account`); an
already-linked account gets `409 link.already_linked`. An e-mail address is never treated as proof
of identity.

Administration: `GET /api/v1/admin/patient-links`, `POST /api/v1/admin/patient-links/{id}/revoke`
(`patient_links.manage`) — revocation ends the patient's sessions. Releasing a patient from an
organization also revokes its link.

## 2. Patient endpoints (`/api/v1/portal`)

Every response is localized (see `localization-and-language-support.md`) and includes `locale` and
`direction`. Machine values (ids, enum codes, ISO dates) are never translated; presentation fields
are `*_label`, `*_display`, `title`, `description`, `message`. Unlinked accounts get
`404 portal.not_linked`; staff get `403`. Resources of other patients answer `404` exactly like
missing ones.

| Method & path | Purpose |
|---|---|
| `POST /portal/link` | Redeem an invitation (any authenticated, unlinked, non-staff account) |
| `GET /portal/summary` | Own profile (name, date of birth, sex, language/channel preference, region) and counts: open recommendations, upcoming appointments, open follow-ups, follow-ups awaiting a reply, open requests. No Emirates ID. |
| `GET /portal/health-summary` | History availability per programme; screenings and well-child visits with dates and localized status |
| `GET /portal/evaluations` | Own evaluation history: rule id, programme, localized status, next due date. Results outside the person's age/sex band, `not_eligible` results and rule-level review flags are omitted. No reason codes, guards or input snapshots. |
| `GET /portal/recommendations?status=active\|all` | Care gaps as recommendations: `recommendation_id` (= care gap id), programme, gap type, localized title/description, status, identified date, documented next step (or "your care team will review") |
| `GET /portal/recommendations/{id}` | Details + patient-friendly evidence + timeline (identified, appointment/referral events, documented completion, simulated reminder, closed) + related follow-up ids. No staff notes or reviewer identities. |
| `GET /portal/recommendations/{id}/explanation` | Deterministic patient-friendly explanation (`generation_mode: deterministic_template`; no model call) |
| `GET /portal/appointments`, `GET /portal/appointments/{id}` | Own appointments with localized type/status and `can_request_change` |
| `POST /portal/appointment-requests` | `{recommendation_id?, follow_up_id?, preferred_dates[≤5], preferred_time_of_day?, message?}` → request `appointment` |
| `POST /portal/appointments/{id}/change-requests` | `{action: cancel\|reschedule, preferred_dates?, …}`; only for `scheduled`/`rescheduled` appointments more than 24 h away (`422 workflow.appointment_change_not_allowed` otherwise). The appointment itself is changed only by staff. |
| `GET /portal/referrals`, `GET /portal/referrals/{id}` | Own referrals: target, localized status, dates |
| `POST /portal/assistance` | `{message, preferred_time_of_day?}` → request `assistance` |
| `GET /portal/requests`, `GET /portal/requests/{id}` | Own requests with status and the patient-visible `staff_response` (never `internal_note`) |
| `POST /portal/requests/{id}/cancel` | Cancel while `submitted`/`acknowledged` |
| `GET /portal/follow-ups`, `GET /portal/follow-ups/{id}` | Patient-visible follow-up tasks: localized message, status, due date, `is_overdue`, `reported_completion_pending_verification`, patient-visible history |
| `GET /portal/follow-ups/{id}/history` | Patient-visible events only (created, status changes, care-team messages, the patient's own responses/requests, completion) |
| `POST /portal/follow-ups/{id}/responses` | `{response: will_book\|already_done\|need_help\|not_interested\|question, message?}` |
| `POST /portal/follow-ups/{id}/assistance` | Request help linked to the follow-up |
| `POST /portal/follow-ups/{id}/appointment-request` | Request an appointment linked to the follow-up |

Profile and language: `GET/PATCH /api/v1/me`, `GET/PATCH /api/v1/me/preferences`.

**Patients cannot complete clinical care.** `already_done` sets
`patient_reported_completion = true` on the task for staff verification; it never closes a care
gap or a task. Care gaps close only through `completion_documented` with validated evidence
(`POST /care-gaps/{id}/follow-ups`, staff with `care_gaps.complete`).

## 3. Follow-up and engagement workflow

1. The deterministic engine identifies a care gap (unchanged).
2. Staff review it (`POST /care-gaps/{id}/reviews`, actor = authenticated user).
3. Staff create/assign a follow-up task: `POST /api/v1/follow-up-tasks {patient_id, care_gap_id?,
   assigned_to_user_id?, due_date?, message_key, patient_visible, staff_note?, language?}`. The
   care gap must be open and belong to the patient; the assignee must be an active care-team member
   with access to the patient. `language` defaults to the patient's recorded preference;
   `message_key` selects an approved, localized template (`screening_invitation`,
   `complete_outstanding`, `referral_follow_up`, `well_child_visit`, `general_check_in`).
   Patient-visible tasks start as `awaiting_patient`, internal ones as `open`.
4. The patient views it in the portal (demo mechanism; nothing is sent).
5. The patient responds, asks for help or requests an appointment.
6. A coordinator reviews: `GET /api/v1/follow-up-tasks?status=patient_responded`,
   `GET /api/v1/patient-requests`, `PATCH /api/v1/patient-requests/{id} {status, staff_response,
   internal_note, appointment_id}` (the appointment must belong to the patient).
7. Workflow updates: `PATCH /api/v1/follow-up-tasks/{id}` (status
   `awaiting_patient`/`in_progress`/`cancelled`, assignee, due date),
   `POST …/notes {text, patient_visible}` (internal note or patient-visible message),
   `POST …/escalate {reason}`. Phase 5 (migration 0013): `priority` (`routine`/`high`/`urgent`)
   on create/PATCH (internal `priority_changed` event) and
   `POST …/contact-attempts {channel, outcome, note?}` to document a contact a staff member made
   outside PulseReach (internal `contact_attempt` event; consent-checked; nothing is sent; the
   status does not change). Workload overview: `GET /follow-up-tasks/summary`; assignees:
   `GET /care-team?patient_id=`.
8. Completion: `POST /api/v1/follow-up-tasks/{id}/complete {completion_follow_up_id}` succeeds
   only if that id is a `completion_documented` follow-up on the task's care gap
   (`422 workflow.completion_evidence_required` otherwise). Tasks without a care gap can be
   completed without it.

Task statuses: `open`, `awaiting_patient`, `patient_responded`, `in_progress`, `completed`,
`cancelled`. Request statuses: `submitted`, `acknowledged`, `scheduled`, `declined`, `closed`,
`cancelled`. `is_overdue` = due date passed and not terminal (`GET /follow-up-tasks?overdue=true`).
Task history (`engagement.follow_up_task_event`) is append-only; `visibility = internal` events
(notes, assignment, escalation, priority changes, contact attempts) are never returned to patients. Every action is audited
(`follow_up_task.*`, `patient_request.*`).

Staff permissions: `followups.read` (list/detail), `followups.create`, `followups.update`,
`patient_requests.manage`; everything is limited to the caller's organization and patient scope.

The existing outreach workflow is unchanged: drafts remain simulated and need human review by an
`outreach.review` holder; approval records `outcome_status = simulated_not_sent`.

## 4. Example

```bash
# Staff (coordinator) creates a patient-visible task
curl -X POST $API/api/v1/follow-up-tasks -H "Authorization: Bearer $COORD" -H 'content-type: application/json' \
  -d '{"patient_id":"SYNTH-PAT-000001","care_gap_id":"SYNTH-GAP-000001","due_date":"2026-12-15"}'
# Patient reads it in Arabic and answers
curl "$API/api/v1/portal/follow-ups?lang=ar" -H "Authorization: Bearer $PATIENT"
curl -X POST $API/api/v1/portal/follow-ups/<task_id>/responses -H "Authorization: Bearer $PATIENT" \
  -H 'content-type: application/json' -d '{"response":"need_help","message":"أحتاج إلى مساعدة"}'
```
