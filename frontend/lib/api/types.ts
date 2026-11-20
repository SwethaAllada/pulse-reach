/**
 * Response types mirroring `backend/app/schemas/v1.py`. Only the fields the
 * frontend reads are declared; names and types match the Pydantic models.
 */

export type Pathway = "ifhas" | "well_child";
export type Sex = "female" | "male";
export type RegionId = 1 | 2 | 3;
export type HistoryStatus = "available" | "partial" | "not_available";

export type CareGapStatus =
  | "open"
  | "closed_completed"
  | "closed_refused"
  | "suppressed"
  | "superseded";

export type CareGapType =
  | "no_documented_screening"
  | "interval_elapsed"
  | "partial_completion"
  | "referral_not_initiated"
  | "visit_not_attended";

export interface RulesSummaryOut {
  total_rules: number;
  authoritative_rules: number;
  review_flagged_rules: number;
  unresolved_rules: number;
  total_rule_items: number;
  clinical_review_status: string;
}

export interface DashboardSummaryOut {
  is_synthetic: boolean;
  run_id: string;
  evaluation_run_id: string;
  reference_date: string;
  total_patients: number;
  n_adults: number;
  n_children: number;
  open_care_gaps_count: number;
  closed_refused_care_gaps_count: number;
  evaluation_status_counts: Record<string, number>;
  rules_summary: RulesSummaryOut;
  governance_disclaimer: string;
  /* Fields below are absent from older backends; readers treat them as optional. */
  unknown_history_patients_count?: number;
  review_flagged_patients_count?: number;
  rule_review_patients_count?: number;
  patient_status_counts?: Record<string, number>;
  pathway_breakdown?: Partial<Record<Pathway, PathwayBreakdownOut>>;
  gaps_by_type?: Record<string, number>;
  gaps_by_pathway?: Partial<Record<Pathway, number>>;
}

export interface PatientSummaryOut {
  patient_id: string;
  is_synthetic: boolean;
  sex: string | null;
  region_id: number;
  date_of_birth: string | null;
  history_by_pathway: Partial<Record<Pathway, HistoryStatus>>;
  open_care_gaps_count?: number;
  /** Recorded contact preferences (outreach drafts must use `preferred_channel`). */
  preferred_language?: string;
  preferred_channel?: string;
  date_of_death?: string | null;
}

export interface Paginated<T> {
  total: number;
  limit: number;
  offset: number;
  items: T[];
}

export interface CareGapOut {
  care_gap_id: string;
  patient_id: string;
  evaluation_id: string;
  rule_id: string;
  rule_version: string;
  gap_type: CareGapType;
  status: CareGapStatus;
  identified_date: string;
  closed_date: string | null;
  closed_by_consent_id: string | null;
  closed_by_component_result_id: string | null;
  subject_ifhas_screening_id: string | null;
  subject_well_child_visit_id: string | null;
  subject_referral_id: string | null;
  is_synthetic: boolean;
}

export interface RuleSummaryOut {
  rule_id: string;
  rule_version: string;
  pathway: Pathway;
  rule_type: string | null;
  source_name: string;
  source_version: string;
  source_reference: string;
  description: string;
  is_authoritative: boolean;
  requires_clinical_review: boolean;
  verification_status: string;
  effective_date_text: string | null;
  open_question_ids: string[];
}

export interface RuleItemOut {
  category: string;
  code: string;
  ordinal: number;
  description: string;
  source_reference: string;
  verification_status: string;
  effective_authority: boolean;
}

export interface RuleDetailOut extends RuleSummaryOut {
  effective_date_note?: string | null;
  notes: string | null;
  spec: Record<string, unknown>;
  items: RuleItemOut[];
}

export interface PaginatedRulesOut {
  total: number;
  items: RuleSummaryOut[];
}

export type AgeBand = "child" | "adult_18_39" | "adult_40_59" | "adult_60_plus";

export interface PatientQuery {
  pathway?: Pathway;
  region_id?: RegionId;
  sex?: Sex;
  /** An open care gap — under `pathway`'s rules when `pathway` is set, otherwise in any programme. */
  has_open_care_gaps?: boolean;
  /** History status for `pathway` when set, otherwise a record with this status in any programme. */
  history_status?: HistoryStatus;
  /** Backend-computed from date of birth at the evaluation reference date. */
  age_band?: AgeBand;
  /** Substring of synthetic patient ID (also names, which PulseReach never displays). */
  q?: string;
  sort_by?: "patient_id" | "age" | "open_gaps";
  sort_dir?: "asc" | "desc";
}

