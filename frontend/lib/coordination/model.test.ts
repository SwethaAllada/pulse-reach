import { describe, expect, it } from "vitest";
import type {
  AppointmentOut,
  CareGapOut,
  CareTeamMemberOut,
  FollowUpEventOut,
  ReferralOut,
  StaffPatientRequestOut,
  TaskDetailOut,
  WorkflowStatusEventOut,
} from "@/lib/api/types";
import {
  APPOINTMENT_TRANSITIONS,
  REFERRAL_TRANSITIONS,
  REQUEST_STATUS_META,
  TASK_STATUS_META,
  TASK_TRANSITIONS,
  actorLabel,
  addDays,
  blockedReasonText,
  buildTimeline,
  dueText,
  memberName,
  outreachOutcomeText,
  taskEventText,
  type TimelineInput,
} from "./model";

const gap: CareGapOut = {
  care_gap_id: "G1",
  patient_id: "P1",
  evaluation_id: "EV-1",
  rule_id: "IFHAS-PKG-ORAL",
  rule_version: "1.0.0",
  gap_type: "no_documented_screening",
  status: "open",
  identified_date: "2026-11-01",
  closed_date: null,
  closed_by_consent_id: null,
  closed_by_component_result_id: null,
  subject_ifhas_screening_id: null,
  subject_well_child_visit_id: null,
  subject_referral_id: null,
  is_synthetic: true,
};

const task: TaskDetailOut = {
  task_id: "T-1",
  organization_id: "ORG-A",
  patient_id: "P1",
  care_gap_id: "G1",
  rule_id: "IFHAS-PKG-ORAL",
  assigned_to_user_id: "U-1",
  created_by_user_id: "U-1",
  status: "completed",
  priority: "high",
  due_date: "2026-11-20",
  is_overdue: false,
  is_due_soon: false,
  escalated_at: null,
  language: "en",
  message_key: "screening_invitation",
  patient_message: "Please book.",
  patient_visible: true,
  staff_note: null,
  patient_reported_completion: false,
  completion_follow_up_id: "FU-3",
  created_at: "2026-11-02T08:00:00Z",
  updated_at: "2026-11-09T08:00:00Z",
  completed_at: "2026-11-09T08:00:00Z",
  events: [
    { event_id: "E1", event_type: "created", visibility: "patient", actor_user_id: "U-1", actor_role: "CARE_COORDINATOR", from_status: null, to_status: "open", response_code: null, message: null, priority: null, contact_channel: null, created_at: "2026-11-02T08:00:00Z" },
    { event_id: "E2", event_type: "staff_note", visibility: "internal", actor_user_id: "U-1", actor_role: "CARE_COORDINATOR", from_status: null, to_status: null, response_code: null, message: "Call after 5pm", priority: null, contact_channel: null, created_at: "2026-11-03T08:00:00Z" },
    { event_id: "E3", event_type: "patient_response", visibility: "patient", actor_user_id: "U-P", actor_role: "PATIENT", from_status: null, to_status: null, response_code: "already_done", message: null, priority: null, contact_channel: null, created_at: "2026-11-04T08:00:00Z" },
    { event_id: "E4", event_type: "completed", visibility: "patient", actor_user_id: "U-1", actor_role: "CARE_COORDINATOR", from_status: "in_progress", to_status: "completed", response_code: null, message: null, priority: null, contact_channel: null, created_at: "2026-11-09T08:00:00Z" },
  ],
};

const fu = (follow_up_id: string, event_type: string, recorded_at: string, extra: Partial<FollowUpEventOut> = {}): FollowUpEventOut => ({
  follow_up_id,
  patient_id: "P1",
  care_gap_id: "G1",
  event_type,
  outcome_status: null,
  documented_evidence: false,
  evidence_reference: null,
  contact_consent_id: null,
  suppression_reason: null,
  recorded_by: "U-1",
  recorded_at,
  note: null,
  appointment_id: null,
  referral_id: null,
  ...extra,
});

const wf = (id: string, extra: Partial<WorkflowStatusEventOut>): WorkflowStatusEventOut => ({
  status_event_id: id,
  patient_id: "P1",
  entity_type: "appointment",
  appointment_id: "A-1",
  referral_id: null,
  care_gap_id: "G1",
  from_status: null,
  to_status: "scheduled",
  scheduled_datetime: "2026-11-20T09:00:00Z",
  initiated_date: null,
  completed_date: null,
  recorded_by: "U-1",
  recorded_at: "2026-11-05T10:00:00Z",
  note: null,
  ...extra,
});

const appointment = (appointment_id: string, status: AppointmentOut["status"], scheduled_datetime: string): AppointmentOut => ({
  appointment_id,
  patient_id: "P1",
  profile_id: "FSP-1",
  care_gap_id: "G1",
  appointment_type: "ifhas_screening",
  scheduled_datetime,
  slot_type: "weekday",
  status,
  booked_via: "seed",
  is_synthetic: true,
});

