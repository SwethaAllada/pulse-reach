import type {
  AppointmentCreateIn,
  AppointmentOut,
  AppointmentPatchIn,
  CareGapDetailOut,
  CareGapOut,
  CareTeamMemberOut,
  DashboardSummaryOut,
  EvaluationItemOut,
  FollowUpCreateIn,
  FollowUpEventOut,
  MeOut,
  OpenQuestionOut,
  OutreachDraftIn,
  OutreachDraftOut,
  OutreachReviewIn,
  OutreachReviewOut,
  Pathway,
  PatientActivityOut,
  PatientSummaryOut,
  PopulationSummaryOut,
  ProgrammeSummaryOut,
  ReferralOut,
  ReferralPatchIn,
  RequestUpdateIn,
  RuleDetailOut,
  RuleSummaryOut,
  ServiceProfilesOut,
  StaffPatientRequestOut,
  TaskCreateIn,
  TaskDetailOut,
  TaskEventOut,
  TaskPriority,
  TaskStatus,
  TaskSummaryOut,
  TaskUpdateIn,
  WorkflowHistoryOut,
  WorkflowStatusEventOut,
} from "@/lib/api/types";
import ROLE_PERMISSION_MATRIX from "./role-permissions.json";

/** Small synthetic fixture mirroring backend response shapes. */
const patient = (
  patient_id: string,
  pathway: "ifhas" | "well_child",
  history: "available" | "partial" | "not_available",
  region_id: number,
  sex: "female" | "male",
  date_of_birth: string | null = null
): PatientSummaryOut => ({
  patient_id,
  is_synthetic: true,
  sex,
  region_id,
  date_of_birth,
  history_by_pathway: { [pathway]: history },
});

export const PATIENTS: PatientSummaryOut[] = [
  patient("SYNTH-PAT-1", "ifhas", "available", 1, "female", "1980-05-20"),
  patient("SYNTH-PAT-2", "ifhas", "not_available", 2, "male", "1970-01-01"),
  patient("SYNTH-PAT-3", "ifhas", "partial", 1, "male"),
  patient("SYNTH-PAT-4", "ifhas", "available", 1, "male", "1960-11-16"),
  patient("SYNTH-PAT-5", "well_child", "available", 3, "female", "2026-05-10"),
  patient("SYNTH-PAT-6", "well_child", "not_available", 1, "female", "2024-01-01"),
];

const rule = (
  rule_id: string,
  pathway: "ifhas" | "well_child",
  description: string,
  extra: Partial<RuleSummaryOut> = {}
): RuleSummaryOut => ({
  rule_id,
  rule_version: "1.0.0",
  pathway,
  rule_type: "screening_package",
  source_name: pathway === "ifhas" ? "IFHAS Standard" : "Well-Child Standard",
  source_version: "V10",
  source_reference: `${rule_id} source, PDF p.1`,
  description,
  is_authoritative: true,
  requires_clinical_review: false,
  verification_status: "verified",
  effective_date_text: "2025-07",
  open_question_ids: [],
  ...extra,
});

export const RULES: RuleSummaryOut[] = [
  rule("IFHAS-PKG-ORAL", "ifhas", "Oral Health Package: target group 18-75"),
  rule("IFHAS-PKG-FIT", "ifhas", "Standalone FIT screening: target group 40-75"),
  rule("WCV-VISIT-06M", "well_child", "Well-Child visit at 6 months: age, required services", { rule_type: "visit_schedule" }),
  rule("IFHAS-PKG-LUNG", "ifhas", "Lung screening: target group 55-75 high risk", {
    is_authoritative: false,
    requires_clinical_review: true,
    open_question_ids: ["OQ-LUNG"],
  }),
  rule("IFHAS-PROG-ELIG-MIN-AGE", "ifhas", "Minimum age: 18 years and above", { rule_type: "programme_eligibility" }),
];

const gap = (
  care_gap_id: string,
  patient_id: string,
  rule_id: string,
  status: CareGapOut["status"] = "open",
  gap_type: CareGapOut["gap_type"] = "no_documented_screening",
  extra: Partial<CareGapOut> = {}
): CareGapOut => ({
  care_gap_id,
  patient_id,
  evaluation_id: `EV-${patient_id}-${rule_id}`,
  rule_id,
  rule_version: "1.0.0",
  gap_type,
  status,
  identified_date: "2026-11-16",
  closed_date: null,
  closed_by_consent_id: null,
  closed_by_component_result_id: null,
  subject_ifhas_screening_id: null,
  subject_well_child_visit_id: null,
  subject_referral_id: null,
  is_synthetic: true,
  ...extra,
});

export const CARE_GAPS: CareGapOut[] = [
  gap("G1", "SYNTH-PAT-1", "IFHAS-PKG-ORAL"),
  gap("G2", "SYNTH-PAT-1", "IFHAS-PKG-FIT", "open", "partial_completion", { subject_ifhas_screening_id: "SYNTH-SCR-9" }),
  gap("G3", "SYNTH-PAT-5", "WCV-VISIT-06M"),
  gap("G4", "SYNTH-PAT-4", "IFHAS-PKG-ORAL", "closed_refused", "no_documented_screening", {
    closed_date: "2026-11-01",
    closed_by_consent_id: "SYNTH-CON-1",
  }),
];

/** Gaps returned only by `/patients/{id}/evaluations` (not part of the population roll-up fixture). */
const PROFILE_ONLY_GAPS: CareGapOut[] = [
  gap("G5", "SYNTH-PAT-4", "IFHAS-PKG-FIT", "closed_completed", "interval_elapsed", { closed_date: "2026-10-01" }),
  gap("G6", "SYNTH-PAT-3", "IFHAS-UNLISTED"),
];

const evaluation = (
  patient_id: string,
  rule_id: string,
  evaluation_status: string,
  extra: Partial<EvaluationItemOut> = {}
): EvaluationItemOut => ({
  evaluation_id: `EV-${patient_id}-${rule_id}`,
  patient_id,
  rule_id,
  rule_version: "1.0.0",
  pathway: rule_id.startsWith("WCV") ? "well_child" : "ifhas",
  rule_type: RULES.find((r) => r.rule_id === rule_id)?.rule_type ?? "screening_package",
  evaluation_status,
  reason_code: null,
  next_due_date: null,
  evaluated_at: "2026-11-16T09:00:00Z",
  reasons: [],
  ...extra,
});

const reviewFlag = {
  reason_code: "rule_requires_clinical_review",
  reasons: [{ reason_ordinal: 1, reason_code: "rule_requires_clinical_review", guard_id: "GUARD-RULE-REVIEW-FLAG", item_category: null, item_code: null }],
};

