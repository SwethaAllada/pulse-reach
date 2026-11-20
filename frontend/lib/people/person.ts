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
import { PATHWAY_OPTIONS, sexLabel as populationSexLabel } from "@/lib/population/filters";
import type { MessageKey, Translate } from "@/lib/i18n/translate";

/*
 * Clinical vocabulary of the person views. Every label is a message key rendered with the bound
 * translator; the Arabic renderings must keep the engine's meaning exactly (glossary:
 * docs/localization-glossary.md) and require clinical-language review before real-world use.
 */

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
export function ageLabel(dob: string | null, referenceDate: string | null, t: Translate): string {
  if (!dob) return t("person.age.no_dob");
  const months = ageInMonths(dob, referenceDate);
  if (months === null) return t("person.age.not_available");
  if (months < 24) return t(months === 1 ? "person.age.month" : "person.age.months", { count: String(months) });
  return t("person.age.years", { count: String(Math.floor(months / 12)) });
}

export function sexLabel(sex: string | null, t: Translate): string {
  return populationSexLabel(sex, t);
}

/** Programme membership = pathways with a history-availability record. */
export function programmesOf(patient: Pick<PatientSummaryOut, "history_by_pathway">): Pathway[] {
  return PATHWAY_OPTIONS.map((o) => o.value).filter((p) => patient.history_by_pathway[p] !== undefined);
}

export const HISTORY_META: Record<HistoryStatus, { label: MessageKey; description: MessageKey }> = {
  available: { label: "person.history.available", description: "person.history.available_desc" },
  partial: { label: "person.history.partial", description: "person.history.partial_desc" },
  not_available: { label: "person.history.not_available", description: "person.history.not_available_desc" },
};

export function historyMeta(status: string | undefined, t: Translate): { label: string; description: string } {
  const meta = status && status in HISTORY_META ? HISTORY_META[status as HistoryStatus] : null;
  return meta
    ? { label: t(meta.label), description: t(meta.description) }
    : { label: t("person.history.not_recorded"), description: t("person.history.not_recorded_desc") };
}

/* ── Care gaps ──────────────────────────────────────────────────────────── */

export function openGapCountByPatient(gaps: CareGapOut[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const g of gaps) if (gapStatusFlags(g.status).isOpen) counts.set(g.patient_id, (counts.get(g.patient_id) ?? 0) + 1);
  return counts;
}

export interface GapStatusFlags {
  /** Glyph shape reused from the evaluation status set. */
  glyph: EvaluationStatus;
  isOpen: boolean;
  isCompleted: boolean;
}

export interface GapStatusMeta extends GapStatusFlags {
  label: string;
  description: string;
}

const GAP_STATUS: Record<string, GapStatusFlags & { key: string }> = {
  open: { key: "open", glyph: "due", isOpen: true, isCompleted: false },
  closed_completed: { key: "closed_completed", glyph: "completed", isOpen: false, isCompleted: true },
  closed_refused: { key: "closed_refused", glyph: "not_eligible", isOpen: false, isCompleted: false },
  suppressed: { key: "suppressed", glyph: "not_eligible", isOpen: false, isCompleted: false },
  superseded: { key: "superseded", glyph: "not_eligible", isOpen: false, isCompleted: false },
  scheduled: { key: "scheduled", glyph: "upcoming", isOpen: true, isCompleted: false },
  cancelled: { key: "cancelled", glyph: "unknown", isOpen: true, isCompleted: false },
};

/**
 * Care-gap status vocabulary. Only `closed_completed` is a completion —
 * refusals, scheduling, cancellation and supersession never count as done,
 * and anything unrecognised stays "unknown".
 */
export function gapStatusFlags(status: string): GapStatusFlags {
  return GAP_STATUS[status] ?? { glyph: "unknown", isOpen: false, isCompleted: false };
}

export function gapStatusMeta(status: string, t: Translate): GapStatusMeta {
  const known = GAP_STATUS[status];
  if (!known) return { ...gapStatusFlags(status), label: t("person.gap_status.unknown", { status }), description: t("person.gap_status.unknown_desc") };
  return {
    ...known,
    label: t(`person.gap_status.${known.key}` as MessageKey),
    description: t(`person.gap_status.${known.key}_desc` as MessageKey),
  };
}

