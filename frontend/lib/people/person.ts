import type {
  CareGapOut,
  CareGapType,
  EvaluationItemOut,
  HistoryStatus,
  Pathway,
  PatientSummaryOut,
  RuleDetailOut,
  RuleSummaryOut,
} from "@/lib/api/types";
import type { EvaluationStatus } from "@/components/ui/status-glyph";
import { PATHWAY_OPTIONS } from "@/lib/population/filters";

/* ── Demographics ───────────────────────────────────────────────────────── */

function ymd(iso: string): [number, number, number] | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}

/** Whole months between date of birth and the evaluation reference date (null when either is missing). */
export function ageInMonths(dob: string | null, referenceDate: string | null): number | null {
  if (!dob || !referenceDate) return null;
  const a = ymd(dob);
  const b = ymd(referenceDate);
  if (!a || !b) return null;
  const months = (b[0] - a[0]) * 12 + (b[1] - a[1]) - (b[2] < a[2] ? 1 : 0);
  return months >= 0 ? months : null;
}

/** "14 months" under two years, otherwise whole years. Missing input is reported, never guessed. */
export function ageLabel(dob: string | null, referenceDate: string | null): string {
  if (!dob) return "Date of birth not recorded";
  const months = ageInMonths(dob, referenceDate);
  if (months === null) return "Not available";
  if (months < 24) return `${months} ${months === 1 ? "month" : "months"}`;
  return `${Math.floor(months / 12)} years`;
}

export function sexLabel(sex: string | null): string {
  if (sex === "female") return "Female";
  if (sex === "male") return "Male";
  return "Not recorded";
}

/** Programme membership = pathways with a history-availability record. */
export function programmesOf(patient: Pick<PatientSummaryOut, "history_by_pathway">): Pathway[] {
  return PATHWAY_OPTIONS.map((o) => o.value).filter((p) => patient.history_by_pathway[p] !== undefined);
}

export const HISTORY_META: Record<HistoryStatus, { label: string; description: string }> = {
  available: {
    label: "History available",
    description:
      "A screening or visit history is available to the engine. This does not mean every recommended service was completed.",
  },
  partial: {
    label: "History partially available",
    description:
      "Only part of the history is available. Affected evaluations are routed to clinical review instead of producing a result.",
  },
  not_available: {
    label: "History unavailable",
    description:
      "No screening or visit history is available. Completion cannot be determined — this is not evidence that screening did not happen.",
  },
};

export function historyMeta(status: string | undefined): { label: string; description: string } {
  if (status && status in HISTORY_META) return HISTORY_META[status as HistoryStatus];
  return { label: "Not recorded", description: "No history-availability record for this programme." };
}

/* ── Care gaps ──────────────────────────────────────────────────────────── */

export function openGapCountByPatient(gaps: CareGapOut[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const g of gaps) if (gapStatusMeta(g.status).isOpen) counts.set(g.patient_id, (counts.get(g.patient_id) ?? 0) + 1);
  return counts;
}

export interface GapStatusMeta {
  label: string;
  description: string;
  /** Glyph shape reused from the evaluation status set. */
  glyph: EvaluationStatus;
  isOpen: boolean;
  isCompleted: boolean;
}

/**
 * Care-gap status vocabulary. Only `closed_completed` is a completion —
 * refusals, scheduling, cancellation and supersession never count as done,
 * and anything unrecognised stays "unknown".
 */
export function gapStatusMeta(status: string): GapStatusMeta {
  switch (status) {
    case "open":
      return { label: "Open", description: "Documented care gap, not yet closed.", glyph: "due", isOpen: true, isCompleted: false };
    case "closed_completed":
      return {
        label: "Closed — completed",
        description: "Closed because a qualifying screening or visit was documented.",
        glyph: "completed",
        isOpen: false,
        isCompleted: true,
      };
    case "closed_refused":
      return {
        label: "Closed — documented refusal",
        description: "Closed by a documented refusal. The service was not completed.",
        glyph: "not_eligible",
        isOpen: false,
        isCompleted: false,
      };
    case "suppressed":
      return {
        label: "Suppressed",
        description: "Not actioned (suppressed). The service is not documented as completed.",
        glyph: "not_eligible",
        isOpen: false,
        isCompleted: false,
      };
    case "superseded":
      return {
        label: "Superseded",
        description: "Replaced by a later evaluation. The service is not documented as completed.",
        glyph: "not_eligible",
        isOpen: false,
        isCompleted: false,
      };
    case "scheduled":
      return {
        label: "Scheduled — not completed",
        description: "An appointment or referral is scheduled. Nothing is documented as completed yet.",
        glyph: "upcoming",
        isOpen: true,
        isCompleted: false,
      };
    case "cancelled":
      return {
        label: "Cancelled — not completed",
        description: "The scheduled appointment or referral was cancelled. The service was not completed.",
        glyph: "unknown",
        isOpen: true,
        isCompleted: false,
      };
    default:
      return {
        label: `Unknown status (${status})`,
        description: "The API returned a status PulseReach does not recognise; it is not interpreted.",
        glyph: "unknown",
        isOpen: false,
        isCompleted: false,
      };
  }
}