export const EVALUATIONS: Record<string, EvaluationItemOut[]> = {
  "SYNTH-PAT-1": [
    evaluation("SYNTH-PAT-1", "IFHAS-PROG-ELIG-MIN-AGE", "eligible"),
    evaluation("SYNTH-PAT-1", "IFHAS-PKG-ORAL", "due", { next_due_date: "2026-11-16" }),
    evaluation("SYNTH-PAT-1", "IFHAS-PKG-FIT", "due", { next_due_date: "2026-11-16" }),
    evaluation("SYNTH-PAT-1", "IFHAS-PKG-LUNG", "requires_clinical_review", reviewFlag),
    evaluation("SYNTH-PAT-1", "WCV-VISIT-06M", "not_eligible"),
  ],
  "SYNTH-PAT-2": [
    evaluation("SYNTH-PAT-2", "IFHAS-PROG-ELIG-MIN-AGE", "eligible"),
    evaluation("SYNTH-PAT-2", "IFHAS-PKG-ORAL", "unknown", {
      reason_code: "missing_screening_history",
      reasons: [{ reason_ordinal: 1, reason_code: "missing_screening_history", guard_id: "GUARD-MISSING-HISTORY", item_category: null, item_code: null }],
    }),
  ],
  "SYNTH-PAT-3": [evaluation("SYNTH-PAT-3", "IFHAS-UNLISTED", "due")],
  "SYNTH-PAT-4": [
    evaluation("SYNTH-PAT-4", "IFHAS-PKG-ORAL", "due"),
    evaluation("SYNTH-PAT-4", "IFHAS-PKG-FIT", "completed", { next_due_date: "2027-10-01" }),
  ],
  "SYNTH-PAT-5": [evaluation("SYNTH-PAT-5", "WCV-VISIT-06M", "due", { next_due_date: "2026-11-10" })],
  "SYNTH-PAT-6": [],
};

export const RULE_DETAILS: Record<string, RuleDetailOut> = {
  "IFHAS-PKG-ORAL": {
    ...RULES[0],
    notes: null,
    spec: {
      eligibility: { age: { min_years: 18, max_years: 75, as_printed: "18-75 years (configured)" }, sex: ["female", "male"], conditions: [] },
      frequency: { as_printed: "Every 3 years (configured)", interval: { value: 3, unit: "years" } },
    },
    items: [
      { category: "package_component", code: "dental", ordinal: 1, description: "Dental examination", source_reference: "p.1", verification_status: "verified", effective_authority: true },
    ],
  },
};

export const SUMMARY: DashboardSummaryOut = {
  is_synthetic: true,
  run_id: "SYNTH-RUN-0001",
  evaluation_run_id: "SYNTH-EVR-000001",
  reference_date: "2026-11-16",
  total_patients: 6,
  n_adults: 4,
  n_children: 2,
  open_care_gaps_count: 3,
  closed_refused_care_gaps_count: 1,
  evaluation_status_counts: { due: 3, unknown: 5, not_eligible: 10 },
  rules_summary: {
    total_rules: 3,
    authoritative_rules: 3,
    review_flagged_rules: 0,
    unresolved_rules: 0,
    total_rule_items: 3,
    clinical_review_status: "not_reviewed",
  },
  governance_disclaimer: "synthetic",
  pathway_breakdown: {
    ifhas: {
      patients_with_history: 3,
      programme_eligible_patients: 4,
      due_or_upcoming_patients: 2,
      unknown_history_patients: 1,
      review_flagged_patients: 0,
      rule_review_patients: 4,
      open_care_gaps_count: 2,
    },
    well_child: {
      patients_with_history: 1,
      programme_eligible_patients: 2,
      due_or_upcoming_patients: 1,
      unknown_history_patients: 1,
      review_flagged_patients: 0,
      rule_review_patients: 0,
      open_care_gaps_count: 1,
    },
  },
};

export const OPEN_QUESTIONS: OpenQuestionOut[] = [
  {
    oq_id: "OQ-LUNG",
    category: "interpretation",
    status: "open",
    title: "Lung screening high-risk criteria",
    detail: "The standard does not define high risk.",
    affects: [],
    resolve_via: "DoH clarification",
    resolution: null,
    resolved_on: null,
    rule_ids: ["IFHAS-PKG-LUNG"],
  },
];

export const POPULATION_SUMMARY: PopulationSummaryOut = {
  is_synthetic: true,
  as_of: "2026-11-16",
  complete_through: "2026-11-02",
  disclaimer: "Aggregates of synthetic records.",
  total_population: 6,
  latest_aggregation_at: null,
  preventive_care: {
    in_scope_patients: 6,
    patients_with_open_gap: 2,
    in_scope_patients_with_open_gap: 2,
    open_care_gaps: 3,
    preventive_coverage: 0.666667,
    preventive_coverage_definition: "in-scope patients without an open preventive-care gap / in-scope patients",
    care_gap_history_start: "2026-09-15",
    period: "90d",
    period_metrics: {
      period_days: 90,
      current_start: "2026-08-19",
      current_end: "2026-11-16",
      previous_start: "2026-05-21",
      previous_end: "2026-08-18",
      screening_completions: 5,
      previous_screening_completions: 3,
      care_gaps_identified: 4,
      previous_care_gaps_identified: 0,
      care_gap_trend: { direction: "INSUFFICIENT_DATA", reason_codes: ["history_incomplete"], absolute_change: 4, percentage_change: null },
      follow_up_completion_rate: null,
      suppressed: ["follow_up_completed"],
    },
    suppressed: [],
  },
};

export function me(role: string, permissions: string[], patient_access = "organization"): MeOut {
  return {
    user: { user_id: `U-${role}`, email: `${role.toLowerCase()}@demo.invalid`, full_name: `Demo ${role} (synthetic)`, preferred_language: "en" },
    organization_id: "ORG-A",
    role,
    permissions,
    patient_linked: role === "PATIENT",
    memberships: [{ organization_id: "ORG-A", organization_name: "Demo Org A", role, patient_access, is_active: true }],
    locale: "en",
    direction: "ltr",
  };
}

/**
 * Backend role → permission matrix at each role's default patient access
 * (`backend/app/core/permissions.py`; parity checked by `backend/tests/test_rbac.py`).
 */
export const ROLE_PERMISSIONS = ROLE_PERMISSION_MATRIX as Record<
  "SYSTEM_ADMIN" | "POPULATION_HEALTH_MANAGER" | "CARE_COORDINATOR" | "CLINICIAN" | "PATIENT",
  string[]
>;