const referral = (referral_id: string, status: ReferralOut["status"], trigger_date: string): ReferralOut => ({
  referral_id,
  patient_id: "P1",
  trigger_rule_id: "IFHAS-PKG-FIT",
  trigger_rule_version: "1.0.0",
  referral_target: "Gastroenterology",
  target_profile_id: null,
  trigger_date,
  initiated_date: null,
  completed_date: status === "completed" ? trigger_date : null,
  status,
});

const request: StaffPatientRequestOut = {
  request_id: "R-1",
  organization_id: "ORG-A",
  patient_id: "P1",
  submitted_by_user_id: "U-P",
  request_type: "appointment",
  status: "scheduled",
  task_id: "T-1",
  care_gap_id: "G1",
  appointment_id: "A-1",
  change_action: null,
  preferred_dates: [],
  preferred_time_of_day: null,
  message: "Mornings please",
  language: "en",
  staff_response: null,
  internal_note: null,
  handled_by_user_id: null,
  created_at: "2026-11-04T12:00:00Z",
  updated_at: "2026-11-04T12:00:00Z",
};

const team = new Map<string, CareTeamMemberOut>([
  ["U-1", { user_id: "U-1", full_name: "Amal", role: "CARE_COORDINATOR", patient_access: "assigned", is_self: true, can_be_assigned: true }],
  ["U-2", { user_id: "U-2", full_name: "Omar", role: "CLINICIAN", patient_access: "assigned", is_self: false, can_be_assigned: true }],
]);

const input = (patch: Partial<TimelineInput> = {}): TimelineInput => ({
  careGaps: [gap],
  tasks: [task],
  followUps: [
    fu("FU-1", "outreach_attempted", "2026-11-06T09:00:00Z", { outcome_status: "simulated_not_sent" }),
    fu("FU-2", "appointment_scheduled", "2026-11-05T10:00:00Z", { appointment_id: "A-1" }),
    fu("FU-3", "completion_documented", "2026-11-08T09:00:00Z", { documented_evidence: true, evidence_reference: "SYNTH-SCR-1", outcome_status: "completed" }),
    fu("FU-4", "referral_completed", "2026-11-07T09:00:00Z", { referral_id: "REF-1" }),
    fu("FU-5", "outreach_suppressed", "2026-11-06T08:00:00Z", { suppression_reason: "contact_consent_withdrawn" }),
  ],
  workflow: [
    wf("WF-1", {}),
    wf("WF-2", { from_status: "scheduled", to_status: "attended", recorded_at: "2026-11-20T11:00:00Z" }),
    wf("WF-3", { entity_type: "referral", appointment_id: null, referral_id: "REF-1", to_status: "completed", scheduled_datetime: null, recorded_at: "2026-11-07T09:00:00Z" }),
  ],
  requests: [request],
  appointments: [appointment("A-1", "attended", "2026-11-20T09:00:00Z"), appointment("A-9", "scheduled", "2026-12-01T09:00:00Z")],
  referrals: [referral("REF-1", "completed", "2026-11-01"), referral("REF-9", "pending", "2026-10-15")],
  team,
  ...patch,
});

describe("dueText", () => {
  it("describes due dates relative to today", () => {
    expect(dueText(null, "2026-11-16", false)).toBe("No due date");
    expect(dueText("2026-11-16", "2026-11-16", false)).toBe("Due today");
    expect(dueText("2026-11-17", "2026-11-16", false)).toBe("Due in 1 day");
    expect(dueText("2026-11-20", "2026-11-16", false)).toBe("Due in 4 days");
    expect(dueText("2026-11-15", "2026-11-16", false)).toBe("1 day overdue");
    expect(dueText("2026-11-01", "2026-11-16", false)).toBe("15 days overdue");
  });

  it("never calls a closed follow-up overdue", () => {
    expect(dueText("2026-11-01", "2026-11-16", true)).toBe("Due 1 Nov 2026");
    expect(dueText("2026-11-01", "2026-11-16", true)).not.toMatch(/overdue/);
  });

  it("crosses month and year boundaries", () => {
    expect(addDays("2026-12-28", 7)).toBe("2027-01-04");
    expect(dueText("2027-01-04", "2026-12-28", false)).toBe("Due in 7 days");
  });
});

