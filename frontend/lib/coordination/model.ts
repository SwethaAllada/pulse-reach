/**
 * Coordination vocabulary and pure helpers. Transitions mirror the backend state machines
 * (`app/services/identity/engagement.py`, `app/services/followup/service.py`) only to decide which
 * actions to offer; the backend validates every change.
 */
import type {
  AppointmentOut,
  AppointmentStatus,
  CareGapOut,
  CareTeamMemberOut,
  ContactChannel,
  ContactOutcome,
  FollowUpEventOut,
  MessageKey,
  ReferralOut,
  ReferralStatus,
  RequestStatus,
  RequestType,
  StaffPatientRequestOut,
  TaskDetailOut,
  TaskEventOut,
  TaskPriority,
  TaskStatus,
  WorkflowStatusEventOut,
} from "@/lib/api/types";

export type Tone = "due" | "upcoming" | "eligible" | "completed" | "not_eligible" | "review" | "insufficient";

/** Semantic colour token per tone (theme-aware CSS variables; never raw colours). */
export const TONE_COLOR: Record<Tone, { paper: string; ink: string }> = {
  due: { paper: "var(--status-due)", ink: "var(--ink-due)" },
  upcoming: { paper: "var(--status-upcoming)", ink: "var(--ink-programme-well-child)" },
  eligible: { paper: "var(--status-eligible)", ink: "var(--ink-muted)" },
  completed: { paper: "var(--status-completed)", ink: "var(--ink-completed)" },
  not_eligible: { paper: "var(--status-not-eligible)", ink: "var(--ink-unknown)" },
  review: { paper: "var(--status-review)", ink: "var(--ink-review)" },
  insufficient: { paper: "var(--status-insufficient)", ink: "var(--ink-insufficient)" },
};

export const TASK_STATUS_ORDER: TaskStatus[] = ["open", "awaiting_patient", "patient_responded", "in_progress", "completed", "cancelled"];

export const TASK_STATUS_META: Record<TaskStatus, { label: string; tone: Tone; description: string }> = {
  open: { label: "Open", tone: "eligible", description: "Internal task, not yet worked." },
  awaiting_patient: { label: "Awaiting patient", tone: "upcoming", description: "Visible in the patient portal; no reply yet." },
  patient_responded: { label: "Patient responded", tone: "review", description: "The patient replied or asked for help — needs review." },
  in_progress: { label: "In progress", tone: "insufficient", description: "Being coordinated by the care team." },
  completed: { label: "Completed", tone: "completed", description: "Closed with documented, evidence-backed completion." },
  cancelled: { label: "Cancelled", tone: "not_eligible", description: "Closed without completion." },
};

export const TERMINAL_TASK_STATUSES: TaskStatus[] = ["completed", "cancelled"];

/** Staff-driven transitions (`TASK_TRANSITIONS`); completion has its own evidence-checked path. */
export const TASK_TRANSITIONS: Record<TaskStatus, ("awaiting_patient" | "in_progress" | "cancelled")[]> = {
  open: ["awaiting_patient", "in_progress", "cancelled"],
  awaiting_patient: ["in_progress", "cancelled"],
  patient_responded: ["in_progress", "awaiting_patient", "cancelled"],
  in_progress: ["awaiting_patient", "cancelled"],
  completed: [],
  cancelled: [],
};

export const PRIORITY_ORDER: TaskPriority[] = ["urgent", "high", "routine"];

export const PRIORITY_META: Record<TaskPriority, { label: string; tone: Tone; bars: number }> = {
  urgent: { label: "Urgent", tone: "due", bars: 3 },
  high: { label: "High", tone: "insufficient", bars: 2 },
  routine: { label: "Routine", tone: "eligible", bars: 1 },
};

export const MESSAGE_KEY_LABELS: Record<MessageKey, string> = {
  screening_invitation: "Screening invitation",
  complete_outstanding: "Complete outstanding parts",
  referral_follow_up: "Referral follow-up",
  well_child_visit: "Well-child visit invitation",
  general_check_in: "General check-in",
};