export const MANAGER_PERMISSIONS = [
  "care_gaps.read",
  "evaluations.read",
  "insights.read",
  "patients.read",
  "patients.read_assigned",
  "population.read",
  "rules.read",
];

export class FakeHttpError extends Error {
  /** `body` = the backend error body (`{ error: { code, message } }`); defaults to a 404 detail. */
  constructor(
    readonly status: number,
    readonly body?: unknown
  ) {
    super(`HTTP ${status}`);
  }
}

/** Backend error body (`app/core/errors.py` shape). */
export const errorBody = (code: string, message: string) => ({ error: { code, message } });

/* ── Coordination fixtures (follow-up tasks, requests, appointments, referrals, outreach) ──
 * Mirrors `backend/app/schemas/portal.py` and `backend/app/schemas/v1.py`. Writes mutate an
 * in-memory store so refetches after a write see the change; call `resetCoordinationFixtures()`
 * between tests that write. */

/** The fake caller (`is_self`) and the other care-team members. */
export const CARE_TEAM: CareTeamMemberOut[] = [
  { user_id: "U-COORD", full_name: "Amal Coordinator (synthetic)", role: "CARE_COORDINATOR", patient_access: "assigned", is_self: true, can_be_assigned: true },
  { user_id: "U-CLIN", full_name: "Omar Clinician (synthetic)", role: "CLINICIAN", patient_access: "assigned", is_self: false, can_be_assigned: true },
  { user_id: "U-MGR", full_name: "Sara Manager (synthetic)", role: "POPULATION_HEALTH_MANAGER", patient_access: "organization", is_self: false, can_be_assigned: false },
];
const SELF_ID = "U-COORD";
const COORD_AS_OF = "2026-11-16";
const TERMINAL: TaskStatus[] = ["completed", "cancelled"];

const taskEvent = (
  event_id: string,
  event_type: string,
  visibility: "patient" | "internal",
  created_at: string,
  extra: Partial<TaskEventOut> = {}
): TaskEventOut => ({
  event_id,
  event_type,
  visibility,
  actor_user_id: SELF_ID,
  actor_role: "CARE_COORDINATOR",
  from_status: null,
  to_status: null,
  response_code: null,
  message: null,
  priority: null,
  contact_channel: null,
  created_at,
  ...extra,
});

const followUpTask = (task_id: string, patient_id: string, extra: Partial<TaskDetailOut>): TaskDetailOut => ({
  task_id,
  organization_id: "ORG-A",
  patient_id,
  care_gap_id: null,
  rule_id: null,
  assigned_to_user_id: null,
  created_by_user_id: SELF_ID,
  status: "open",
  priority: "routine",
  due_date: null,
  is_overdue: false,
  is_due_soon: false,
  escalated_at: null,
  language: "en",
  message_key: "general_check_in",
  patient_message: "Please contact your health centre about your preventive care.",
  patient_visible: true,
  staff_note: null,
  patient_reported_completion: false,
  completion_follow_up_id: null,
  created_at: "2026-11-01T08:00:00Z",
  updated_at: "2026-11-01T08:00:00Z",
  completed_at: null,
  events: [],
  ...extra,
});

const followUpEvent = (follow_up_id: string, patient_id: string, care_gap_id: string, event_type: string, recorded_at: string, extra: Partial<FollowUpEventOut> = {}): FollowUpEventOut => ({
  follow_up_id,
  patient_id,
  care_gap_id,
  event_type,
  outcome_status: null,
  documented_evidence: false,
  evidence_reference: null,
  contact_consent_id: null,
  suppression_reason: null,
  recorded_by: SELF_ID,
  recorded_at,
  note: null,
  appointment_id: null,
  referral_id: null,
  ...extra,
});

const workflowEvent = (status_event_id: string, patient_id: string, extra: Partial<WorkflowStatusEventOut>): WorkflowStatusEventOut => ({
  status_event_id,
  patient_id,
  entity_type: "appointment",
  appointment_id: null,
  referral_id: null,
  care_gap_id: null,
  from_status: null,
  to_status: "scheduled",
  scheduled_datetime: null,
  initiated_date: null,
  completed_date: null,
  recorded_by: SELF_ID,
  recorded_at: "2026-11-12T10:00:00Z",
  note: null,
  ...extra,
});