export interface CareGapQuery {
  status?: CareGapStatus;
  gap_type?: CareGapType;
  rule_id?: string;
  patient_id?: string;
}

/** `PathwayBreakdownOut` — people (not evaluations) per pathway, in-band results only. */
export interface PathwayBreakdownOut {
  patients_with_history: number;
  programme_eligible_patients: number;
  due_or_upcoming_patients: number;
  unknown_history_patients: number;
  review_flagged_patients: number;
  rule_review_patients: number;
  open_care_gaps_count: number;
}

export interface OpenQuestionOut {
  oq_id: string;
  category: string;
  status: string;
  title: string;
  detail: string;
  affects: string[];
  resolve_via: string | null;
  resolution: string | null;
  resolved_on: string | null;
  rule_ids: string[];
}

export interface PaginatedOpenQuestionsOut {
  total: number;
  items: OpenQuestionOut[];
}

/* ── Identity (`AUTH_MODE=users`, `backend/app/schemas/identity.py`) ── */

export interface UserOut {
  user_id: string;
  email: string;
  full_name: string;
  preferred_language: string;
}

export interface TokenOut {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  refresh_expires_in: number;
  user: UserOut;
  organization_id: string | null;
  role: string | null;
  permissions: string[];
}

export interface MembershipOut {
  organization_id: string;
  organization_name: string;
  role: string;
  patient_access: "organization" | "assigned" | string;
  is_active: boolean;
}

export interface MeOut {
  user: UserOut;
  organization_id: string | null;
  role: string | null;
  permissions: string[];
  patient_linked: boolean;
  memberships: MembershipOut[];
  locale: string;
  direction: string;
}

/* ── Population surveillance (`GET /population/summary`, BE-33) ── */

export interface TrendOut {
  direction: "INCREASING" | "DECREASING" | "STABLE" | "INSUFFICIENT_DATA" | string;
  reason_codes: string[];
  absolute_change: number | null;
  percentage_change: number | null;
}

export interface PreventiveCareOut {
  in_scope_patients: number | null;
  patients_with_open_gap: number | null;
  in_scope_patients_with_open_gap: number | null;
  open_care_gaps: number | null;
  preventive_coverage: number | null;
  preventive_coverage_definition: string;
  care_gap_history_start: string | null;
  period: string;
  period_metrics: {
    period_days: number;
    current_start: string;
    current_end: string;
    previous_start: string;
    previous_end: string;
    screening_completions: number | null;
    previous_screening_completions: number | null;
    care_gaps_identified: number | null;
    previous_care_gaps_identified: number | null;
    care_gap_trend: TrendOut;
    follow_up_completion_rate: number | null;
    suppressed: string[];
  } | null;
  suppressed: string[];
}

export interface PopulationSummaryOut {
  is_synthetic: boolean;
  as_of: string;
  complete_through: string | null;
  disclaimer: string;
  total_population: number | null;
  preventive_care: PreventiveCareOut;
  latest_aggregation_at: string | null;
}

export interface EvaluationReasonOut {
  reason_ordinal: number;
  reason_code: string;
  guard_id: string | null;
  item_category: string | null;
  item_code: string | null;
}

export interface EvaluationItemOut {
  evaluation_id: string;
  patient_id: string;
  rule_id: string;
  rule_version: string;
  pathway: Pathway;
  rule_type: string | null;
  evaluation_status: string;
  reason_code: string | null;
  next_due_date: string | null;
  evaluated_at: string;
  reasons: EvaluationReasonOut[];
}

export interface PatientEvaluationsOut {
  is_synthetic: boolean;
  patient_id: string;
  evaluation_run_id: string;
  reference_date: string;
  evaluations: EvaluationItemOut[];
  care_gaps: CareGapOut[];
}

/** `POST /explanations` — deterministic template unless an LLM provider is configured server-side. */
export interface ExplanationOut {
  synthetic_patient_id: string;
  rule_id: string;
  rule_version: string;
  evaluation_status: string;
  is_authoritative: boolean;
  generation_mode: string;
  summary_text: string;
  why_text: string;
  missing_or_uncertain_text: string;
  rule_citation_text: string;
  warnings: string[];
}