/** Gap-type meanings, as produced by `app/services/evaluation/engine.py`. */
export const GAP_TYPE_META: Record<CareGapType, { label: string; description: string }> = {
  no_documented_screening: {
    label: "No documented screening",
    description: "The person is in scope for this rule and no qualifying screening or visit record is documented.",
  },
  interval_elapsed: {
    label: "Interval elapsed",
    description: "The last documented completion is older than the interval configured for this rule.",
  },
  partial_completion: {
    label: "Partial completion",
    description:
      "A screening or visit is documented as only partially completed, or a workflow milestone was not documented within its configured window.",
  },
  referral_not_initiated: {
    label: "Referral not initiated",
    description: "A referral triggered under this rule is recorded as pending beyond its configured window.",
  },
  visit_not_attended: {
    label: "Visit not attended",
    description: "A visit for this schedule point is recorded as not attended.",
  },
};

export function gapTypeMeta(type: string): { label: string; description: string } {
  return (
    GAP_TYPE_META[type as CareGapType] ?? {
      label: type,
      description: "Gap type not recognised by PulseReach; shown as returned by the API.",
    }
  );
}

/** Historical records a gap points at — documented evidence, distinct from the evaluation result. */
export function gapEvidenceRefs(gap: CareGapOut): { label: string; id: string }[] {
  const refs: { label: string; id: string }[] = [];
  if (gap.subject_ifhas_screening_id) refs.push({ label: "IFHAS screening record", id: gap.subject_ifhas_screening_id });
  if (gap.subject_well_child_visit_id) refs.push({ label: "Well-Child visit record", id: gap.subject_well_child_visit_id });
  if (gap.subject_referral_id) refs.push({ label: "Referral record", id: gap.subject_referral_id });
  if (gap.closed_by_consent_id) refs.push({ label: "Closing consent / refusal record", id: gap.closed_by_consent_id });
  if (gap.closed_by_component_result_id) refs.push({ label: "Closing component result", id: gap.closed_by_component_result_id });
  return refs;
}

/* ── Evaluation vocabulary (data-pipeline/rules/common/status_definitions.yaml v1.0.0) ── */

const EVALUATION_STATUSES: EvaluationStatus[] = [
  "due",
  "upcoming",
  "eligible",
  "completed",
  "not_eligible",
  "unknown",
  "insufficient_information",
  "requires_clinical_review",
];

export function asEvaluationStatus(status: string): EvaluationStatus | null {
  return (EVALUATION_STATUSES as string[]).includes(status) ? (status as EvaluationStatus) : null;
}

export const EVALUATION_STATUS_DEFINITIONS: Record<EvaluationStatus, string> = {
  eligible: "All attributes required by the rule are present and satisfy its eligibility criteria.",
  not_eligible: "All attributes required by the rule are present and positively fail its eligibility criteria.",
  due: "Eligible, and the rule's interval or schedule point has been reached with no qualifying completed screening documented.",
  upcoming: "Eligible (or becoming eligible) and not yet due, within the product look-ahead period (not a clinical threshold).",
  completed: "A qualifying screening or visit is documented as completed within the rule's interval.",
  unknown: "The person may be eligible but their history is not available, so completion cannot be determined.",
  insufficient_information: "A required attribute (for example date of birth or sex) is missing, so no eligibility result can be produced.",
  requires_clinical_review:
    "The evaluation touches an unresolved or review-flagged rule, or conflicting records. No automated recommendation is produced.",
};

