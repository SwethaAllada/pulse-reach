import type {
  CareGapOut,
  DashboardSummaryOut,
  PatientSummaryOut,
  RuleSummaryOut,
} from "@/lib/api/types";

/** Small synthetic fixture mirroring backend response shapes. */
const patient = (
  patient_id: string,
  pathway: "ifhas" | "well_child",
  history: "available" | "partial" | "not_available",
  region_id: number,
  sex: "female" | "male"
): PatientSummaryOut => ({
  patient_id,
  is_synthetic: true,
  sex,
  region_id,
  date_of_birth: null,
  history_by_pathway: { [pathway]: history },
});

export const PATIENTS: PatientSummaryOut[] = [
  patient("SYNTH-PAT-1", "ifhas", "available", 1, "female"),
  patient("SYNTH-PAT-2", "ifhas", "not_available", 2, "male"),
  patient("SYNTH-PAT-3", "ifhas", "partial", 1, "male"),
  patient("SYNTH-PAT-4", "ifhas", "available", 1, "male"),
  patient("SYNTH-PAT-5", "well_child", "available", 3, "female"),
  patient("SYNTH-PAT-6", "well_child", "not_available", 1, "female"),
];

const rule = (rule_id: string, pathway: "ifhas" | "well_child", description: string): RuleSummaryOut => ({
  rule_id,
  rule_version: "1.0.0",
  pathway,
  rule_type: "screening_package",
  description,
  is_authoritative: true,
  requires_clinical_review: false,
  verification_status: "verified",
});

export const RULES: RuleSummaryOut[] = [
  rule("IFHAS-PKG-ORAL", "ifhas", "Oral Health Package: target group 18-75"),
  rule("IFHAS-PKG-FIT", "ifhas", "Standalone FIT screening: target group 40-75"),
  rule("WCV-VISIT-06M", "well_child", "Well-Child visit at 6 months: age, required services"),
];

const gap = (
  care_gap_id: string,
  patient_id: string,
  rule_id: string,
  status: CareGapOut["status"] = "open",
  gap_type: CareGapOut["gap_type"] = "no_documented_screening"
): CareGapOut => ({
  care_gap_id,
  patient_id,
  rule_id,
  gap_type,
  status,
  identified_date: "2026-11-16",
  is_synthetic: true,
});

export const CARE_GAPS: CareGapOut[] = [
  gap("G1", "SYNTH-PAT-1", "IFHAS-PKG-ORAL"),
  gap("G2", "SYNTH-PAT-1", "IFHAS-PKG-FIT", "open", "partial_completion"),
  gap("G3", "SYNTH-PAT-5", "WCV-VISIT-06M"),
  gap("G4", "SYNTH-PAT-4", "IFHAS-PKG-ORAL", "closed_refused"),
];

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
};

/** Backend-like handler: applies `/patients` filters and pagination server-side. */
export function fakeBackend(url: string): unknown {
  const u = new URL(url);
  const path = u.pathname.replace("/api/v1", "");
  const limit = Number(u.searchParams.get("limit") ?? 25);
  const offset = Number(u.searchParams.get("offset") ?? 0);
  const page = <T,>(items: T[]) => ({ total: items.length, limit, offset, items: items.slice(offset, offset + limit) });
  if (path === "/dashboard/summary") return SUMMARY;
  if (path === "/rules") return { total: RULES.length, items: RULES };
  if (path === "/care-gaps") return page(CARE_GAPS);
  if (path === "/patients") {
    const pathway = u.searchParams.get("pathway");
    const region = u.searchParams.get("region_id");
    const sex = u.searchParams.get("sex");
    return page(
      PATIENTS.filter(
        (p) =>
          (!pathway || pathway in p.history_by_pathway) &&
          (!region || p.region_id === Number(region)) &&
          (!sex || p.sex === sex)
      )
    );
  }
  throw new Error(`unexpected ${url}`);
}