function seedCoordination() {
  const tasks: TaskDetailOut[] = [
    // Active, patient-visible, assigned to the caller.
    followUpTask("T-1", "SYNTH-PAT-1", {
      care_gap_id: "G1",
      rule_id: "IFHAS-PKG-ORAL",
      assigned_to_user_id: "U-COORD",
      status: "awaiting_patient",
      priority: "high",
      due_date: "2099-01-15",
      message_key: "screening_invitation",
      patient_message: "You are due for an oral health check. Please book a visit.",
      staff_note: "Prefers evening calls",
      created_at: "2026-11-05T08:00:00Z",
      updated_at: "2026-11-06T09:00:00Z",
      events: [
        taskEvent("E-1", "created", "patient", "2026-11-05T08:00:00Z", { to_status: "open" }),
        taskEvent("E-2", "staff_note", "internal", "2026-11-05T08:05:00Z", { message: "Prefers evening calls" }),
        taskEvent("E-3", "status_changed", "patient", "2026-11-06T09:00:00Z", { from_status: "open", to_status: "awaiting_patient" }),
      ],
    }),
    // Overdue, internal-only, unassigned.
    followUpTask("T-2", "SYNTH-PAT-1", {
      care_gap_id: "G2",
      rule_id: "IFHAS-PKG-FIT",
      status: "open",
      priority: "urgent",
      due_date: "2020-01-01",
      is_overdue: true,
      patient_visible: false,
      message_key: "complete_outstanding",
      created_at: "2026-11-07T08:00:00Z",
      events: [
        taskEvent("E-4", "created", "internal", "2026-11-07T08:00:00Z", { to_status: "open" }),
        taskEvent("E-5", "contact_attempt", "internal", "2026-11-08T10:00:00Z", {
          contact_channel: "phone",
          response_code: "no_answer",
          message: "No answer on mobile",
        }),
      ],
    }),
    // Completed with documented evidence.
    followUpTask("T-3", "SYNTH-PAT-4", {
      care_gap_id: "G5",
      rule_id: "IFHAS-PKG-FIT",
      assigned_to_user_id: "U-CLIN",
      status: "completed",
      due_date: "2026-10-01",
      completed_at: "2026-10-02T10:00:00Z",
      completion_follow_up_id: "FU-DONE-1",
      message_key: "screening_invitation",
      events: [
        taskEvent("E-6", "created", "patient", "2026-09-20T08:00:00Z", { to_status: "open" }),
        taskEvent("E-7", "completed", "patient", "2026-10-02T10:00:00Z", { from_status: "in_progress", to_status: "completed" }),
      ],
    }),
    // General follow-up without a care gap.
    followUpTask("T-4", "SYNTH-PAT-5", {
      assigned_to_user_id: "U-CLIN",
      status: "in_progress",
      due_date: "2099-02-01",
      events: [taskEvent("E-8", "created", "patient", "2026-11-09T08:00:00Z", { to_status: "open" })],
    }),
  ];
  const requests: StaffPatientRequestOut[] = [
    {
      request_id: "R-1",
      organization_id: "ORG-A",
      patient_id: "SYNTH-PAT-1",
      submitted_by_user_id: "U-PAT-1",
      request_type: "appointment",
      status: "submitted",
      task_id: "T-1",
      care_gap_id: "G1",
      appointment_id: null,
      change_action: null,
      preferred_dates: ["2026-12-03"],
      preferred_time_of_day: "morning",
      message: "Could I come in the morning?",
      language: "en",
      staff_response: null,
      internal_note: null,
      handled_by_user_id: null,
      created_at: "2026-11-10T08:00:00Z",
      updated_at: "2026-11-10T08:00:00Z",
    },
    {
      request_id: "R-2",
      organization_id: "ORG-A",
      patient_id: "SYNTH-PAT-5",
      submitted_by_user_id: "U-PAT-5",
      request_type: "assistance",
      status: "acknowledged",
      task_id: null,
      care_gap_id: null,
      appointment_id: null,
      change_action: null,
      preferred_dates: [],
      preferred_time_of_day: null,
      message: "I need help finding a clinic.",
      language: "en",
      staff_response: "We will call you.",
      internal_note: "Guardian handles calls",
      handled_by_user_id: "U-COORD",
      created_at: "2026-11-11T08:00:00Z",
      updated_at: "2026-11-11T09:00:00Z",
    },
  ];
  const appointments: AppointmentOut[] = [
    {
      appointment_id: "A-1",
      patient_id: "SYNTH-PAT-1",
      profile_id: "FSP-1",
      care_gap_id: "G1",
      appointment_type: "ifhas_screening",
      scheduled_datetime: "2099-12-01T09:00:00Z",
      slot_type: "weekday",
      status: "scheduled",
      booked_via: "staff_portal",
      is_synthetic: true,
    },
    // Seed record without workflow history.
    {
      appointment_id: "A-2",
      patient_id: "SYNTH-PAT-4",
      profile_id: "FSP-2",
      care_gap_id: null,
      appointment_type: "ifhas_screening",
      scheduled_datetime: "2026-09-20T10:00:00Z",
      slot_type: "weekend",
      status: "attended",
      booked_via: "seed",
      is_synthetic: true,
    },
  ];
  const referrals: ReferralOut[] = [
    {
      referral_id: "REF-1",
      patient_id: "SYNTH-PAT-1",
      trigger_rule_id: "IFHAS-PKG-FIT",
      trigger_rule_version: "1.0.0",
      referral_target: "Gastroenterology",
      target_profile_id: null,
      trigger_date: "2026-11-01",
      initiated_date: null,
      completed_date: null,
      status: "pending",
    },
    {
      referral_id: "REF-2",
      patient_id: "SYNTH-PAT-4",
      trigger_rule_id: "IFHAS-PKG-FIT",
      trigger_rule_version: "1.0.0",
      referral_target: "Colonoscopy unit",
      target_profile_id: null,
      trigger_date: "2026-08-01",
      initiated_date: "2026-08-05",
      completed_date: "2026-09-01",
      status: "completed",
    },
  ];
  const workflow: WorkflowStatusEventOut[] = [
    workflowEvent("WF-1", "SYNTH-PAT-1", {
      appointment_id: "A-1",
      care_gap_id: "G1",
      to_status: "scheduled",
      scheduled_datetime: "2099-12-01T09:00:00Z",
      recorded_at: "2026-11-12T10:00:00Z",
      note: "Booked by phone",
    }),
  ];
  const followUps: FollowUpEventOut[] = [
    followUpEvent("FU-1", "SYNTH-PAT-1", "G1", "outreach_attempted", "2026-11-13T09:00:00Z", { outcome_status: "simulated_not_sent" }),
    followUpEvent("FU-DONE-1", "SYNTH-PAT-4", "G5", "completion_documented", "2026-10-02T09:30:00Z", {
      outcome_status: "completed",
      documented_evidence: true,
      evidence_reference: "SYNTH-SCR-42",
    }),
  ];
  return { tasks, requests, appointments, referrals, workflow, followUps, seq: 0 };
}

let coord = seedCoordination();

/** Restores the coordination store (tasks, requests, appointments, …) to its seed state. */
export function resetCoordinationFixtures(): void {
  coord = seedCoordination();
}

/** Current coordination store, for assertions on what a write changed. */
export function coordinationState() {
  return coord;
}

export const SERVICE_PROFILES: ServiceProfilesOut = {
  notice: "Simulated service profiles — not real facility availability or a booking system.",
  items: [
    { profile_id: "FSP-1", facility_id: 101, facility_name: "Synthetic Health Centre A", offers_ifhas: true, offers_wcv: false, evening_hours: true, weekend_hours: false, capability_basis: "simulated" },
    { profile_id: "FSP-2", facility_id: 102, facility_name: "Synthetic Health Centre B", offers_ifhas: true, offers_wcv: true, evening_hours: false, weekend_hours: true, capability_basis: "simulated" },
  ],
};

/** Draft body the fake outreach endpoint returns (deterministic template). */
export const OUTREACH_DRAFT_BODY = "Dear patient, you are due for a preventive check. Please book a visit at your health centre.";

const nextId = (prefix: string) => `${prefix}-NEW-${++coord.seq}`;
const stamp = () => new Date(Date.UTC(2026, 10, 16, 12, coord.seq)).toISOString();

