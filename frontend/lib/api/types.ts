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
}

export interface PatientSummaryOut {
  patient_id: string;
  is_synthetic: boolean;
  sex: string | null;
  region_id: number;
  date_of_birth: string | null;
  history_by_pathway: Partial<Record<Pathway, HistoryStatus>>;
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
  notes: string | null;
  spec: Record<string, unknown>;
  items: RuleItemOut[];
}

export interface PaginatedRulesOut {
  total: number;
  items: RuleSummaryOut[];
}

export interface PatientQuery {
  pathway?: Pathway;
  region_id?: RegionId;
  sex?: Sex;
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