/**
 * `GET /programmes/{pathway}/summary` — server-side programme aggregates for the caller's patient
 * scope and filters. Any count is `null` when suppressed for privacy (listed in `suppressed`;
 * `"all"` when the member set is below `min_cell_size`).
 */
export interface ProgrammeSummaryOut {
  is_synthetic: boolean;
  pathway: Pathway;
  evaluation_run_id: string;
  reference_date: string;
  patient_scope: "organization" | "assigned" | "unrestricted";
  filters: { region_id: RegionId | null; sex: Sex | null; age_band: AgeBand | null };
  min_cell_size: number;
  members: number | null;
  history: Record<HistoryStatus, number | null>;
  segments: { segment: "open_gap" | HistoryStatus; people: number | null }[];
  people_with_open_gap: number | null;
  care_gaps: Record<CareGapStatus, number | null> & { total: number | null };
  open_gaps_by_type: Partial<Record<CareGapType, number | null>>;
  eligibility: {
    programme_eligible_patients: number | null;
    due_or_upcoming_patients: number | null;
    review_flagged_patients: number | null;
    rule_review_patients: number | null;
  };
  trend: {
    period: string;
    current_start: string;
    current_end: string;
    previous_start: string;
    previous_end: string;
    evaluation_runs: number;
    evaluation_history_start: string | null;
    /** False when no persisted evaluation run covers the previous window (previous counts are then null). */
    previous_period_observed: boolean;
    care_gaps_identified: number | null;
    previous_care_gaps_identified: number | null;
    gaps_closed_completed: number | null;
    previous_gaps_closed_completed: number | null;
    care_gap_trend: { direction: string; reason_codes: string[]; absolute_change: number | null; percentage_change: number | null };
  };
  suppressed: string[];
  disclaimer: string;
}

export interface ProgrammeSummaryQuery {
  region_id?: RegionId;
  sex?: Sex;
  age_band?: AgeBand;
}

/* ── Coordination: follow-up tasks, patient requests, appointments, referrals, outreach ──
 * `backend/app/schemas/portal.py` (engagement) and `backend/app/schemas/v1.py` (workflow). */

export type TaskStatus = "open" | "awaiting_patient" | "patient_responded" | "in_progress" | "completed" | "cancelled";
export type TaskPriority = "routine" | "high" | "urgent";
export type MessageKey =
  | "screening_invitation"
  | "complete_outstanding"
  | "referral_follow_up"
  | "well_child_visit"
  | "general_check_in";
export type ContactChannel = "phone" | "sms" | "email" | "in_person" | "portal";
export type ContactOutcome = "reached" | "no_answer" | "left_message" | "wrong_contact_details" | "declined";

export interface TaskEventOut {
  event_id: string;
  event_type: string;
  visibility: "patient" | "internal";
  actor_user_id: string;
  actor_role: string;
  from_status: string | null;
  to_status: string | null;
  response_code: string | null;
  message: string | null;
  priority: string | null;
  contact_channel: string | null;
  created_at: string;
}