function filterTasks(q: URLSearchParams): TaskDetailOut[] {
  const s = (k: string) => q.get(k);
  return coord.tasks
    .filter((t) => {
      if (s("patient_id") && t.patient_id !== s("patient_id")) return false;
      if (s("status") && t.status !== s("status")) return false;
      if (s("active") !== null && TERMINAL.includes(t.status) === (s("active") === "true")) return false;
      if (s("priority") && t.priority !== s("priority")) return false;
      const a = s("assigned_to");
      if (a && (a === "unassigned" ? t.assigned_to_user_id !== null : t.assigned_to_user_id !== (a === "me" ? SELF_ID : a))) return false;
      if (s("overdue") === "true" && !t.is_overdue) return false;
      if (s("pathway") && RULES.find((r) => r.rule_id === t.rule_id)?.pathway !== s("pathway")) return false;
      if (s("region_id") && PATIENTS.find((p) => p.patient_id === t.patient_id)?.region_id !== Number(s("region_id"))) return false;
      if (s("due_after") && (!t.due_date || t.due_date < s("due_after")!)) return false;
      if (s("due_before") && (!t.due_date || t.due_date > s("due_before")!)) return false;
      return true;
    })
    .sort((a, b) => (a.due_date ?? "9999").localeCompare(b.due_date ?? "9999"));
}

function taskSummary(q: URLSearchParams): TaskSummaryOut {
  const tasks = filterTasks(q);
  const active = tasks.filter((t) => !TERMINAL.includes(t.status));
  const statuses: TaskStatus[] = ["open", "awaiting_patient", "patient_responded", "in_progress", "completed", "cancelled"];
  const priorities: TaskPriority[] = ["urgent", "high", "routine"];
  const assignees = [...new Set(active.map((t) => t.assigned_to_user_id))];
  return {
    as_of: COORD_AS_OF,
    due_soon_days: 7,
    total: tasks.length,
    active: active.length,
    overdue: active.filter((t) => t.is_overdue).length,
    due_soon: active.filter((t) => t.is_due_soon).length,
    completed: tasks.filter((t) => t.status === "completed").length,
    cancelled: tasks.filter((t) => t.status === "cancelled").length,
    unassigned_active: active.filter((t) => t.assigned_to_user_id === null).length,
    patient_reported_completion: active.filter((t) => t.patient_reported_completion).length,
    by_status: Object.fromEntries(statuses.map((s) => [s, tasks.filter((t) => t.status === s).length])) as Record<TaskStatus, number>,
    active_by_priority: Object.fromEntries(priorities.map((p) => [p, active.filter((t) => t.priority === p).length])) as Record<TaskPriority, number>,
    workload: assignees.map((id) => {
      const mine = active.filter((t) => t.assigned_to_user_id === id);
      return {
        assigned_to_user_id: id,
        active: mine.length,
        overdue: mine.filter((t) => t.is_overdue).length,
        due_soon: mine.filter((t) => t.is_due_soon).length,
        urgent: mine.filter((t) => t.priority === "urgent").length,
      };
    }),
    recent_events: tasks
      .flatMap((t) =>
        t.events.map((e) => ({
          event_id: e.event_id,
          task_id: t.task_id,
          patient_id: t.patient_id,
          event_type: e.event_type,
          visibility: e.visibility,
          actor_user_id: e.actor_user_id,
          actor_role: e.actor_role,
          to_status: e.to_status,
          response_code: e.response_code,
          priority: e.priority,
          contact_channel: e.contact_channel,
          created_at: e.created_at,
        }))
      )
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .slice(0, 5),
  };
}

function findTask(id: string): TaskDetailOut {
  const t = coord.tasks.find((x) => x.task_id === id);
  if (!t) throw new FakeHttpError(404, errorBody("not_found", "Follow-up task not found."));
  return t;
}

function addEvent(t: TaskDetailOut, type: string, visibility: "patient" | "internal", extra: Partial<TaskEventOut> = {}): void {
  const at = stamp();
  t.events = [...t.events, taskEvent(nextId("E"), type, visibility, at, extra)];
  t.updated_at = at;
}

function careGapDetail(id: string): CareGapDetailOut {
  const g = [...CARE_GAPS, ...PROFILE_ONLY_GAPS].find((x) => x.care_gap_id === id);
  if (!g) throw new FakeHttpError(404, errorBody("not_found", "Care gap not found."));
  return {
    ...g,
    priority_score: 0.72,
    priority_explanation: "Synthetic engine priority.",
    rule: RULES.find((r) => r.rule_id === g.rule_id) ?? RULES[0],
    linked_appointments: coord.appointments.filter((a) => a.care_gap_id === id),
    linked_referrals: [],
    follow_up_events: coord.followUps.filter((f) => f.care_gap_id === id),
    workflow_events: coord.workflow.filter((w) => w.care_gap_id === id),
    recommended_pathway:
      g.status === "open"
        ? {
            status: "documented_next_step",
            next_step: "book_screening",
            description: "Book the screening listed by the rule.",
            rule_id: g.rule_id,
            rule_version: g.rule_version,
            source_reference: "p.1",
            notice: "From the configured rule; not a clinical recommendation.",
          }
        : null,
  };
}

function outreachDraft(body: OutreachDraftIn): OutreachDraftOut {
  // Like a patient without contact consent: the backend refuses before any generation.
  const blocked = body.care_gap_id === "G2";
  return {
    synthetic_patient_id: body.patient_id,
    care_gap_id: body.care_gap_id ?? null,
    rule_id: body.rule_id,
    allowed: !blocked,
    simulated_only: true,
    sendable: false,
    blocked_reason: blocked ? "contact_consent_absent" : null,
    draft_message: blocked ? null : OUTREACH_DRAFT_BODY,
    draft_body: blocked ? null : OUTREACH_DRAFT_BODY,
    disclaimer: "Simulated draft for human review; nothing is sent.",
    ai: blocked
      ? null
      : { generation_mode: "deterministic_fallback", prompt_version: "outreach-v1", provider: null, model: null, fallback_reason: "llm_disabled", audit_id: "AUD-DRAFT-1" },
    channel: body.channel,
    language: body.language,
    tone: body.tone,
    generation_status: blocked ? "blocked" : "fallback",
    is_fallback: !blocked,
    next_step: null,
    review_status: blocked ? "not_applicable" : "pending_review",
  };
}

function outreachReview(body: OutreachReviewIn): OutreachReviewOut {
  const approved = body.decision === "approved";
  const fu = approved
    ? followUpEvent(nextId("FU"), body.patient_id, body.care_gap_id, "outreach_attempted", stamp(), { outcome_status: "simulated_not_sent" })
    : null;
  if (fu) coord.followUps.push(fu);
  return {
    draft_audit_id: body.draft_audit_id,
    review_audit_id: "AUD-REVIEW-1",
    review_status: approved ? "approved" : "rejected",
    blocked_reason: null,
    edited: approved ? body.final_message !== OUTREACH_DRAFT_BODY : null,
    simulated_outreach_status: approved ? "simulated_not_sent" : null,
    follow_up: fu,
    simulated_only: true,
    sendable: false,
    delivered: false,
    disclaimer: "Simulated outreach; nothing was delivered.",
  };
}