export const CONTACT_CHANNEL_LABELS: Record<ContactChannel, string> = {
  phone: "Phone call",
  sms: "SMS",
  email: "E-mail",
  in_person: "In person",
  portal: "Portal message",
};

export const CONTACT_OUTCOME_META: Record<ContactOutcome, { label: string; tone: Tone }> = {
  reached: { label: "Reached", tone: "completed" },
  no_answer: { label: "No answer", tone: "not_eligible" },
  left_message: { label: "Left a message", tone: "upcoming" },
  wrong_contact_details: { label: "Wrong contact details", tone: "insufficient" },
  declined: { label: "Declined", tone: "due" },
};

export const PATIENT_RESPONSE_LABELS: Record<string, string> = {
  will_book: "Will book",
  already_done: "Reports already done (unverified)",
  need_help: "Needs help",
  not_interested: "Not interested",
  question: "Has a question",
};

export const ROLE_LABELS: Record<string, string> = {
  SYSTEM_ADMIN: "Administrator",
  POPULATION_HEALTH_MANAGER: "Population health manager",
  CARE_COORDINATOR: "Care coordinator",
  CLINICIAN: "Clinician",
  PATIENT: "Patient",
};

export const REQUEST_STATUS_META: Record<RequestStatus, { label: string; tone: Tone }> = {
  submitted: { label: "New", tone: "due" },
  acknowledged: { label: "Acknowledged", tone: "upcoming" },
  scheduled: { label: "Appointment recorded", tone: "completed" },
  declined: { label: "Declined", tone: "not_eligible" },
  closed: { label: "Closed", tone: "not_eligible" },
  cancelled: { label: "Cancelled by patient", tone: "not_eligible" },
};

export const REQUEST_TRANSITIONS: Record<RequestStatus, ("acknowledged" | "scheduled" | "declined" | "closed")[]> = {
  submitted: ["acknowledged", "scheduled", "declined", "closed"],
  acknowledged: ["scheduled", "declined", "closed"],
  scheduled: ["closed"],
  declined: [],
  closed: [],
  cancelled: [],
};

export const REQUEST_TYPE_LABELS: Record<RequestType, string> = {
  appointment: "Appointment request",
  assistance: "Help request",
  appointment_change: "Change to an appointment",
};

export const APPOINTMENT_STATUS_META: Record<AppointmentStatus, { label: string; tone: Tone }> = {
  scheduled: { label: "Recorded", tone: "upcoming" },
  rescheduled: { label: "Rescheduled", tone: "upcoming" },
  attended: { label: "Attended", tone: "completed" },
  no_show: { label: "Not attended", tone: "insufficient" },
  cancelled_by_patient: { label: "Cancelled by patient", tone: "not_eligible" },
  cancelled_by_facility: { label: "Cancelled by facility", tone: "not_eligible" },
};

export const APPOINTMENT_STATUS_ORDER: AppointmentStatus[] = [
  "scheduled",
  "rescheduled",
  "attended",
  "no_show",
  "cancelled_by_patient",
  "cancelled_by_facility",
];

export const APPOINTMENT_TRANSITIONS: Record<AppointmentStatus, AppointmentStatus[]> = {
  scheduled: ["attended", "no_show", "cancelled_by_patient", "cancelled_by_facility", "rescheduled"],
  rescheduled: ["attended", "no_show", "cancelled_by_patient", "cancelled_by_facility", "rescheduled"],
  attended: [],
  no_show: [],
  cancelled_by_patient: [],
  cancelled_by_facility: [],
};

export const APPOINTMENT_TYPE_LABELS: Record<string, string> = {
  ifhas_screening: "IFHAS screening",
  well_child_visit: "Well-child visit",
  referral_visit: "Referral visit",
  other: "Other",
};

export const REFERRAL_STATUS_META: Record<ReferralStatus, { label: string; tone: Tone }> = {
  pending: { label: "Pending", tone: "due" },
  initiated: { label: "Initiated", tone: "upcoming" },
  completed: { label: "Completed", tone: "completed" },
  declined: { label: "Declined", tone: "not_eligible" },
  cancelled: { label: "Cancelled", tone: "not_eligible" },
};