/** Gap-type meanings, as produced by `app/services/evaluation/engine.py`. */
const GAP_TYPES: CareGapType[] = [
  "no_documented_screening",
  "interval_elapsed",
  "partial_completion",
  "referral_not_initiated",
  "visit_not_attended",
];

export function gapTypeMeta(type: string, t: Translate): { label: string; description: string } {
  if (!(GAP_TYPES as string[]).includes(type)) return { label: type, description: t("person.gap_type.unknown_desc") };
  return { label: t(`pop.gap_type.${type}` as MessageKey), description: t(`person.gap_type.${type}_desc` as MessageKey) };
}

/** Historical records a gap points at — documented evidence, distinct from the evaluation result. */
export function gapEvidenceRefs(gap: CareGapOut, t: Translate): { label: string; id: string }[] {
  const refs: { label: string; id: string }[] = [];
  if (gap.subject_ifhas_screening_id) refs.push({ label: t("person.ref.ifhas"), id: gap.subject_ifhas_screening_id });
  if (gap.subject_well_child_visit_id) refs.push({ label: t("person.ref.well_child"), id: gap.subject_well_child_visit_id });
  if (gap.subject_referral_id) refs.push({ label: t("person.ref.referral"), id: gap.subject_referral_id });
  if (gap.closed_by_consent_id) refs.push({ label: t("person.ref.consent"), id: gap.closed_by_consent_id });
  if (gap.closed_by_component_result_id) refs.push({ label: t("person.ref.component"), id: gap.closed_by_component_result_id });
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

/** Definitions from `status_definitions.yaml` (message keys `person.eval_def.<status>`). */
export function evaluationDefinition(status: EvaluationStatus, t: Translate): string {
  return t(`person.eval_def.${status}` as MessageKey);
}

export const GUARD_META: Record<string, { when: MessageKey; scope: "person" | "rule" }> = {
  "GUARD-MISSING-DOB": { when: "person.guard.missing_dob", scope: "person" },
  "GUARD-MISSING-ATTRIBUTE": { when: "person.guard.missing_attribute", scope: "person" },
  "GUARD-MISSING-HISTORY": { when: "person.guard.missing_history", scope: "person" },
  "GUARD-CONFLICTING-RECORDS": { when: "person.guard.conflicting_records", scope: "person" },
  "GUARD-RULE-NOT-VERIFIED": { when: "person.guard.rule_not_verified", scope: "rule" },
  "GUARD-RULE-REVIEW-FLAG": { when: "person.guard.rule_review_flag", scope: "rule" },
  "GUARD-ITEM-UNRESOLVED": { when: "person.guard.item_unresolved", scope: "rule" },
};

const REASON_CODES = [
  "missing_date_of_birth",
  "missing_sex",
  "missing_required_attribute",
  "missing_screening_history",
  "conflicting_records",
  "rule_unresolved",
  "rule_reported_not_verified",
  "rule_requires_clinical_review",
  "rule_item_unresolved",
];

/** Localized reason; an unrecognised code is shown as returned. */
export function reasonCodeLabel(code: string, t: Translate): string {
  return REASON_CODES.includes(code) ? t(`person.reason.${code}` as MessageKey) : code;
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
      openGaps: pathwayGaps.filter((g) => gapStatusFlags(g.status).isOpen).length,
      closedGaps: pathwayGaps.filter((g) => !gapStatusFlags(g.status).isOpen).length,
    };
  });
}

/* ── Evidence trace ─────────────────────────────────────────────────────── */

export type TraceOrigin = "care_gap" | "person_evidence" | "rule_review" | "documented";