function workflowHistory(entity: "appointment" | "referral", id: string): WorkflowHistoryOut {
  return {
    entity_type: entity,
    entity_id: id,
    items: coord.workflow.filter((w) => (entity === "appointment" ? w.appointment_id : w.referral_id) === id),
  };
}

/** Coordination endpoints; `undefined` = not a coordination path. */
function coordinationBackend(path: string, q: URLSearchParams, method: string, body: unknown, page: <T>(items: T[]) => unknown): unknown {
  const s = (k: string) => q.get(k);
  if (path === "/follow-up-tasks/summary") return taskSummary(q);
  if (path === "/follow-up-tasks") {
    if (method === "POST") {
      const b = body as TaskCreateIn;
      if (!PATIENTS.some((p) => p.patient_id === b.patient_id)) throw new FakeHttpError(404, errorBody("not_found", "Patient not found."));
      const gap = CARE_GAPS.find((g) => g.care_gap_id === b.care_gap_id);
      const id = nextId("T");
      const at = stamp();
      const t = followUpTask(id, b.patient_id, {
        care_gap_id: b.care_gap_id ?? null,
        rule_id: gap?.rule_id ?? null,
        assigned_to_user_id: b.assigned_to_user_id ?? null,
        due_date: b.due_date ?? null,
        message_key: b.message_key,
        priority: b.priority,
        patient_visible: b.patient_visible,
        staff_note: b.staff_note ?? null,
        language: b.language ?? "en",
        status: b.patient_visible ? "awaiting_patient" : "open",
        created_at: at,
        updated_at: at,
        events: [taskEvent(`${id}-E`, "created", b.patient_visible ? "patient" : "internal", at, { to_status: "open" })],
      });
      coord.tasks.push(t);
      return t;
    }
    return page(filterTasks(q));
  }
  const ft = /^\/follow-up-tasks\/([^/]+)(?:\/(notes|escalate|contact-attempts|complete))?$/.exec(path);
  if (ft) {
    const t = findTask(ft[1]);
    if (!ft[2] && method === "GET") return t;
    if (!ft[2] && method === "PATCH") {
      const b = body as TaskUpdateIn;
      if (b.status) {
        addEvent(t, "status_changed", "patient", { from_status: t.status, to_status: b.status });
        t.status = b.status;
      }
      if (b.priority) {
        t.priority = b.priority;
        addEvent(t, "priority_changed", "internal", { priority: b.priority });
      }
      if (b.assigned_to_user_id) {
        t.assigned_to_user_id = b.assigned_to_user_id;
        addEvent(t, "assigned", "internal");
      }
      if (b.due_date || b.clear_due_date) {
        t.due_date = b.clear_due_date ? null : b.due_date!;
        t.is_overdue = false;
        addEvent(t, "due_date_changed", "internal");
      }
      return t;
    }
    if (ft[2] === "notes") {
      const b = body as { text: string; patient_visible: boolean };
      addEvent(t, b.patient_visible ? "staff_message" : "staff_note", b.patient_visible ? "patient" : "internal", { message: b.text });
      return t;
    }
    if (ft[2] === "escalate") {
      t.escalated_at = stamp();
      addEvent(t, "escalated", "internal", { message: (body as { reason: string | null }).reason });
      return t;
    }
    if (ft[2] === "contact-attempts") {
      const b = body as { channel: string; outcome: string; note?: string | null };
      addEvent(t, "contact_attempt", "internal", { contact_channel: b.channel, response_code: b.outcome, message: b.note ?? null });
      return t;
    }
    if (ft[2] === "complete") {
      addEvent(t, "completed", "patient", { from_status: t.status, to_status: "completed" });
      t.status = "completed";
      t.completed_at = stamp();
      t.completion_follow_up_id = (body as { completion_follow_up_id: string | null }).completion_follow_up_id;
      return t;
    }
  }
  if (path === "/care-team") return { items: CARE_TEAM };
  const cg = /^\/care-gaps\/([^/]+)(\/follow-ups)?$/.exec(path);
  if (cg) {
    const detail = careGapDetail(cg[1]);
    if (!cg[2]) return detail;
    const b = body as FollowUpCreateIn;
    const fu = followUpEvent(nextId("FU"), detail.patient_id, detail.care_gap_id, b.event_type, stamp(), {
      documented_evidence: b.documented_evidence,
      evidence_reference: b.evidence_reference ?? null,
      note: b.note ?? null,
      outcome_status: b.event_type === "completion_documented" ? "completed" : null,
    });
    coord.followUps.push(fu);
    return fu;
  }
  const act = /^\/patients\/([^/]+)\/activity$/.exec(path);
  if (act) {
    if (!PATIENTS.some((p) => p.patient_id === act[1])) throw new FakeHttpError(404);
    const out: PatientActivityOut = {
      patient_id: act[1],
      follow_up_events: coord.followUps.filter((f) => f.patient_id === act[1]),
      workflow_events: coord.workflow.filter((w) => w.patient_id === act[1]),
    };
    return out;
  }
  if (path === "/patient-requests")
    return page(
      coord.requests.filter(
        (r) => (!s("patient_id") || r.patient_id === s("patient_id")) && (!s("status") || r.status === s("status")) && (!s("request_type") || r.request_type === s("request_type"))
      )
    );
  const pr = /^\/patient-requests\/([^/]+)$/.exec(path);
  if (pr && method === "PATCH") {
    const r = coord.requests.find((x) => x.request_id === pr[1]);
    if (!r) throw new FakeHttpError(404);
    const b = body as RequestUpdateIn;
    if (b.status) r.status = b.status;
    if (b.staff_response) r.staff_response = b.staff_response;
    if (b.internal_note) r.internal_note = b.internal_note;
    if (b.appointment_id) r.appointment_id = b.appointment_id;
    r.handled_by_user_id = SELF_ID;
    return r;
  }
  if (path === "/appointments") {
    if (method === "POST") {
      const b = body as AppointmentCreateIn;
      const a: AppointmentOut = {
        appointment_id: nextId("APT"),
        patient_id: b.patient_id,
        profile_id: b.profile_id,
        care_gap_id: b.care_gap_id ?? null,
        appointment_type: b.appointment_type,
        scheduled_datetime: b.scheduled_datetime,
        slot_type: b.slot_type,
        status: "scheduled",
        booked_via: "staff_portal",
        is_synthetic: true,
      };
      coord.appointments.push(a);
      coord.workflow.push(
        workflowEvent(nextId("WF"), a.patient_id, { appointment_id: a.appointment_id, care_gap_id: a.care_gap_id, scheduled_datetime: a.scheduled_datetime, recorded_at: stamp(), note: b.note ?? null })
      );
      return a;
    }
    const group = s("status_group");
    const rows = coord.appointments
      .filter(
        (a) =>
          (!s("patient_id") || a.patient_id === s("patient_id")) &&
          (!s("care_gap_id") || a.care_gap_id === s("care_gap_id")) &&
          (!s("status") || a.status === s("status")) &&
          (!group || (group === "active" ? a.status === "scheduled" || a.status === "rescheduled" : a.status.startsWith("cancelled"))) &&
          (!s("profile_id") || a.profile_id === s("profile_id")) &&
          (!s("scheduled_from") || a.scheduled_datetime >= s("scheduled_from")!) &&
          (!s("scheduled_to") || a.scheduled_datetime <= s("scheduled_to")!)
      )
      .sort((a, b) => (s("order") === "desc" ? -1 : 1) * a.scheduled_datetime.localeCompare(b.scheduled_datetime));
    return page(rows);
  }
  const ap = /^\/appointments\/([^/]+)(\/history)?$/.exec(path);
  if (ap) {
    const a = coord.appointments.find((x) => x.appointment_id === ap[1]);
    if (!a) throw new FakeHttpError(404);
    if (ap[2]) return workflowHistory("appointment", a.appointment_id);
    if (method === "PATCH") {
      const b = body as AppointmentPatchIn;
      coord.workflow.push(
        workflowEvent(nextId("WF"), a.patient_id, {
          appointment_id: a.appointment_id,
          care_gap_id: a.care_gap_id,
          from_status: a.status,
          to_status: b.status,
          scheduled_datetime: b.scheduled_datetime ?? null,
          recorded_at: stamp(),
          note: b.note ?? null,
        })
      );
      a.status = b.status;
      if (b.scheduled_datetime) a.scheduled_datetime = b.scheduled_datetime;
      return a;
    }
    return a;
  }
  if (path === "/facility-service-profiles") return SERVICE_PROFILES;
  if (path === "/referrals")
    return page(coord.referrals.filter((r) => (!s("patient_id") || r.patient_id === s("patient_id")) && (!s("status") || r.status === s("status"))));
  const rf = /^\/referrals\/([^/]+)(\/history)?$/.exec(path);
  if (rf) {
    const r = coord.referrals.find((x) => x.referral_id === rf[1]);
    if (!r) throw new FakeHttpError(404);
    if (rf[2]) return workflowHistory("referral", r.referral_id);
    if (method === "PATCH") {
      const b = body as ReferralPatchIn;
      // Like the backend: initiation and completion need their dates.
      if ((b.status === "initiated" || b.status === "completed") && !b.initiated_date)
        throw new FakeHttpError(422, errorBody("validation_error", "An initiated date is required."));
      if (b.status === "completed" && !b.completed_date) throw new FakeHttpError(422, errorBody("validation_error", "A completed date is required."));
      coord.workflow.push(
        workflowEvent(nextId("WF"), r.patient_id, {
          entity_type: "referral",
          referral_id: r.referral_id,
          from_status: r.status,
          to_status: b.status,
          initiated_date: b.initiated_date ?? null,
          completed_date: b.completed_date ?? null,
          recorded_at: stamp(),
          note: b.note ?? null,
        })
      );
      r.status = b.status;
      if (b.initiated_date) r.initiated_date = b.initiated_date;
      if (b.completed_date) r.completed_date = b.completed_date;
      return r;
    }
    return r;
  }
  if (path === "/outreach/draft") return outreachDraft(body as OutreachDraftIn);
  if (path === "/outreach/draft/review") return outreachReview(body as OutreachReviewIn);
  return undefined;
}

