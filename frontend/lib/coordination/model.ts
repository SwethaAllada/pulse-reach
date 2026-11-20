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
import type { MessageKey as I18nKey, Translate } from "@/lib/i18n/translate";
import { intlLocale, type Locale } from "@/lib/i18n/config";
import { GAP_TYPE_LABELS } from "@/lib/population/model";

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

/** Labels and descriptions are message keys: render them with the bound translator. */
export const TASK_STATUS_META: Record<TaskStatus, { label: I18nKey; tone: Tone; description: I18nKey }> = {
  open: { label: "coord.task_status.open", tone: "eligible", description: "coord.task_status.open_desc" },
  awaiting_patient: { label: "coord.task_status.awaiting_patient", tone: "upcoming", description: "coord.task_status.awaiting_patient_desc" },
  patient_responded: { label: "coord.task_status.patient_responded", tone: "review", description: "coord.task_status.patient_responded_desc" },
  in_progress: { label: "coord.task_status.in_progress", tone: "insufficient", description: "coord.task_status.in_progress_desc" },
  completed: { label: "coord.task_status.completed", tone: "completed", description: "coord.task_status.completed_desc" },
  cancelled: { label: "coord.task_status.cancelled", tone: "not_eligible", description: "coord.task_status.cancelled_desc" },
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

export const PRIORITY_META: Record<TaskPriority, { label: I18nKey; tone: Tone; bars: number }> = {
  urgent: { label: "coord.priority.urgent", tone: "due", bars: 3 },
  high: { label: "coord.priority.high", tone: "insufficient", bars: 2 },
  routine: { label: "coord.priority.routine", tone: "eligible", bars: 1 },
};

export const MESSAGE_KEY_LABELS: Record<MessageKey, I18nKey> = {
  screening_invitation: "coord.template.screening_invitation",
  complete_outstanding: "coord.template.complete_outstanding",
  referral_follow_up: "coord.template.referral_follow_up",
  well_child_visit: "coord.template.well_child_visit",
  general_check_in: "coord.template.general_check_in",
};

export const CONTACT_CHANNEL_LABELS: Record<ContactChannel, I18nKey> = {
  phone: "coord.channel.phone",
  sms: "coord.channel.sms",
  email: "coord.channel.email",
  in_person: "coord.channel.in_person",
  portal: "coord.channel.portal",
};

export const CONTACT_OUTCOME_META: Record<ContactOutcome, { label: I18nKey; tone: Tone }> = {
  reached: { label: "coord.outcome.reached", tone: "completed" },
  no_answer: { label: "coord.outcome.no_answer", tone: "not_eligible" },
  left_message: { label: "coord.outcome.left_message", tone: "upcoming" },
  wrong_contact_details: { label: "coord.outcome.wrong_contact_details", tone: "insufficient" },
  declined: { label: "coord.outcome.declined", tone: "due" },
};

export const PATIENT_RESPONSE_LABELS: Record<string, I18nKey> = {
  will_book: "coord.response.will_book",
  already_done: "coord.response.already_done",
  need_help: "coord.response.need_help",
  not_interested: "coord.response.not_interested",
  question: "coord.response.question",
};

export const ROLE_LABELS: Record<string, I18nKey> = {
  SYSTEM_ADMIN: "coord.role.admin",
  POPULATION_HEALTH_MANAGER: "role.POPULATION_HEALTH_MANAGER",
  CARE_COORDINATOR: "role.CARE_COORDINATOR",
  CLINICIAN: "role.CLINICIAN",
  PATIENT: "role.PATIENT",
};

/** Localized role name; an unknown role is shown as its identifier. */
export function roleText(role: string, t: Translate): string {
  return ROLE_LABELS[role] ? t(ROLE_LABELS[role]) : role;
}

export const REQUEST_STATUS_META: Record<RequestStatus, { label: I18nKey; tone: Tone }> = {
  submitted: { label: "coord.request_status.submitted", tone: "due" },
  acknowledged: { label: "coord.request_status.acknowledged", tone: "upcoming" },
  scheduled: { label: "coord.request_status.scheduled", tone: "completed" },
  declined: { label: "coord.request_status.declined", tone: "not_eligible" },
  closed: { label: "coord.request_status.closed", tone: "not_eligible" },
  cancelled: { label: "coord.request_status.cancelled", tone: "not_eligible" },
};

export const REQUEST_TRANSITIONS: Record<RequestStatus, ("acknowledged" | "scheduled" | "declined" | "closed")[]> = {
  submitted: ["acknowledged", "scheduled", "declined", "closed"],
  acknowledged: ["scheduled", "declined", "closed"],
  scheduled: ["closed"],
  declined: [],
  closed: [],
  cancelled: [],
};

export const REQUEST_TYPE_LABELS: Record<RequestType, I18nKey> = {
  appointment: "coord.request_type.appointment",
  assistance: "coord.request_type.assistance",
  appointment_change: "coord.request_type.appointment_change",
};

export const APPOINTMENT_STATUS_META: Record<AppointmentStatus, { label: I18nKey; tone: Tone }> = {
  scheduled: { label: "coord.appt_status.scheduled", tone: "upcoming" },
  rescheduled: { label: "coord.appt_status.rescheduled", tone: "upcoming" },
  attended: { label: "coord.appt_status.attended", tone: "completed" },
  no_show: { label: "coord.appt_status.no_show", tone: "insufficient" },
  cancelled_by_patient: { label: "coord.appt_status.cancelled_by_patient", tone: "not_eligible" },
  cancelled_by_facility: { label: "coord.appt_status.cancelled_by_facility", tone: "not_eligible" },
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

export const APPOINTMENT_TYPE_LABELS: Record<string, I18nKey> = {
  ifhas_screening: "coord.appt_type.ifhas_screening",
  well_child_visit: "coord.appt_type.well_child_visit",
  referral_visit: "coord.appt_type.referral_visit",
  other: "coord.appt_type.other",
};

export const REFERRAL_STATUS_META: Record<ReferralStatus, { label: I18nKey; tone: Tone }> = {
  pending: { label: "coord.referral_status.pending", tone: "due" },
  initiated: { label: "coord.referral_status.initiated", tone: "upcoming" },
  completed: { label: "coord.referral_status.completed", tone: "completed" },
  declined: { label: "coord.referral_status.declined", tone: "not_eligible" },
  cancelled: { label: "coord.referral_status.cancelled", tone: "not_eligible" },
};

export const REFERRAL_TRANSITIONS: Record<ReferralStatus, ReferralStatus[]> = {
  pending: ["initiated", "declined", "cancelled"],
  initiated: ["completed", "declined", "cancelled"],
  completed: [],
  declined: [],
  cancelled: [],
};

const BLOCKED_REASONS: Record<string, I18nKey> = {
  contact_consent_absent: "coord.blocked.contact_consent_absent",
  contact_consent_withdrawn: "coord.blocked.contact_consent_withdrawn",
  contact_consent_refused: "coord.blocked.contact_consent_refused",
  contact_consent_expired: "coord.blocked.contact_consent_expired",
  patient_deceased: "coord.blocked.patient_deceased",
  rule_not_authoritative: "coord.blocked.rule_not_authoritative",
  no_open_care_gap: "coord.blocked.no_open_care_gap",
  evaluation_not_due: "coord.blocked.evaluation_not_due",
  channel_unsupported: "coord.blocked.channel_unsupported",
  language_unsupported: "coord.blocked.language_unsupported",
  channel_not_permitted: "coord.blocked.channel_not_permitted",
  contact_details_missing_for_channel: "coord.blocked.contact_details_missing_for_channel",
  guardian_contact_not_supported: "coord.blocked.guardian_contact_not_supported",
  care_gap_not_open: "coord.blocked.care_gap_not_open",
  no_supported_next_step: "coord.blocked.no_supported_next_step",
  template_unavailable: "coord.blocked.template_unavailable",
  rule_not_found: "coord.blocked.rule_not_found",
};

export function blockedReasonText(reason: string | null, t: Translate): string {
  if (!reason) return t("coord.blocked.default");
  if (reason.startsWith("contact_details_") && !BLOCKED_REASONS[reason]) return t("coord.blocked.contact_details_unverified");
  return BLOCKED_REASONS[reason] ? t(BLOCKED_REASONS[reason]) : humanize(reason);
}

export function humanize(code: string): string {
  const s = code.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Label from a key map, falling back to the humanized code for values the UI does not know. */
function labelOr(key: I18nKey | undefined, code: string, t: Translate): string {
  return key ? t(key) : humanize(code);
}

export function gapTypeText(type: string, t: Translate): string {
  return labelOr(GAP_TYPE_LABELS[type as keyof typeof GAP_TYPE_LABELS], type, t);
}

const GAP_STATUS_LABELS: Record<string, I18nKey> = {
  open: "coord.gap_status.open",
  closed_completed: "coord.gap_status.closed_completed",
  closed_refused: "coord.gap_status.closed_refused",
  suppressed: "coord.gap_status.suppressed",
  superseded: "coord.gap_status.superseded",
  scheduled: "coord.gap_status.scheduled",
  cancelled: "coord.gap_status.cancelled",
};

export function gapStatusText(status: string, t: Translate): string {
  return labelOr(GAP_STATUS_LABELS[status], status, t);
}

const SLOT_LABELS: Record<string, I18nKey> = { weekday: "coord.slot.weekday", evening: "coord.slot.evening", weekend: "coord.slot.weekend" };

export function slotText(slot: string, t: Translate): string {
  return SLOT_LABELS[slot] ? t(SLOT_LABELS[slot]) : slot;
}

export function templateText(key: string, t: Translate): string {
  return labelOr(MESSAGE_KEY_LABELS[key as MessageKey], key, t);
}

export function appointmentTypeText(type: string, t: Translate): string {
  return APPOINTMENT_TYPE_LABELS[type] ? t(APPOINTMENT_TYPE_LABELS[type]) : type;
}

/** Simulated outreach status wording — approval is never delivery. */
export function outreachOutcomeText(outcome: string | null, t: Translate): string {
  if (outcome === "simulated_not_sent") return t("coord.outreach_status.simulated_not_sent");
  if (outcome === "suppressed" || outcome === "outreach_suppressed") return t("coord.outreach_status.suppressed");
  return outcome ? humanize(outcome) : t("coord.outreach_status.recorded");
}

export function memberName(team: Map<string, CareTeamMemberOut> | null, userId: string | null, t: Translate): string {
  if (!userId) return t("coord.member.unassigned");
  const m = team?.get(userId);
  return m ? (m.is_self ? t("coord.member.you", { name: m.full_name }) : m.full_name) : t("coord.member.unknown");
}

export function actorLabel(team: Map<string, CareTeamMemberOut> | null, userId: string, role: string, t: Translate): string {
  if (role === "PATIENT") return t("role.PATIENT");
  const m = team?.get(userId);
  return m ? (m.is_self ? t("coord.actor.you") : m.full_name) : ROLE_LABELS[role] ? t(ROLE_LABELS[role]) : t("coord.actor.staff");
}

/** One-line description of a task event; internal text stays in `detail`. */
export function taskEventText(
  e: Pick<TaskEventOut, "event_type" | "to_status" | "from_status" | "priority" | "contact_channel" | "response_code">,
  t: Translate
): string {
  switch (e.event_type) {
    case "created": {
      const meta = TASK_STATUS_META[(e.to_status as TaskStatus) ?? "open"];
      return t("coord.event.created", { status: meta ? t(meta.label) : String(e.to_status) });
    }
    case "assigned":
      return t("coord.event.assigned");
    case "status_changed":
      return t("coord.event.status_changed", { from: statusText(e.from_status, t), to: statusText(e.to_status, t) });
    case "due_date_changed":
      return t("coord.event.due_date_changed");
    case "priority_changed": {
      const meta = PRIORITY_META[e.priority as TaskPriority];
      return t("coord.event.priority_changed", { priority: meta ? t(meta.label) : String(e.priority) });
    }
    case "staff_note":
      return t("coord.event.staff_note");
    case "staff_message":
      return t("coord.event.staff_message");
    case "patient_response":
      return t("coord.event.patient_response", { response: labelOr(PATIENT_RESPONSE_LABELS[e.response_code ?? ""], e.response_code ?? "reply", t) });
    case "assistance_requested":
      return t("coord.event.assistance_requested");
    case "appointment_requested":
      return t("coord.event.appointment_requested");
    case "escalated":
      return t("coord.event.escalated");
    case "completed":
      return t("coord.event.completed");
    case "contact_attempt": {
      const channel = CONTACT_CHANNEL_LABELS[e.contact_channel as ContactChannel];
      const outcome = CONTACT_OUTCOME_META[e.response_code as ContactOutcome];
      return t("coord.event.contact_attempt", {
        channel: channel ? t(channel) : String(e.contact_channel),
        outcome: outcome ? t(outcome.label) : String(e.response_code),
      });
    }
    default:
      return humanize(e.event_type);
  }
}

export function statusText(s: string | null, t: Translate): string {
  if (!s) return "—";
  const meta = TASK_STATUS_META[s as TaskStatus];
  return meta ? t(meta.label) : humanize(s);
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

const DATE_OPTIONS: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" };

/** `16 Nov 2026` (English) / `16 نوفمبر 2026` (Arabic, Western digits). */
export function formatDate(value: string | null, locale: Locale = "en"): string {
  if (!value) return "—";
  const d = new Date(value.length === 10 ? `${value}T00:00:00Z` : value);
  return d.toLocaleDateString(intlLocale(locale), DATE_OPTIONS);
}

export function formatDateTime(value: string, locale: Locale = "en"): string {
  return new Date(value).toLocaleString(intlLocale(locale), { ...DATE_OPTIONS, hour: "2-digit", minute: "2-digit" }) + " UTC";
}

/** "in 3 days" / "2 days overdue" relative to `today` (ISO date). */
export function dueText(due: string | null, today: string, terminal: boolean, t: Translate, locale: Locale = "en"): string {
  if (!due) return t("coord.due.none");
  const days = Math.round((Date.parse(`${due}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
  if (terminal) return t("coord.due.on", { date: formatDate(due, locale) });
  if (days < 0) return t(days === -1 ? "coord.due.overdue_one" : "coord.due.overdue_n", { count: String(-days) });
  if (days === 0) return t("coord.due.today");
  return t(days === 1 ? "coord.due.in_one" : "coord.due.in_n", { count: String(days) });
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
export function buildTimeline(input: TimelineInput, t: Translate, locale: Locale = "en"): TimelineEntry[] {
  const out: TimelineEntry[] = [];
  for (const g of input.careGaps)
    out.push({
      id: `gap-${g.care_gap_id}`,
      at: g.identified_date,
      kind: "gap",
      title: t("coord.tl.gap_identified", { rule: g.rule_id }),
      detail: gapTypeText(g.gap_type, t),
      tone: "due",
      visibility: "record",
    });
  for (const task of input.tasks)
    for (const e of task.events)
      out.push({
        id: `task-${e.event_id}`,
        at: e.created_at,
        kind: e.event_type === "staff_note" || e.event_type === "contact_attempt" ? "note" : "task",
        title: `${taskEventText(e, t)}${e.event_type === "created" ? ` · ${MESSAGE_KEY_LABELS[task.message_key as MessageKey] ? t(MESSAGE_KEY_LABELS[task.message_key as MessageKey]) : task.message_key}` : ""}`,
        detail:
          e.event_type === "assigned"
            ? null
            : e.message ?? (e.event_type === "created" ? t("coord.tl.assigned_to", { name: memberName(input.team, task.assigned_to_user_id, t) }) : null),
        tone: eventTone(e),
        visibility: e.visibility,
        href: `/follow-up/${encodeURIComponent(task.task_id)}`,
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
        ? t("coord.tl.completion")
        : f.event_type === "outreach_attempted"
          ? t("coord.tl.outreach_approved", { outcome: outreachOutcomeText(f.outcome_status, t) })
          : f.event_type === "outreach_suppressed"
            ? t("coord.tl.outreach_suppressed", { reason: blockedReasonText(f.suppression_reason, t) })
            : t("coord.tl.gap_note", { event: humanize(f.event_type) }),
      detail: completion ? t("coord.tl.evidence", { reference: f.evidence_reference ?? "—" }) : f.note,
      tone: completion ? "completed" : f.event_type === "outreach_suppressed" ? "not_eligible" : "upcoming",
      visibility: "internal",
    });
  }
  for (const w of input.workflow) {
    const appointment = w.entity_type === "appointment";
    const to = w.to_status;
    const label = appointment
      ? labelOr(APPOINTMENT_STATUS_META[to as AppointmentStatus]?.label, to, t)
      : labelOr(REFERRAL_STATUS_META[to as ReferralStatus]?.label, to, t);
    out.push({
      id: `wf-${w.status_event_id}`,
      at: w.recorded_at,
      kind: appointment ? "appointment" : "referral",
      title: appointment
        ? `${t(w.from_status ? "coord.tl.appointment" : "coord.tl.appointment_recorded", { status: label })}${w.scheduled_datetime ? ` · ${formatDateTime(w.scheduled_datetime, locale)}` : ""}`
        : t("coord.tl.referral", { id: w.referral_id ?? "", status: label }),
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
      title: `${labelOr(REQUEST_TYPE_LABELS[r.request_type], r.request_type, t)} · ${REQUEST_STATUS_META[r.status] ? t(REQUEST_STATUS_META[r.status].label) : r.status}`,
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
        title: t("coord.tl.appointment_seed", {
          type: appointmentTypeText(a.appointment_type, t),
          status: APPOINTMENT_STATUS_META[a.status] ? t(APPOINTMENT_STATUS_META[a.status].label) : a.status,
        }),
        detail: t("coord.tl.scheduled_for", { datetime: formatDateTime(a.scheduled_datetime, locale) }),
        tone: APPOINTMENT_STATUS_META[a.status]?.tone ?? "eligible",
        visibility: "record",
      });
  for (const r of input.referrals)
    if (!withHistory.has(r.referral_id))
      out.push({
        id: `ref-${r.referral_id}`,
        at: r.trigger_date,
        kind: "referral",
        title: t("coord.tl.referral_to", {
          target: r.referral_target,
          status: REFERRAL_STATUS_META[r.status] ? t(REFERRAL_STATUS_META[r.status].label) : r.status,
        }),
        detail: t("coord.tl.triggered_by", { rule: r.trigger_rule_id }),
        tone: REFERRAL_STATUS_META[r.status]?.tone ?? "eligible",
        visibility: "record",
      });
  return out.sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : a.id.localeCompare(b.id)));
}
