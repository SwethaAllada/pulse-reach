import type {
  CareGapOut,
  CareGapStatus,
  OpenQuestionOut,
  Pathway,
  ProgrammeSummaryOut,
  RuleSummaryOut,
} from "@/lib/api/types";
import { ruleGroup, type RuleGroup } from "@/lib/people/person";
import { gapTypeLabel, ruleShortLabel, type CohortId, type CountRow, type SegmentId } from "@/lib/population/model";
import type { MessageKey, Translate } from "@/lib/i18n/translate";
import type { PeopleFilters } from "@/lib/people/params";

/**
 * Programme views are assembled only from backend records:
 *  - rules and their verification state        (`GET /rules`)
 *  - open questions linked to those rules      (`GET /open-questions`)
 *  - care-gap records and their status         (`GET /care-gaps`)
 *  - people-level programme breakdown          (`GET /dashboard/summary` → `pathway_breakdown`)
 *  - programme aggregates and evidence segments (`GET /programmes/{pathway}/summary`)
 * Nothing here decides eligibility, due dates or thresholds — those come from the
 * deterministic evaluation engine. This module only groups and counts.
 */

export const PROGRAMME_SLUGS: Record<Pathway, string> = { ifhas: "ifhas", well_child: "well-child" };

export function pathwayFromSlug(slug: string): Pathway | null {
  return (Object.keys(PROGRAMME_SLUGS) as Pathway[]).find((p) => PROGRAMME_SLUGS[p] === slug) ?? null;
}

export function programmeHref(pathway: Pathway, query?: URLSearchParams | string): string {
  const qs = typeof query === "string" ? query : query?.toString();
  return `/programmes/${PROGRAMME_SLUGS[pathway]}${qs ? `?${qs}` : ""}`;
}

export function ruleHref(pathway: Pathway, ruleId: string): string {
  return `/programmes/${PROGRAMME_SLUGS[pathway]}/rules/${encodeURIComponent(ruleId)}`;
}

/** Message keys (render with the bound translator). */
export const PROGRAMME_META: Record<Pathway, { name: MessageKey; full: MessageKey; audience: MessageKey; unit: MessageKey }> = {
  ifhas: { name: "pop.pathway.ifhas_short", full: "pop.pathway.ifhas", audience: "prog.audience.adults", unit: "prog.unit.adults" },
  well_child: { name: "pop.pathway.well_child_short", full: "pop.pathway.well_child", audience: "prog.audience.children", unit: "prog.unit.children" },
};

export const RULE_GROUP_META: Record<RuleGroup, { title: MessageKey; description: MessageKey }> = {
  programme: { title: "prog.group.programme", description: "prog.group.programme_desc" },
  service: { title: "prog.group.service", description: "prog.group.service_desc" },
  workflow: { title: "prog.group.workflow", description: "prog.group.workflow_desc" },
};

export const RULE_GROUP_ORDER: RuleGroup[] = ["programme", "service", "workflow"];

/* ── Rule standing (from verification fields only) ─────────────────────── */

export type RuleStanding = "authoritative" | "review" | "unresolved";

export const STANDING_META: Record<RuleStanding, { label: MessageKey; description: MessageKey }> = {
  authoritative: { label: "prog.standing.authoritative", description: "prog.standing.authoritative_desc" },
  review: { label: "prog.standing.review", description: "prog.standing.review_desc" },
  unresolved: { label: "prog.standing.unresolved", description: "prog.standing.unresolved_desc" },
};

export function ruleStanding(rule: Pick<RuleSummaryOut, "verification_status" | "is_authoritative" | "requires_clinical_review">): RuleStanding {
  if (rule.verification_status !== "verified") return "unresolved";
  if (!rule.is_authoritative || rule.requires_clinical_review) return "review";
  return "authoritative";
}

/* ── Care-gap status vocabulary ────────────────────────────────────────── */

export const GAP_STATUS_ORDER: CareGapStatus[] = ["open", "closed_completed", "closed_refused", "suppressed", "superseded"];

export const GAP_STATUS_META: Record<CareGapStatus, { label: MessageKey; short: MessageKey; description: MessageKey }> = {
  open: { label: "prog.gap.open", short: "prog.gap.open_short", description: "prog.gap.open_desc" },
  closed_completed: { label: "prog.gap.completed", short: "prog.gap.completed_short", description: "prog.gap.completed_desc" },
  closed_refused: { label: "prog.gap.refused", short: "prog.gap.refused_short", description: "prog.gap.refused_desc" },
  suppressed: { label: "prog.gap.suppressed", short: "prog.gap.suppressed", description: "prog.gap.suppressed_desc" },
  superseded: { label: "prog.gap.superseded", short: "prog.gap.superseded", description: "prog.gap.superseded_desc" },
};