export const GUARD_META: Record<string, { when: string; scope: "person" | "rule" }> = {
  "GUARD-MISSING-DOB": { when: "Date of birth is missing.", scope: "person" },
  "GUARD-MISSING-ATTRIBUTE": { when: "A required eligibility attribute (for example sex) is missing.", scope: "person" },
  "GUARD-MISSING-HISTORY": { when: "Eligibility is established but screening history is missing.", scope: "person" },
  "GUARD-CONFLICTING-RECORDS": { when: "Two or more records disagree on a fact the rule depends on.", scope: "person" },
  "GUARD-RULE-NOT-VERIFIED": { when: "The governing rule has verification_status other than `verified`.", scope: "rule" },
  "GUARD-RULE-REVIEW-FLAG": { when: "The governing rule has requires_clinical_review = true.", scope: "rule" },
  "GUARD-ITEM-UNRESOLVED": {
    when: "The governing assessment item has verification_status other than `verified`.",
    scope: "rule",
  },
};

export const REASON_CODE_LABELS: Record<string, string> = {
  missing_date_of_birth: "Date of birth missing",
  missing_sex: "Sex missing",
  missing_required_attribute: "Required attribute missing",
  missing_screening_history: "Screening history missing",
  conflicting_records: "Conflicting or partial records",
  rule_unresolved: "Rule not verified / unresolved",
  rule_reported_not_verified: "Rule reported, not verified",
  rule_requires_clinical_review: "Rule flagged for clinical review",
  rule_item_unresolved: "Rule item unresolved",
};

export function reasonCodeLabel(code: string): string {
  return REASON_CODE_LABELS[code] ?? code;
}

/* ── Assessment grouping ────────────────────────────────────────────────── */

export type RuleGroup = "programme" | "service" | "workflow";

const RULE_GROUPS: Record<string, RuleGroup> = {
  programme_eligibility: "programme",
  programme_scope: "programme",
  programme_status: "programme",
  screening_package: "service",
  visit_schedule: "service",
  developmental_screening_tier: "service",
  workflow_timing: "workflow",
  follow_up_window: "workflow",
  visit_timing: "workflow",
  policy: "workflow",
};

export function ruleGroup(ruleType: string | null): RuleGroup {
  return (ruleType && RULE_GROUPS[ruleType]) || "workflow";
}

export interface ProgrammeAssessment {
  pathway: Pathway;
  isMember: boolean;
  history: string | undefined;
  /** Programme-level gates (eligibility, scope, in-force status). */
  gates: EvaluationItemOut[];
  /** Preventive services (packages, visits, developmental tiers) by status. */
  serviceCounts: Partial<Record<EvaluationStatus | "other", number>>;
  servicesInScope: number;
  openGaps: number;
  closedGaps: number;
}

export function buildAssessment(
  patient: Pick<PatientSummaryOut, "history_by_pathway">,
  evaluations: EvaluationItemOut[],
  gaps: CareGapOut[]
): ProgrammeAssessment[] {
  const members = programmesOf(patient);
  const pathways = members.length > 0 ? members : PATHWAY_OPTIONS.map((o) => o.value);
  return pathways.map((pathway) => {
    const evs = evaluations.filter((e) => e.pathway === pathway);
    const evIds = new Set(evs.map((e) => e.evaluation_id));
    const services = evs.filter((e) => ruleGroup(e.rule_type) === "service");
    const serviceCounts: ProgrammeAssessment["serviceCounts"] = {};
    for (const e of services) {
      const k = asEvaluationStatus(e.evaluation_status) ?? "other";
      serviceCounts[k] = (serviceCounts[k] ?? 0) + 1;
    }
    const pathwayGaps = gaps.filter((g) => evIds.has(g.evaluation_id));
    return {
      pathway,
      isMember: members.includes(pathway),
      history: patient.history_by_pathway[pathway],
      gates: evs.filter((e) => ruleGroup(e.rule_type) === "programme"),
      serviceCounts,
      servicesInScope: services.filter((e) => e.evaluation_status !== "not_eligible").length,
      openGaps: pathwayGaps.filter((g) => gapStatusMeta(g.status).isOpen).length,
      closedGaps: pathwayGaps.filter((g) => !gapStatusMeta(g.status).isOpen).length,
    };
  });
}

/* ── Evidence trace ─────────────────────────────────────────────────────── */