export const TRACE_ORIGIN_META: Record<TraceOrigin, { title: MessageKey; description: MessageKey }> = {
  care_gap: { title: "person.trace.care_gap", description: "person.trace.care_gap_desc" },
  person_evidence: { title: "person.trace.person_evidence", description: "person.trace.person_evidence_desc" },
  rule_review: { title: "person.trace.rule_review", description: "person.trace.rule_review_desc" },
  documented: { title: "person.trace.documented", description: "person.trace.documented_desc" },
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
export function traceReasons(item: TraceItem, t: Translate): string[] {
  const out: string[] = [];
  for (const g of item.gaps) {
    const m = gapTypeMeta(g.gap_type, t);
    out.push(t("person.trace.gap_reason", { label: m.label, description: m.description }));
  }
  for (const r of item.evaluation.reasons) {
    const guard = r.guard_id ? GUARD_META[r.guard_id] : undefined;
    const suffix = r.item_code ? ` ${t("person.trace.item", { item: `${r.item_category ?? ""}/${r.item_code}` })}` : "";
    if (r.guard_id && guard) out.push(t("person.trace.guard", { guard: r.guard_id, when: t(guard.when) }) + suffix);
    else if (r.guard_id) out.push(t("person.trace.guard_unknown", { guard: r.guard_id }) + suffix);
    else out.push(t("person.trace.reason", { reason: reasonCodeLabel(r.reason_code, t) }) + suffix);
  }
  const status = asEvaluationStatus(item.evaluation.evaluation_status);
  if (status) out.push(t("person.trace.result", { status: item.evaluation.evaluation_status, definition: evaluationDefinition(status, t) }));
  return out;
}

/* ── Rule specification (configured criteria, read — never hardcoded) ──── */

const SPEC_LABELS: Record<string, MessageKey> = {
  "": "person.spec.rule_text",
  "eligibility.age": "person.spec.target_age",
  frequency: "person.spec.frequency",
  "timing.recommended_age": "person.spec.recommended_age",
  score: "person.spec.score",
};

function humanize(key: string): string {
  const s = key.replace(/\[\d+\]/g, "").split(".").pop() ?? key;
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/**
 * Every `as_printed` criterion in a rule spec, labelled by where it sits, plus sex scope and evaluability
 * flags. `as_printed` values are the published standard's wording and are shown as printed.
 */
export function ruleCriteria(spec: Record<string, unknown>, t: Translate): { label: string; value: string; note?: string }[] {
  const rows: { label: string; value: string; note?: string }[] = [];
  const walk = (node: unknown, path: string) => {
    if (Array.isArray(node)) return node.forEach((n, i) => walk(n, `${path}[${i}]`));
    if (!node || typeof node !== "object") return;
    const obj = node as Record<string, unknown>;
    if (typeof obj.as_printed === "string") {
      const bare = path.replace(/\[\d+\]$/, "");
      const kind = typeof obj.kind === "string" ? ` (${obj.kind})` : "";
      rows.push({
        label: (SPEC_LABELS[bare] ? t(SPEC_LABELS[bare]) : humanize(bare || "rule")) + kind,
        value: obj.as_printed,
        note: obj.machine_evaluable === false ? t("person.spec.not_evaluable") : undefined,
      });
    }
    for (const [k, v] of Object.entries(obj)) if (k !== "as_printed") walk(v, path ? `${path}.${k}` : k);
  };
  walk(spec, "");
  const eligibility = spec.eligibility as { sex?: unknown } | undefined;
  if (Array.isArray(eligibility?.sex))
    rows.push({ label: t("person.spec.sex_scope"), value: eligibility.sex.map((s) => sexLabel(String(s), t)).join(t("list.sep")) });
  if (typeof spec.effective_date_as_printed === "string") rows.push({ label: t("person.spec.effective_date"), value: spec.effective_date_as_printed });
  const timing = spec.timing as { due_window_status?: unknown } | undefined;
  if (typeof timing?.due_window_status === "string") rows.push({ label: t("person.spec.due_window"), value: humanize(timing.due_window_status) });
  if (spec.is_diagnosis === false) rows.push({ label: t("person.spec.result_type"), value: t("person.spec.not_diagnosis") });
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
  rules: Map<string, RuleSummaryOut>,
  t: Translate
): PathwayEntry[] {
  return gaps.map((gap) => {
    const evaluation = evaluations.find((e) => e.evaluation_id === gap.evaluation_id);
    const rule = rules.get(gap.rule_id);
    let blocked: string | null = null;
    if (gap.status !== "open") blocked = t("person.pathway.gap_closed", { status: gapStatusMeta(gap.status, t).label.toLowerCase() });
    else if (!rule) blocked = t("person.pathway.no_rule");
    else if (!evaluation) blocked = t("person.pathway.no_evaluation");
    else if (evaluation.evaluation_status !== "due") blocked = t("person.pathway.not_due", { status: evaluation.evaluation_status });
    else if (rule.verification_status !== "verified") blocked = t("person.pathway.not_verified", { status: rule.verification_status });
    else if (!rule.is_authoritative || rule.requires_clinical_review) blocked = t("person.pathway.review");
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