/** Backend-like handler: applies filters and pagination server-side; unknown IDs → 404. */
export function fakeBackend(url: string, init?: RequestInit): unknown {
  const u = new URL(url);
  const path = decodeURIComponent(u.pathname.replace("/api/v1", ""));
  const limit = Number(u.searchParams.get("limit") ?? 25);
  const offset = Number(u.searchParams.get("offset") ?? 0);
  const page = <T,>(items: T[]) => ({ total: items.length, limit, offset, items: items.slice(offset, offset + limit) });
  const method = (init?.method ?? "GET").toUpperCase();
  const coordination = coordinationBackend(path, u.searchParams, method, init?.body ? JSON.parse(String(init.body)) : {}, page);
  if (coordination !== undefined) return coordination;
  if (path === "/dashboard/summary") return SUMMARY;
  if (path === "/rules") return { total: RULES.length, items: RULES };
  if (path === "/care-gaps") {
    const rule = u.searchParams.get("rule_id");
    return page(CARE_GAPS.filter((g) => !rule || g.rule_id === rule));
  }
  if (path === "/open-questions") return { total: OPEN_QUESTIONS.length, items: OPEN_QUESTIONS };
  const ps = /^\/programmes\/(ifhas|well_child)\/summary$/.exec(path);
  if (ps) return programmeSummary(ps[1] as Pathway, u.searchParams);
  if (path === "/population/summary") return POPULATION_SUMMARY;
  if (path === "/explanations") {
    const body = JSON.parse(String(init?.body ?? "{}")) as { patient_id: string; rule_id: string };
    return {
      synthetic_patient_id: body.patient_id,
      rule_id: body.rule_id,
      rule_version: "1.0.0",
      evaluation_status: "due",
      is_authoritative: true,
      generation_mode: "deterministic_fallback",
      summary_text: `Template summary for ${body.rule_id}`,
      why_text: "Template why",
      missing_or_uncertain_text: "Template missing",
      rule_citation_text: "Template citation",
      warnings: ["SYNTHETIC RECORD"],
    };
  }
  const rd = /^\/rules\/(.+)$/.exec(path);
  if (rd) {
    if (RULE_DETAILS[rd[1]]) return RULE_DETAILS[rd[1]];
    const r = RULES.find((x) => x.rule_id === rd[1]);
    if (!r) throw new FakeHttpError(404);
    return { ...r, notes: null, spec: {}, items: [] };
  }
  const pe = /^\/patients\/([^/]+)(\/evaluations)?$/.exec(path);
  if (pe) {
    const p = PATIENTS.find((x) => x.patient_id === pe[1]);
    if (!p) throw new FakeHttpError(404);
    if (!pe[2]) return p;
    return {
      is_synthetic: true,
      patient_id: p.patient_id,
      evaluation_run_id: SUMMARY.evaluation_run_id,
      reference_date: SUMMARY.reference_date,
      evaluations: EVALUATIONS[p.patient_id] ?? [],
      care_gaps: [...CARE_GAPS, ...PROFILE_ONLY_GAPS].filter((g) => g.patient_id === p.patient_id),
    };
  }
  if (path === "/patients") {
    const q = u.searchParams;
    const pathway = q.get("pathway");
    const region = q.get("region_id");
    const sex = q.get("sex");
    const gaps = q.get("has_open_care_gaps");
    const history = q.get("history_status");
    const band = q.get("age_band");
    const text = q.get("q");
    const openCount = (id: string) => CARE_GAPS.filter((g) => g.patient_id === id && g.status === "open").length;
    // Like the backend: with `pathway`, open-gap and history filters follow that programme.
    const ruleIds = new Set(RULES.filter((r) => !pathway || r.pathway === pathway).map((r) => r.rule_id));
    const scopedOpen = (id: string) => CARE_GAPS.filter((g) => g.patient_id === id && g.status === "open" && ruleIds.has(g.rule_id)).length;
    const years = (dob: string | null) => (dob ? 2026 - Number(dob.slice(0, 4)) - (dob.slice(5) > "11-16" ? 1 : 0) : null);
    const inBand = (dob: string | null) => {
      const y = years(dob);
      if (y === null) return false;
      return band === "child" ? y < 18 : band === "adult_18_39" ? y >= 18 && y < 40 : band === "adult_40_59" ? y >= 40 && y < 60 : y >= 60;
    };
    let rows = PATIENTS.filter(
      (p) =>
        (!pathway || pathway in p.history_by_pathway) &&
        (!region || p.region_id === Number(region)) &&
        (!sex || p.sex === sex) &&
        (gaps === null || scopedOpen(p.patient_id) > 0 === (gaps === "true")) &&
        (!history ||
          (pathway ? p.history_by_pathway[pathway as "ifhas"] === history : Object.values(p.history_by_pathway).includes(history as "available"))) &&
        (!band || inBand(p.date_of_birth)) &&
        (!text || p.patient_id.toLowerCase().includes(text.toLowerCase()))
    );
    if (q.get("sort_by") === "open_gaps") rows = [...rows].sort((a, b) => openCount(b.patient_id) - openCount(a.patient_id));
    return page(rows);
  }
  throw new Error(`unexpected ${url}`);
}