export type TraceOrigin = "care_gap" | "person_evidence" | "rule_review" | "documented";

export const TRACE_ORIGIN_META: Record<TraceOrigin, { title: string; description: string }> = {
  care_gap: {
    title: "Documented care gaps",
    description: "Evaluations that produced a care-gap record for this person.",
  },
  person_evidence: {
    title: "Evidence missing or conflicting for this person",
    description: "No result could be produced because this person's information is missing, partial or conflicting.",
  },
  rule_review: {
    title: "Rule-level clinical review",
    description: "The governing rule is unresolved or review-flagged — this applies to everyone in scope, not to this person specifically.",
  },
  documented: {
    title: "Documented complete or upcoming",
    description: "Evaluations where a completion is documented or the next date falls within the look-ahead period.",
  },
};

export interface TraceItem {
  evaluation: EvaluationItemOut;
  gaps: CareGapOut[];
  origin: TraceOrigin;
}

const TRACE_ORDER: TraceOrigin[] = ["care_gap", "person_evidence", "rule_review", "documented"];

function traceOrigin(e: EvaluationItemOut, hasGap: boolean): TraceOrigin | null {
  if (hasGap || e.evaluation_status === "due") return "care_gap";
  if (e.evaluation_status === "unknown" || e.evaluation_status === "insufficient_information") return "person_evidence";
  if (e.evaluation_status === "requires_clinical_review") {
    const personLevel = e.reasons.some((r) => r.guard_id && GUARD_META[r.guard_id]?.scope === "person");
    return personLevel ? "person_evidence" : "rule_review";
  }
  if (e.evaluation_status === "completed" || e.evaluation_status === "upcoming") return "documented";
  if (asEvaluationStatus(e.evaluation_status) === null) return "person_evidence";
  return null;
}

/**
 * Evaluations worth explaining, grouped by why they matter. Care gaps are always
 * included; other results are limited to the person's programmes so rule-level
 * noise from programmes they do not belong to is left out.
 */
export function buildTrace(
  patient: Pick<PatientSummaryOut, "history_by_pathway">,
  evaluations: EvaluationItemOut[],
  gaps: CareGapOut[]
): TraceItem[] {
  const members = programmesOf(patient);
  const gapsByEval = new Map<string, CareGapOut[]>();
  for (const g of gaps) gapsByEval.set(g.evaluation_id, [...(gapsByEval.get(g.evaluation_id) ?? []), g]);
  const items: TraceItem[] = [];
  for (const e of evaluations) {
    const own = gapsByEval.get(e.evaluation_id) ?? [];
    const origin = traceOrigin(e, own.length > 0);
    if (!origin) continue;
    if (origin !== "care_gap" && members.length > 0 && !members.includes(e.pathway)) continue;
    items.push({ evaluation: e, gaps: own, origin });
  }
  return items.sort((a, b) => TRACE_ORDER.indexOf(a.origin) - TRACE_ORDER.indexOf(b.origin));
}

/** Plain statements of why the engine reached its result — built only from returned codes and configured definitions. */
export function traceReasons(item: TraceItem): string[] {
  const out: string[] = [];
  for (const g of item.gaps) out.push(`${gapTypeMeta(g.gap_type).label}: ${gapTypeMeta(g.gap_type).description}`);
  for (const r of item.evaluation.reasons) {
    const guard = r.guard_id ? GUARD_META[r.guard_id] : undefined;
    const suffix = r.item_code ? ` (item ${r.item_category ?? ""}/${r.item_code})` : "";
    if (r.guard_id && guard) out.push(`${r.guard_id} fired — ${guard.when}${suffix}`);
    else if (r.guard_id) out.push(`${r.guard_id} fired (no definition available in PulseReach)${suffix}`);
    else out.push(`Reason: ${reasonCodeLabel(r.reason_code)}${suffix}`);
  }
  const status = asEvaluationStatus(item.evaluation.evaluation_status);
  if (status) out.push(`Result “${item.evaluation.evaluation_status}”: ${EVALUATION_STATUS_DEFINITIONS[status]}`);
  return out;
}

/* ── Rule specification (configured criteria, read — never hardcoded) ──── */

const SPEC_LABELS: Record<string, string> = {
  "": "Rule text",
  "eligibility.age": "Target age",
  frequency: "Frequency",
  "timing.recommended_age": "Recommended age",
  score: "Score",
};