export const REFERRAL_TRANSITIONS: Record<ReferralStatus, ReferralStatus[]> = {
  pending: ["initiated", "declined", "cancelled"],
  initiated: ["completed", "declined", "cancelled"],
  completed: [],
  declined: [],
  cancelled: [],
};

const BLOCKED_REASONS: Record<string, string> = {
  contact_consent_absent: "No current contact consent is recorded for this programme.",
  contact_consent_withdrawn: "The patient withdrew contact consent.",
  contact_consent_refused: "The patient refused contact.",
  contact_consent_expired: "The contact consent has expired.",
  patient_deceased: "The record shows the person is deceased.",
  rule_not_authoritative: "The rule is not authoritative, so outreach is not offered.",
  no_open_care_gap: "There is no open care gap for this rule.",
  evaluation_not_due: "The current evaluation is not due.",
  channel_unsupported: "This channel is not supported.",
  language_unsupported: "This language is not supported.",
  channel_not_permitted: "Drafts use the patient's recorded contact preference; choose that channel.",
  contact_details_missing_for_channel: "No contact details are recorded for this channel.",
  guardian_contact_not_supported: "Consent is held by a guardian; guardian outreach is not supported.",
  care_gap_not_open: "The care gap is no longer open.",
  no_supported_next_step: "The rule documents no next step that outreach can offer.",
  template_unavailable: "No approved template exists for this language.",
  rule_not_found: "The rule was not found.",
};

export function blockedReasonText(reason: string | null): string {
  if (!reason) return "Outreach is not permitted for this person.";
  if (reason.startsWith("contact_details_") && !BLOCKED_REASONS[reason]) return "The recorded contact details are not verified.";
  return BLOCKED_REASONS[reason] ?? humanize(reason);
}