/** Minimum cell size of the fake `/programmes/{pathway}/summary` (1 = no suppression). */
export const fakeSummaryConfig = { minCellSize: 1 };

/** Same definitions as `backend/app/services/programmes.py`, over the fixture records. */
function programmeSummary(pathway: Pathway, q: URLSearchParams): ProgrammeSummaryOut {
  const region = q.get("region_id");
  const sex = q.get("sex");
  const k = fakeSummaryConfig.minCellSize;
  const ruleIds = new Set(RULES.filter((r) => r.pathway === pathway).map((r) => r.rule_id));
  const members = PATIENTS.filter(
    (p) => p.history_by_pathway[pathway] !== undefined && (!region || p.region_id === Number(region)) && (!sex || p.sex === sex)
  );
  const ids = new Set(members.map((p) => p.patient_id));
  const gaps = CARE_GAPS.filter((g) => ruleIds.has(g.rule_id) && ids.has(g.patient_id));
  const openPeople = new Set(gaps.filter((g) => g.status === "open").map((g) => g.patient_id));
  const hide = (n: number) => (n > 0 && n < k ? null : n);
  const history = { available: 0, partial: 0, not_available: 0 };
  const seg = { open_gap: 0, available: 0, partial: 0, not_available: 0 };
  for (const p of members) {
    const h = p.history_by_pathway[pathway]!;
    history[h] += 1;
    seg[openPeople.has(p.patient_id) ? "open_gap" : h] += 1;
  }
  const evals = members.flatMap((p) => (EVALUATIONS[p.patient_id] ?? []).filter((e) => e.pathway === pathway));
  const people = (statuses: string[]) => new Set(evals.filter((e) => statuses.includes(e.evaluation_status)).map((e) => e.patient_id)).size;
  const status = (s: string) => hide(gaps.filter((g) => g.status === s).length);
  const small = members.length > 0 && members.length < k;
  return {
    is_synthetic: true,
    pathway,
    evaluation_run_id: SUMMARY.evaluation_run_id,
    reference_date: SUMMARY.reference_date,
    patient_scope: "organization",
    filters: { region_id: region ? (Number(region) as 1) : null, sex: (sex as "female") ?? null, age_band: null },
    min_cell_size: k,
    members: small ? null : members.length,
    history: { available: hide(history.available), partial: hide(history.partial), not_available: hide(history.not_available) },
    segments: (Object.keys(seg) as (keyof typeof seg)[]).map((s) => ({ segment: s, people: small ? null : hide(seg[s]) })),
    people_with_open_gap: small ? null : hide(seg.open_gap),
    care_gaps: {
      open: status("open"),
      closed_completed: status("closed_completed"),
      closed_refused: status("closed_refused"),
      suppressed: status("suppressed"),
      superseded: status("superseded"),
      total: hide(gaps.length),
    },
    open_gaps_by_type: {},
    eligibility: {
      programme_eligible_patients: hide(people(["eligible"])),
      due_or_upcoming_patients: hide(people(["due", "upcoming", "overdue"])),
      review_flagged_patients: hide(people(["requires_clinical_review"])),
      rule_review_patients: 0,
    },
    trend: {
      period: "90d",
      current_start: "2026-08-19",
      current_end: "2026-11-16",
      previous_start: "2026-05-21",
      previous_end: "2026-08-18",
      evaluation_runs: 1,
      evaluation_history_start: "2026-11-16",
      previous_period_observed: false,
      care_gaps_identified: hide(gaps.length),
      previous_care_gaps_identified: null,
      gaps_closed_completed: status("closed_completed"),
      previous_gaps_closed_completed: null,
      care_gap_trend: { direction: "INSUFFICIENT_DATA", reason_codes: ["evaluation_history_incomplete"], absolute_change: null, percentage_change: null },
    },
    suppressed: small ? ["all"] : [],
    disclaimer: "Aggregates of synthetic records.",
  };
}

/** `fetch` stand-in over `fakeBackend`, translating thrown HTTP errors to responses. */
export async function fakeFetchResponse(url: string, init?: RequestInit): Promise<Response> {
  try {
    return new Response(JSON.stringify(fakeBackend(url, init)), { status: 200 });
  } catch (err) {
    if (err instanceof FakeHttpError) return new Response(JSON.stringify(err.body ?? { detail: "not found" }), { status: err.status });
    throw err;
  }
}