export type GapStatusCounts = Record<CareGapStatus, number> & { total: number };

function emptyGapCounts(): GapStatusCounts {
  return { open: 0, closed_completed: 0, closed_refused: 0, suppressed: 0, superseded: 0, total: 0 };
}

function addGap(c: GapStatusCounts, status: string) {
  if (status in c && status !== "total") c[status as CareGapStatus] += 1;
  c.total += 1;
}

/* ── Programme model ───────────────────────────────────────────────────── */

export interface RuleRow {
  rule: RuleSummaryOut;
  label: string;
  group: RuleGroup;
  standing: RuleStanding;
  gaps: GapStatusCounts;
  /** Distinct people with an open gap under this rule. */
  openPeople: number;
  openQuestionIds: string[];
}

export interface ProgrammeModel {
  pathway: Pathway;
  source: { name: string; version: string } | null;
  rules: RuleRow[];
  standing: Record<RuleStanding, number>;
  gaps: GapStatusCounts;
  gapTypes: CountRow[];
  /** People with ≥1 open gap under this programme's rules. */
  peopleWithOpenGap: number;
  openQuestions: OpenQuestionOut[];
}

function mostCommon<T>(items: T[], key: (t: T) => string): T | null {
  const counts = new Map<string, { n: number; item: T }>();
  for (const it of items) {
    const k = key(it);
    const e = counts.get(k);
    counts.set(k, { n: (e?.n ?? 0) + 1, item: e?.item ?? it });
  }
  return [...counts.values()].sort((a, b) => b.n - a.n)[0]?.item ?? null;
}

/**
 * @param patientIds when set, only care gaps of these people are counted (the
 *   backend-filtered patient set of the current exploration filters).
 */
export function buildProgrammeModel(
  pathway: Pathway,
  rules: RuleSummaryOut[],
  careGaps: CareGapOut[],
  openQuestions: OpenQuestionOut[],
  t: Translate,
  patientIds: Set<string> | null = null
): ProgrammeModel {
  const own = rules.filter((r) => r.pathway === pathway);
  const ids = new Set(own.map((r) => r.rule_id));
  const gaps = careGaps.filter((g) => ids.has(g.rule_id) && (!patientIds || patientIds.has(g.patient_id)));

  const byRule = new Map<string, { counts: GapStatusCounts; openPeople: Set<string> }>();
  const total = emptyGapCounts();
  const types = new Map<string, number>();
  const openPeople = new Set<string>();
  for (const g of gaps) {
    const e = byRule.get(g.rule_id) ?? { counts: emptyGapCounts(), openPeople: new Set<string>() };
    addGap(e.counts, g.status);
    addGap(total, g.status);
    if (g.status === "open") {
      e.openPeople.add(g.patient_id);
      openPeople.add(g.patient_id);
      types.set(g.gap_type, (types.get(g.gap_type) ?? 0) + 1);
    }
    byRule.set(g.rule_id, e);
  }

  const oqByRule = new Map<string, string[]>();
  for (const q of openQuestions) for (const rid of q.rule_ids) oqByRule.set(rid, [...(oqByRule.get(rid) ?? []), q.oq_id]);

  const rows: RuleRow[] = own.map((rule) => {
    const e = byRule.get(rule.rule_id);
    return {
      rule,
      label: ruleShortLabel(rule, rule.rule_id),
      group: ruleGroup(rule.rule_type),
      standing: ruleStanding(rule),
      gaps: e?.counts ?? emptyGapCounts(),
      openPeople: e?.openPeople.size ?? 0,
      openQuestionIds: [...new Set([...rule.open_question_ids, ...(oqByRule.get(rule.rule_id) ?? [])])],
    };
  });

  const standing: Record<RuleStanding, number> = { authoritative: 0, review: 0, unresolved: 0 };
  for (const r of rows) standing[r.standing] += 1;

  const src = mostCommon(own, (r) => `${r.source_name}|${r.source_version}`);
  return {
    pathway,
    source: src ? { name: src.source_name, version: src.source_version } : null,
    rules: rows,
    standing,
    gaps: total,
    gapTypes: [...types.entries()]
      .map(([key, count]) => ({ key, label: gapTypeLabel(key, t), count }))
      .sort((a, b) => b.count - a.count),
    peopleWithOpenGap: openPeople.size,
    openQuestions: openQuestions.filter((q) => q.rule_ids.some((id) => ids.has(id))),
  };
}