describe("buildTimeline", () => {
  it("orders every entry newest first, with ties broken by id", () => {
    const t = buildTimeline(input());
    const at = t.map((e) => e.at);
    expect([...at].sort().reverse()).toEqual(at);
    const tie = buildTimeline(input({ tasks: [], followUps: [], workflow: [], requests: [], appointments: [], referrals: [], careGaps: [gap, { ...gap, care_gap_id: "G0" }] }));
    expect(tie.map((e) => e.id)).toEqual(["gap-G0", "gap-G1"]);
  });

  it("labels only a completion_documented follow-up as completion", () => {
    const t = buildTimeline(input());
    const completions = t.filter((e) => e.kind === "completion");
    expect(completions.map((e) => e.id)).toEqual(["fu-FU-3"]);
    expect(completions[0].title).toBe("Completion documented with evidence · care gap closed");
    expect(completions[0].detail).toBe("Evidence SYNTH-SCR-1");
    // Attended appointments, completed referrals, patient reports and approved outreach are not completion.
    for (const e of t.filter((x) => x.kind !== "completion")) expect(e.title).not.toMatch(/care gap closed/);
    expect(t.find((e) => e.id === "wf-WF-2")!.kind).toBe("appointment");
    expect(t.find((e) => e.id === "wf-WF-3")!.kind).toBe("referral");
    expect(t.find((e) => e.id === "task-E3")!.title).toBe("Patient response: Reports already done (unverified)");
    expect(t.find((e) => e.id === "fu-FU-1")!.title).toBe("Outreach reviewed and approved · Simulated — not sent");
  });

  it("keeps visibility: internal notes and follow-ups internal, requests patient-visible, workflow as record", () => {
    const t = buildTimeline(input());
    const byId = Object.fromEntries(t.map((e) => [e.id, e]));
    expect(byId["task-E2"]).toMatchObject({ kind: "note", visibility: "internal", title: "Internal note", detail: "Call after 5pm" });
    expect(byId["task-E1"]).toMatchObject({ kind: "task", visibility: "patient", title: "Follow-up created · Open · Screening invitation", detail: "Assigned to Amal (you)" });
    expect(byId["task-E1"].href).toBe("/follow-up/T-1");
    expect(byId["fu-FU-1"].visibility).toBe("internal");
    expect(byId["fu-FU-5"]).toMatchObject({ kind: "outreach", visibility: "internal", title: "Outreach suppressed · The patient withdrew contact consent.", tone: "not_eligible" });
    expect(byId["req-R-1"]).toMatchObject({ kind: "request", visibility: "patient", title: "Appointment request · Appointment recorded" });
    expect(byId["wf-WF-1"]).toMatchObject({ visibility: "record" });
    expect(byId["wf-WF-1"].title).toMatch(/^Appointment recorded · Recorded · 20 Nov 2026/);
    expect(byId["wf-WF-2"].title).toMatch(/^Appointment · Attended/);
  });

  it("skips gap events that duplicate workflow history and lists seed records once", () => {
    const t = buildTimeline(input());
    const ids = t.map((e) => e.id);
    expect(ids).not.toContain("fu-FU-2");
    expect(ids).not.toContain("fu-FU-4");
    // A-1 and REF-1 have workflow history; A-9 and REF-9 are seed records without it.
    expect(ids).not.toContain("apt-A-1");
    expect(ids).not.toContain("ref-REF-1");
    expect(ids).toContain("apt-A-9");
    expect(ids).toContain("ref-REF-9");
    expect(t.find((e) => e.id === "ref-REF-9")!.title).toBe("Referral to Gastroenterology · Pending");
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("vocabulary", () => {
  it("never offers completion as a plain status transition", () => {
    for (const next of Object.values(TASK_TRANSITIONS)) expect(next).not.toContain("completed");
    expect(TASK_TRANSITIONS.completed).toEqual([]);
    expect(TASK_TRANSITIONS.cancelled).toEqual([]);
    expect(APPOINTMENT_TRANSITIONS.attended).toEqual([]);
    expect(REFERRAL_TRANSITIONS.pending).not.toContain("completed");
    expect(TASK_STATUS_META.completed.description).toMatch(/evidence/);
    expect(REQUEST_STATUS_META.scheduled.label).toBe("Appointment recorded");
  });

  it("describes simulated outreach without ever calling it sent", () => {
    expect(outreachOutcomeText("simulated_not_sent")).toBe("Simulated — not sent");
    expect(outreachOutcomeText("outreach_suppressed")).toBe("Suppressed — not permitted");
    expect(outreachOutcomeText(null)).toBe("Recorded");
    expect(blockedReasonText("contact_consent_absent")).toBe("No current contact consent is recorded for this programme.");
    expect(blockedReasonText("contact_details_unverified")).toBe("The recorded contact details are not verified.");
    expect(blockedReasonText(null)).toBe("Outreach is not permitted for this person.");
    expect(blockedReasonText("some_new_reason")).toBe("Some new reason");
  });

  it("names people and events from the care team", () => {
    expect(memberName(team, "U-1")).toBe("Amal (you)");
    expect(memberName(team, "U-2")).toBe("Omar");
    expect(memberName(team, null)).toBe("Unassigned");
    expect(memberName(team, "U-404")).toBe("Care-team member");
    expect(actorLabel(team, "U-P", "PATIENT")).toBe("Patient");
    expect(actorLabel(team, "U-1", "CARE_COORDINATOR")).toBe("You");
    expect(actorLabel(null, "U-3", "CLINICIAN")).toBe("Clinician");
    expect(
      taskEventText({ event_type: "contact_attempt", contact_channel: "phone", response_code: "no_answer", to_status: null, from_status: null, priority: null })
    ).toBe("Contact attempt · Phone call · No answer");
    expect(
      taskEventText({ event_type: "status_changed", from_status: "open", to_status: "in_progress", contact_channel: null, response_code: null, priority: null })
    ).toBe("Status: Open → In progress");
  });
});