export function humanize(code: string): string {
  const s = code.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Simulated outreach status wording — approval is never delivery. */
export function outreachOutcomeText(outcome: string | null): string {
  if (outcome === "simulated_not_sent") return "Simulated — not sent";
  if (outcome === "suppressed" || outcome === "outreach_suppressed") return "Suppressed — not permitted";
  return outcome ? humanize(outcome) : "Recorded";
}

export function memberName(team: Map<string, CareTeamMemberOut> | null, userId: string | null): string {
  if (!userId) return "Unassigned";
  const m = team?.get(userId);
  return m ? (m.is_self ? `${m.full_name} (you)` : m.full_name) : "Care-team member";
}

export function actorLabel(team: Map<string, CareTeamMemberOut> | null, userId: string, role: string): string {
  if (role === "PATIENT") return "Patient";
  const m = team?.get(userId);
  return m ? (m.is_self ? "You" : m.full_name) : ROLE_LABELS[role] ?? "Staff";
}

/** One-line description of a task event; internal text stays in `detail`. */
export function taskEventText(e: Pick<TaskEventOut, "event_type" | "to_status" | "from_status" | "priority" | "contact_channel" | "response_code">): string {
  switch (e.event_type) {
    case "created":
      return `Follow-up created · ${TASK_STATUS_META[(e.to_status as TaskStatus) ?? "open"]?.label ?? e.to_status}`;
    case "assigned":
      return "Assignment changed";
    case "status_changed":
      return `Status: ${statusText(e.from_status)} → ${statusText(e.to_status)}`;
    case "due_date_changed":
      return "Due date changed";
    case "priority_changed":
      return `Priority set to ${PRIORITY_META[e.priority as TaskPriority]?.label ?? e.priority}`;
    case "staff_note":
      return "Internal note";
    case "staff_message":
      return "Message to the patient (portal)";
    case "patient_response":
      return `Patient response: ${PATIENT_RESPONSE_LABELS[e.response_code ?? ""] ?? humanize(e.response_code ?? "reply")}`;
    case "assistance_requested":
      return "Patient asked for help";
    case "appointment_requested":
      return "Patient requested an appointment";
    case "escalated":
      return "Escalated";
    case "completed":
      return "Completed with documented evidence";
    case "contact_attempt":
      return `Contact attempt · ${CONTACT_CHANNEL_LABELS[e.contact_channel as ContactChannel] ?? e.contact_channel} · ${
        CONTACT_OUTCOME_META[e.response_code as ContactOutcome]?.label ?? e.response_code
      }`;
    default:
      return humanize(e.event_type);
  }
}

function statusText(s: string | null): string {
  return s ? TASK_STATUS_META[s as TaskStatus]?.label ?? humanize(s) : "—";
}

export function eventTone(e: Pick<TaskEventOut, "event_type" | "response_code" | "priority">): Tone {
  switch (e.event_type) {
    case "completed":
      return "completed";
    case "escalated":
      return "due";
    case "patient_response":
    case "assistance_requested":
    case "appointment_requested":
      return "review";
    case "contact_attempt":
      return CONTACT_OUTCOME_META[e.response_code as ContactOutcome]?.tone ?? "eligible";
    case "priority_changed":
      return PRIORITY_META[e.priority as TaskPriority]?.tone ?? "eligible";
    case "staff_message":
      return "upcoming";
    default:
      return "eligible";
  }
}

/* ── Dates ───────────────────────────────────────────────────────────────────── */

export function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function addDays(base: string, days: number): string {
  const d = new Date(`${base}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return isoDate(d);
}

export function formatDate(value: string | null): string {
  if (!value) return "—";
  const d = new Date(value.length === 10 ? `${value}T00:00:00Z` : value);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

export function formatDateTime(value: string): string {
  return new Date(value).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }) + " UTC";
}

/** "in 3 days" / "2 days overdue" relative to `today` (ISO date). */
export function dueText(due: string | null, today: string, terminal: boolean): string {
  if (!due) return "No due date";
  const days = Math.round((Date.parse(`${due}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
  if (terminal) return `Due ${formatDate(due)}`;
  if (days < 0) return `${-days} ${-days === 1 ? "day" : "days"} overdue`;
  if (days === 0) return "Due today";
  return `Due in ${days} ${days === 1 ? "day" : "days"}`;
}

/* ── Patient coordination timeline ───────────────────────────────────────────── */

export type TimelineKind = "gap" | "task" | "outreach" | "request" | "appointment" | "referral" | "completion" | "note";

export interface TimelineEntry {
  id: string;
  at: string;
  kind: TimelineKind;
  title: string;
  detail?: string | null;
  tone: Tone;
  /** `internal` = staff-only information (never shown to patients); `record` = clinical record. */
  visibility: "internal" | "patient" | "record";
  href?: string;
}

export interface TimelineInput {
  careGaps: CareGapOut[];
  tasks: TaskDetailOut[];
  followUps: FollowUpEventOut[];
  workflow: WorkflowStatusEventOut[];
  requests: StaffPatientRequestOut[];
  appointments: AppointmentOut[];
  referrals: ReferralOut[];
  team: Map<string, CareTeamMemberOut> | null;
}

/**
 * Merges every coordination record of one person into a dated timeline, newest first. Only a
 * `completion_documented` follow-up is labelled as completion; appointments, referrals, patient
 * replies and outreach reviews are shown as what they are.
 */
export function buildTimeline(input: TimelineInput): TimelineEntry[] {
  const out: TimelineEntry[] = [];
  for (const g of input.careGaps)
    out.push({
      id: `gap-${g.care_gap_id}`,
      at: g.identified_date,
      kind: "gap",
      title: `Care gap identified · ${g.rule_id}`,
      detail: humanize(g.gap_type),
      tone: "due",
      visibility: "record",
    });
  for (const t of input.tasks)
    for (const e of t.events)
      out.push({
        id: `task-${e.event_id}`,
        at: e.created_at,
        kind: e.event_type === "staff_note" || e.event_type === "contact_attempt" ? "note" : "task",
        title: `${taskEventText(e)}${e.event_type === "created" ? ` · ${MESSAGE_KEY_LABELS[t.message_key as MessageKey] ?? t.message_key}` : ""}`,
        detail:
          e.event_type === "assigned"
            ? null
            : e.message ?? (e.event_type === "created" ? `Assigned to ${memberName(input.team, t.assigned_to_user_id)}` : null),
        tone: eventTone(e),
        visibility: e.visibility,
        href: `/follow-up/${encodeURIComponent(t.task_id)}`,
      });
  for (const f of input.followUps) {
    // Appointment/referral gap events duplicate the workflow history below.
    if (f.event_type === "appointment_scheduled" || f.event_type === "appointment_updated" || f.event_type.startsWith("referral_")) continue;
    const completion = f.event_type === "completion_documented";
    out.push({
      id: `fu-${f.follow_up_id}`,
      at: f.recorded_at,
      kind: completion ? "completion" : f.event_type.startsWith("outreach") ? "outreach" : "note",
      title: completion
        ? "Completion documented with evidence · care gap closed"
        : f.event_type === "outreach_attempted"
          ? `Outreach reviewed and approved · ${outreachOutcomeText(f.outcome_status)}`
          : f.event_type === "outreach_suppressed"
            ? `Outreach suppressed · ${blockedReasonText(f.suppression_reason)}`
            : `Care-gap note · ${humanize(f.event_type)}`,
      detail: completion ? `Evidence ${f.evidence_reference ?? "—"}` : f.note,
      tone: completion ? "completed" : f.event_type === "outreach_suppressed" ? "not_eligible" : "upcoming",
      visibility: "internal",
    });
  }
  for (const w of input.workflow) {
    const appointment = w.entity_type === "appointment";
    const to = w.to_status;
    const label = appointment
      ? APPOINTMENT_STATUS_META[to as AppointmentStatus]?.label ?? humanize(to)
      : REFERRAL_STATUS_META[to as ReferralStatus]?.label ?? humanize(to);
    out.push({
      id: `wf-${w.status_event_id}`,
      at: w.recorded_at,
      kind: appointment ? "appointment" : "referral",
      title: appointment
        ? `${w.from_status ? "Appointment" : "Appointment recorded"} · ${label}${w.scheduled_datetime ? ` · ${formatDateTime(w.scheduled_datetime)}` : ""}`
        : `Referral ${w.referral_id ?? ""} · ${label}`,
      detail: w.note,
      tone: appointment
        ? APPOINTMENT_STATUS_META[to as AppointmentStatus]?.tone ?? "eligible"
        : REFERRAL_STATUS_META[to as ReferralStatus]?.tone ?? "eligible",
      visibility: "record",
    });
  }
  for (const r of input.requests)
    out.push({
      id: `req-${r.request_id}`,
      at: r.created_at,
      kind: "request",
      title: `${REQUEST_TYPE_LABELS[r.request_type] ?? humanize(r.request_type)} · ${REQUEST_STATUS_META[r.status]?.label ?? r.status}`,
      detail: r.message,
      tone: REQUEST_STATUS_META[r.status]?.tone ?? "eligible",
      visibility: "patient",
    });
  // Workflow history covers appointments/referrals written through the API; seed records without
  // history still appear once, dated by their own record.
  const withHistory = new Set(input.workflow.map((w) => w.appointment_id ?? w.referral_id));
  for (const a of input.appointments)
    if (!withHistory.has(a.appointment_id))
      out.push({
        id: `apt-${a.appointment_id}`,
        at: a.scheduled_datetime,
        kind: "appointment",
        title: `Appointment · ${APPOINTMENT_TYPE_LABELS[a.appointment_type] ?? a.appointment_type} · ${APPOINTMENT_STATUS_META[a.status]?.label ?? a.status}`,
        detail: `Scheduled for ${formatDateTime(a.scheduled_datetime)}`,
        tone: APPOINTMENT_STATUS_META[a.status]?.tone ?? "eligible",
        visibility: "record",
      });
  for (const r of input.referrals)
    if (!withHistory.has(r.referral_id))
      out.push({
        id: `ref-${r.referral_id}`,
        at: r.trigger_date,
        kind: "referral",
        title: `Referral to ${r.referral_target} · ${REFERRAL_STATUS_META[r.status]?.label ?? r.status}`,
        detail: `Triggered by ${r.trigger_rule_id}`,
        tone: REFERRAL_STATUS_META[r.status]?.tone ?? "eligible",
        visibility: "record",
      });
  return out.sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : a.id.localeCompare(b.id)));
}