function humanize(key: string): string {
  const s = key.replace(/\[\d+\]/g, "").split(".").pop() ?? key;
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Every `as_printed` criterion in a rule spec, labelled by where it sits, plus sex scope and evaluability flags. */
export function ruleCriteria(spec: Record<string, unknown>): { label: string; value: string; note?: string }[] {
  const rows: { label: string; value: string; note?: string }[] = [];
  const walk = (node: unknown, path: string) => {
    if (Array.isArray(node)) return node.forEach((n, i) => walk(n, `${path}[${i}]`));
    if (!node || typeof node !== "object") return;
    const obj = node as Record<string, unknown>;
    if (typeof obj.as_printed === "string") {
      const bare = path.replace(/\[\d+\]$/, "");
      const kind = typeof obj.kind === "string" ? ` (${obj.kind})` : "";
      rows.push({
        label: (SPEC_LABELS[bare] ?? humanize(bare || "rule")) + kind,
        value: obj.as_printed,
        note: obj.machine_evaluable === false ? "Not machine-evaluable — not checked by the engine" : undefined,
      });
    }
    for (const [k, v] of Object.entries(obj)) if (k !== "as_printed") walk(v, path ? `${path}.${k}` : k);
  };
  walk(spec, "");
  const eligibility = spec.eligibility as { sex?: unknown } | undefined;
  if (Array.isArray(eligibility?.sex)) rows.push({ label: "Sex in scope", value: eligibility.sex.map((s) => sexLabel(String(s))).join(", ") });
  if (typeof spec.effective_date_as_printed === "string") rows.push({ label: "Effective date", value: spec.effective_date_as_printed });
  const timing = spec.timing as { due_window_status?: unknown } | undefined;
  if (typeof timing?.due_window_status === "string") rows.push({ label: "Due window", value: humanize(timing.due_window_status) });
  if (spec.is_diagnosis === false) rows.push({ label: "Result type", value: "Screening result only — not a diagnosis" });
  return rows;
}

/* ── Recommended pathway ────────────────────────────────────────────────── */

export interface PathwayEntry {
  gap: CareGapOut;
  evaluation: EvaluationItemOut | undefined;
  rule: RuleSummaryOut | undefined;
  offered: boolean;
  /** Why a pathway is not offered (null when offered). */
  blocked: string | null;
}

/**
 * A pathway is shown only for an open gap whose evaluation is `due` under a
 * verified, authoritative rule that is not flagged for clinical review.
 */
export function buildPathways(
  gaps: CareGapOut[],
  evaluations: EvaluationItemOut[],
  rules: Map<string, RuleSummaryOut>
): PathwayEntry[] {
  return gaps.map((gap) => {
    const evaluation = evaluations.find((e) => e.evaluation_id === gap.evaluation_id);
    const rule = rules.get(gap.rule_id);
    let blocked: string | null = null;
    if (gap.status !== "open") blocked = `Gap is ${gapStatusMeta(gap.status).label.toLowerCase()} — no pathway is offered.`;
    else if (!rule) blocked = "Rule definition was not returned by the rules API.";
    else if (!evaluation) blocked = "The evaluation behind this gap was not returned.";
    else if (evaluation.evaluation_status !== "due") blocked = `Evaluation result is “${evaluation.evaluation_status}”, not due.`;
    else if (rule.verification_status !== "verified") blocked = `Rule is ${rule.verification_status}, not verified.`;
    else if (!rule.is_authoritative || rule.requires_clinical_review)
      blocked = "Rule is non-authoritative or flagged for clinical review — routed to a healthcare professional.";
    return { gap, evaluation, rule, offered: blocked === null, blocked };
  });
}

/** Services listed by the configured rule (package components or visit assessments). */
export function ruleServices(detail: RuleDetailOut): { category: string; items: { description: string; verified: boolean }[] }[] {
  const groups = new Map<string, { description: string; verified: boolean }[]>();
  for (const it of [...detail.items].sort((a, b) => a.ordinal - b.ordinal)) {
    groups.set(it.category, [
      ...(groups.get(it.category) ?? []),
      { description: it.description, verified: it.verification_status === "verified" },
    ]);
  }
  return [...groups.entries()].map(([category, items]) => ({ category: humanize(category), items }));
}
