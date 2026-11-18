import type {
  CareGapOut,
  DashboardSummaryOut,
  EvaluationItemOut,
  PatientSummaryOut,
  RuleDetailOut,
  RuleSummaryOut,
} from "@/lib/api/types";

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
};

export class FakeHttpError extends Error {
  constructor(readonly status: number) {
    super(`HTTP ${status}`);
  }
}

/** Backend-like handler: applies filters and pagination server-side; unknown IDs → 404. */
export function fakeBackend(url: string, init?: RequestInit): unknown {
  const u = new URL(url);
  const path = decodeURIComponent(u.pathname.replace("/api/v1", ""));
  const limit = Number(u.searchParams.get("limit") ?? 25);
  const offset = Number(u.searchParams.get("offset") ?? 0);
  const page = <T,>(items: T[]) => ({ total: items.length, limit, offset, items: items.slice(offset, offset + limit) });
  if (path === "/dashboard/summary") return SUMMARY;
  if (path === "/rules") return { total: RULES.length, items: RULES };
  if (path === "/care-gaps") return page(CARE_GAPS);
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

/** `fetch` stand-in over `fakeBackend`, translating thrown HTTP errors to responses. */
export async function fakeFetchResponse(url: string, init?: RequestInit): Promise<Response> {
  try {
    return new Response(JSON.stringify(fakeBackend(url, init)), { status: 200 });
  } catch (err) {
    if (err instanceof FakeHttpError) return new Response(JSON.stringify({ detail: "not found" }), { status: err.status });
    throw err;
  }
}