/* ── Evidence classes (what each programme figure is, and is not) ─────── */

export type EvidenceClass = "calculated" | "recorded_gap" | "completed" | "missing_history";

export const EVIDENCE_META: Record<EvidenceClass, { title: MessageKey; source: MessageKey; caution: MessageKey }> = {
  calculated: { title: "prog.evidence.calculated", source: "prog.evidence.calculated_source", caution: "prog.evidence.calculated_caution" },
  recorded_gap: { title: "prog.evidence.recorded_gap", source: "prog.evidence.recorded_gap_source", caution: "prog.evidence.recorded_gap_caution" },
  completed: { title: "prog.evidence.completed", source: "prog.evidence.completed_source", caution: "prog.evidence.completed_caution" },
  missing_history: {
    title: "prog.evidence.missing_history",
    source: "prog.evidence.missing_history_source",
    caution: "prog.evidence.missing_history_caution",
  },
};

export interface EvidenceFigure {
  cls: EvidenceClass;
  value: number | null;
  unit: string;
  detail: string;
}

/** A server-side count: `null` means suppressed (small cell), never zero. */
export function countText(n: number | null, t: Translate): string {
  return n === null ? t("prog.suppressed") : String(n);
}

/**
 * Evidence ledger for one programme, from the server-side programme summary (scope and filters
 * applied by the backend). `null` summary = not available; `null` values = suppressed for privacy.
 */
export function evidenceFigures(s: ProgrammeSummaryOut | null, t: Translate): EvidenceFigure[] {
  const c = (n: number | null | undefined) => countText(n ?? null, t);
  const fig = (cls: EvidenceClass, value: number | null | undefined, unit: MessageKey, detail: string): EvidenceFigure => ({
    cls,
    value: value ?? null,
    unit: t(unit),
    detail: !s ? t("prog.summary_unavailable") : value === null ? t("prog.suppressed_detail", { min: s.min_cell_size }) : detail,
  });
  return [
    fig(
      "calculated",
      s?.eligibility.due_or_upcoming_patients,
      "prog.fig.calculated_unit",
      t("prog.fig.calculated_detail", { count: c(s?.eligibility.programme_eligible_patients) })
    ),
    fig("recorded_gap", s?.care_gaps.open, "prog.fig.recorded_unit", t("prog.fig.recorded_detail", { count: c(s?.people_with_open_gap) })),
    fig("completed", s?.care_gaps.closed_completed, "prog.fig.completed_unit", t("prog.fig.completed_detail", { count: c(s?.care_gaps.total) })),
    fig(
      "missing_history",
      s?.history.not_available,
      "prog.fig.missing_unit",
      t("prog.fig.missing_detail", { partial: c(s?.history.partial), members: c(s?.members) })
    ),
  ];
}

/** Composition-band input from a programme summary; null when the member count or any segment is suppressed. */
export function summaryBand(s: ProgrammeSummaryOut, t: Translate): {
  label: string;
  people: number;
  segments: { id: CohortId; segment: SegmentId; people: number }[];
} | null {
  if (s.members === null || s.segments.some((x) => x.people === null)) return null;
  return {
    label: t(PROGRAMME_META[s.pathway].name),
    people: s.members,
    segments: s.segments.map((x) => ({ id: `${s.pathway}:${x.segment}` as CohortId, segment: x.segment, people: x.people ?? 0 })),
  };
}

/* ── Segment → People workspace drill-down ─────────────────────────────── */

/**
 * The `GET /patients` filters for a programme segment. With `pathway` set the backend scopes
 * `has_open_care_gaps` and `history_status` to that programme; older API versions matched any
 * programme, so callers still compare the backend total with the segment count and disclose any
 * difference.
 */
export function segmentPeopleFilters(pathway: Pathway, segment: SegmentId | null, base: PeopleFilters): PeopleFilters {
  const f: PeopleFilters = { region_id: base.region_id, sex: base.sex, age_band: base.age_band, pathway };
  if (segment === "open_gap") f.has_open_care_gaps = true;
  else if (segment) {
    f.history_status = segment;
    f.has_open_care_gaps = false;
  }
  return f;
}
