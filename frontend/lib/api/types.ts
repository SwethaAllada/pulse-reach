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
  /** Any open care gap, in any programme (backend semantics). */
  has_open_care_gaps?: boolean;
  /** Matches a history record with this status in any programme. */
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