export interface TaskOut {
  task_id: string;
  organization_id: string;
  patient_id: string;
  care_gap_id: string | null;
  rule_id: string | null;
  assigned_to_user_id: string | null;
  created_by_user_id: string;
  status: TaskStatus;
  priority: TaskPriority;
  due_date: string | null;
  is_overdue: boolean;
  is_due_soon: boolean;
  escalated_at: string | null;
  language: "en" | "ar";
  message_key: MessageKey | string;
  /** The approved, localized template text the patient sees in the portal. */
  patient_message: string;
  patient_visible: boolean;
  /** Internal; never shown to the patient. */
  staff_note: string | null;
  patient_reported_completion: boolean;
  completion_follow_up_id: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface TaskDetailOut extends TaskOut {
  events: TaskEventOut[];
}

export interface TaskQuery {
  patient_id?: string;
  status?: TaskStatus;
  active?: boolean;
  assigned_to?: string;
  overdue?: boolean;
  priority?: TaskPriority;
  pathway?: Pathway;
  region_id?: RegionId;
  due_after?: string;
  due_before?: string;
}

export interface TaskCreateIn {
  patient_id: string;
  care_gap_id?: string | null;
  assigned_to_user_id?: string | null;
  due_date?: string | null;
  message_key: MessageKey;
  priority: TaskPriority;
  patient_visible: boolean;
  staff_note?: string | null;
  language?: "en" | "ar" | null;
}

export interface TaskUpdateIn {
  status?: "awaiting_patient" | "in_progress" | "cancelled";
  assigned_to_user_id?: string;
  due_date?: string;
  clear_due_date?: boolean;
  priority?: TaskPriority;
}

export interface TaskWorkloadOut {
  assigned_to_user_id: string | null;
  active: number;
  overdue: number;
  due_soon: number;
  urgent: number;
}

export interface TaskActivityOut {
  event_id: string;
  task_id: string;
  patient_id: string;
  event_type: string;
  visibility: "patient" | "internal";
  actor_user_id: string;
  actor_role: string;
  to_status: string | null;
  response_code: string | null;
  priority: string | null;
  contact_channel: string | null;
  created_at: string;
}

export interface TaskSummaryOut {
  as_of: string;
  due_soon_days: number;
  total: number;
  active: number;
  overdue: number;
  due_soon: number;
  completed: number;
  cancelled: number;
  unassigned_active: number;
  patient_reported_completion: number;
  by_status: Record<TaskStatus, number>;
  active_by_priority: Record<TaskPriority, number>;
  workload: TaskWorkloadOut[];
  recent_events: TaskActivityOut[];
}

export interface CareTeamMemberOut {
  user_id: string;
  full_name: string;
  role: string;
  patient_access: "organization" | "assigned";
  is_self: boolean;
  can_be_assigned: boolean | null;
}

export type RequestStatus = "submitted" | "acknowledged" | "scheduled" | "declined" | "closed" | "cancelled";
export type RequestType = "appointment" | "assistance" | "appointment_change";

export interface StaffPatientRequestOut {
  request_id: string;
  organization_id: string;
  patient_id: string;
  submitted_by_user_id: string;
  request_type: RequestType;
  status: RequestStatus;
  task_id: string | null;
  care_gap_id: string | null;
  appointment_id: string | null;
  change_action: "cancel" | "reschedule" | null;
  preferred_dates: string[];
  preferred_time_of_day: "morning" | "afternoon" | "evening" | null;
  message: string | null;
  language: "en" | "ar";
  /** Visible to the patient. */
  staff_response: string | null;
  /** Staff only. */
  internal_note: string | null;
  handled_by_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface RequestQuery {
  patient_id?: string;
  status?: RequestStatus;
  request_type?: RequestType;
}

export interface RequestUpdateIn {
  status?: "acknowledged" | "scheduled" | "declined" | "closed";
  staff_response?: string;
  internal_note?: string;
  appointment_id?: string;
}

export type AppointmentStatus =
  | "scheduled"
  | "attended"
  | "no_show"
  | "cancelled_by_patient"
  | "cancelled_by_facility"
  | "rescheduled";
export type AppointmentType = "ifhas_screening" | "well_child_visit" | "referral_visit" | "other";

export interface AppointmentOut {
  appointment_id: string;
  patient_id: string;
  profile_id: string;
  care_gap_id: string | null;
  appointment_type: AppointmentType | string;
  scheduled_datetime: string;
  slot_type: string;
  status: AppointmentStatus;
  booked_via: string;
  is_synthetic: boolean;
}

export interface AppointmentQuery {
  patient_id?: string;
  care_gap_id?: string;
  status?: AppointmentStatus;
  status_group?: "active" | "cancelled";
  profile_id?: string;
  scheduled_from?: string;
  scheduled_to?: string;
  order?: "asc" | "desc";
}

export interface AppointmentCreateIn {
  patient_id: string;
  profile_id: string;
  care_gap_id?: string | null;
  appointment_type: AppointmentType;
  scheduled_datetime: string;
  slot_type: "weekday" | "evening" | "weekend";
  note?: string | null;
}

export interface AppointmentPatchIn {
  status: AppointmentStatus;
  scheduled_datetime?: string;
  note?: string | null;
}

export interface ServiceProfileOut {
  profile_id: string;
  facility_id: number;
  facility_name: string | null;
  offers_ifhas: boolean;
  offers_wcv: boolean;
  evening_hours: boolean;
  weekend_hours: boolean;
  capability_basis: string;
}

export interface ServiceProfilesOut {
  notice: string;
  items: ServiceProfileOut[];
}

export type ReferralStatus = "pending" | "initiated" | "completed" | "declined" | "cancelled";

export interface ReferralOut {
  referral_id: string;
  patient_id: string;
  trigger_rule_id: string;
  trigger_rule_version: string;
  referral_target: string;
  target_profile_id: string | null;
  trigger_date: string;
  initiated_date: string | null;
  completed_date: string | null;
  status: ReferralStatus;
}

export interface ReferralPatchIn {
  status: ReferralStatus;
  initiated_date?: string;
  completed_date?: string;
  note?: string | null;
}

export interface WorkflowStatusEventOut {
  status_event_id: string;
  patient_id: string;
  entity_type: "appointment" | "referral";
  appointment_id: string | null;
  referral_id: string | null;
  care_gap_id: string | null;
  from_status: string | null;
  to_status: string;
  scheduled_datetime: string | null;
  initiated_date: string | null;
  completed_date: string | null;
  recorded_by: string;
  recorded_at: string;
  note: string | null;
}

export interface WorkflowHistoryOut {
  entity_type: "appointment" | "referral";
  entity_id: string;
  items: WorkflowStatusEventOut[];
}

export interface FollowUpEventOut {
  follow_up_id: string;
  patient_id: string;
  care_gap_id: string;
  event_type: string;
  outcome_status: string | null;
  documented_evidence: boolean;
  evidence_reference: string | null;
  contact_consent_id: string | null;
  suppression_reason: string | null;
  recorded_by: string;
  recorded_at: string;
  note: string | null;
  appointment_id: string | null;
  referral_id: string | null;
}

export interface PatientActivityOut {
  patient_id: string;
  follow_up_events: FollowUpEventOut[];
  workflow_events: WorkflowStatusEventOut[];
}

export interface FollowUpCreateIn {
  event_type: "outreach_attempted" | "completion_documented" | "note_recorded";
  close_gap: boolean;
  documented_evidence: boolean;
  evidence_reference?: string | null;
  note?: string | null;
}

export interface RecommendedPathwayOut {
  status: "documented_next_step" | "requires_clinical_review" | "no_documented_pathway";
  next_step: string | null;
  description: string;
  rule_id: string;
  rule_version: string;
  source_reference: string | null;
  notice: string;
}

export interface CareGapDetailOut extends CareGapOut {
  priority_score?: number | null;
  priority_explanation?: string | null;
  rule: RuleSummaryOut;
  linked_appointments: AppointmentOut[];
  linked_referrals: ReferralOut[];
  follow_up_events: FollowUpEventOut[];
  workflow_events: WorkflowStatusEventOut[];
  recommended_pathway: RecommendedPathwayOut | null;
}

export interface OutreachDraftIn {
  patient_id: string;
  rule_id: string;
  care_gap_id?: string | null;
  channel: "sms" | "phone" | "email" | "app";
  language: "en" | "ar";
  tone: "supportive" | "neutral";
}

export interface OutreachDraftOut {
  synthetic_patient_id: string;
  care_gap_id: string | null;
  rule_id: string;
  allowed: boolean;
  simulated_only: boolean;
  sendable: boolean;
  blocked_reason: string | null;
  draft_message: string | null;
  draft_body: string | null;
  disclaimer: string;
  ai: { generation_mode: string; prompt_version: string; provider: string | null; model: string | null; fallback_reason: string | null; audit_id: string | null } | null;
  channel: string | null;
  language: string | null;
  tone: string | null;
  generation_status: "generated" | "fallback" | "blocked";
  is_fallback: boolean;
  next_step: RecommendedPathwayOut | null;
  review_status: "pending_review" | "not_applicable";
}

export interface OutreachReviewIn {
  draft_audit_id: string;
  patient_id: string;
  rule_id: string;
  care_gap_id: string;
  channel: string;
  language: string;
  decision: "approved" | "rejected";
  final_message?: string;
  reason?: string;
}

export interface OutreachReviewOut {
  draft_audit_id: string;
  review_audit_id: string;
  review_status: "approved" | "rejected" | "blocked";
  blocked_reason: string | null;
  edited: boolean | null;
  simulated_outreach_status: string | null;
  follow_up: FollowUpEventOut | null;
  simulated_only: boolean;
  sendable: boolean;
  delivered: boolean;
  disclaimer: string;
}
