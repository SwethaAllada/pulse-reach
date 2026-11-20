import type {
  CareGapOut,
  CareGapStatus,
  OpenQuestionOut,
  Pathway,
  PathwayBreakdownOut,
  RuleSummaryOut,
} from "@/lib/api/types";
import { ruleGroup, type RuleGroup } from "@/lib/people/person";
import { GAP_TYPE_LABELS, ruleShortLabel, type CountRow, type SegmentId } from "@/lib/population/model";
import type { PeopleFilters } from "@/lib/people/params";

/**
 * Programme views are assembled only from backend records:
 *  - rules and their verification state        (`GET /rules`)
 *  - open questions linked to those rules      (`GET /open-questions`)
 *  - care-gap records and their status         (`GET /care-gaps`)
 *  - people-level programme breakdown          (`GET /dashboard/summary` → `pathway_breakdown`)
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

export const PROGRAMME_META: Record<Pathway, { name: string; full: string; audience: string; unit: string }> = {
  ifhas: { name: "IFHAS", full: "IFHAS adult screening", audience: "Adults", unit: "adults" },
  well_child: { name: "Well-Child", full: "Well-Child visits", audience: "Children", unit: "children" },
};

export const RULE_GROUP_META: Record<RuleGroup, { title: string; description: string }> = {
  programme: {
    title: "Programme gates",
    description: "Who the programme applies to and whether it is in force — eligibility, scope and status rules.",
  },
  service: {
    title: "Preventive services",
    description: "The screening packages, scheduled visits and developmental screening tiers the programme defines.",
  },
  workflow: {
    title: "Timing & follow-up",
    description: "Windows and policies for when services and follow-up should happen.",
  },
};

export const RULE_GROUP_ORDER: RuleGroup[] = ["programme", "service", "workflow"];

/* ── Rule standing (from verification fields only) ─────────────────────── */

export type RuleStanding = "authoritative" | "review" | "unresolved";

export const STANDING_META: Record<RuleStanding, { label: string; description: string }> = {
  authoritative: {
    label: "Verified & authoritative",
    description: "Transcription verified against the published standard; results under this rule can be acted on.",
  },
  review: {
    label: "Needs clinical review",
    description: "Verified transcription, but non-authoritative or flagged for review: results route to a healthcare professional.",
  },
  unresolved: {
    label: "Unresolved",
    description: "The standard leaves this rule open (e.g. no window defined). The engine never automates a result from it.",
  },
};

export function ruleStanding(rule: Pick<RuleSummaryOut, "verification_status" | "is_authoritative" | "requires_clinical_review">): RuleStanding {
  if (rule.verification_status !== "verified") return "unresolved";
  if (!rule.is_authoritative || rule.requires_clinical_review) return "review";
  return "authoritative";
}

/* ── Care-gap status vocabulary ────────────────────────────────────────── */

export const GAP_STATUS_ORDER: CareGapStatus[] = ["open", "closed_completed", "closed_refused", "suppressed", "superseded"];

export const GAP_STATUS_META: Record<CareGapStatus, { label: string; short: string; description: string }> = {
  open: { label: "Open care gap", short: "Open", description: "Recorded by the engine and not yet closed." },
  closed_completed: {
    label: "Closed by documented completion",
    short: "Completed",
    description: "Closed because a qualifying screening, visit or referral was documented.",
  },
  closed_refused: {
    label: "Closed by documented refusal",
    short: "Refused",
    description: "Closed by a recorded refusal. The service was not completed.",
  },
  suppressed: { label: "Suppressed", short: "Suppressed", description: "Not actioned. Not a completion." },
  superseded: { label: "Superseded", short: "Superseded", description: "Replaced by a later evaluation. Not a completion." },
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
      .map(([key, count]) => ({ key, label: GAP_TYPE_LABELS[key as keyof typeof GAP_TYPE_LABELS] ?? key, count }))
      .sort((a, b) => b.count - a.count),
    peopleWithOpenGap: openPeople.size,
    openQuestions: openQuestions.filter((q) => q.rule_ids.some((id) => ids.has(id))),
  };
}

/* ── Evidence classes (what each programme figure is, and is not) ─────── */

export type EvidenceClass = "calculated" | "recorded_gap" | "completed" | "missing_history";

export const EVIDENCE_META: Record<EvidenceClass, { title: string; source: string; caution: string }> = {
  calculated: {
    title: "Backend-calculated eligibility",
    source: "Deterministic rule evaluations, counted per person inside each rule's printed age/sex band.",
    caution: "“In scope” is not a care need; due or upcoming results are.",
  },
  recorded_gap: {
    title: "Recorded care gaps",
    source: "Care-gap records the engine opened for an in-scope person with no qualifying documented service.",
    caution: "Counts are gap records unless stated as people — one person can hold several.",
  },
  completed: {
    title: "Completed care",
    source: "Gap records closed because a qualifying screening, visit or referral was documented.",
    caution: "Only documented completions count. Refusals, suppression and supersession are not completions.",
  },
  missing_history: {
    title: "Missing or unavailable history",
    source: "People whose screening or visit history is not available to the engine — their evaluations resolve to “unknown”.",
    caution: "Missing history is never evidence that care did not happen.",
  },
};

export interface EvidenceFigure {
  cls: EvidenceClass;
  value: number | null;
  unit: string;
  detail: string;
}

/** Evidence ledger for one programme, straight from the backend breakdown and gap records. */
export function evidenceFigures(
  breakdown: PathwayBreakdownOut | undefined,
  model: ProgrammeModel,
  members: { total: number; history: Record<"available" | "partial" | "not_available", number> } | null,
  /** False when care-gap records are not (yet) available — gap figures are then unknown, never zero. */
  gapsKnown = true
): EvidenceFigure[] {
  const noGaps = "Care-gap records are not available";
  return [
    {
      cls: "calculated",
      value: breakdown?.due_or_upcoming_patients ?? null,
      unit: "people due or upcoming",
      detail: breakdown
        ? `${breakdown.programme_eligible_patients} people with an in-scope programme result · run-wide, filters not applied`
        : "Programme breakdown not returned by the API",
    },
    {
      cls: "recorded_gap",
      value: gapsKnown ? model.gaps.open : null,
      unit: "open gap records",
      detail: gapsKnown ? `${model.peopleWithOpenGap} people hold at least one` : noGaps,
    },
    {
      cls: "completed",
      value: gapsKnown ? model.gaps.closed_completed : null,
      unit: "gaps closed by documented completion",
      detail: gapsKnown ? `of ${model.gaps.total} gap records ever opened under these rules` : noGaps,
    },
    {
      cls: "missing_history",
      value: members ? members.history.not_available : (breakdown?.unknown_history_patients ?? null),
      unit: "people without available history",
      detail: members
        ? `${members.history.partial} more with partial history · of ${members.total} members`
        : "From the programme breakdown",
    },
  ];
}

/* ── Segment → People workspace drill-down ─────────────────────────────── */

/**
 * The `GET /patients` filters closest to a programme segment. `has_open_care_gaps`
 * and `history_status` match any programme, so callers compare the backend total
 * with the segment count and disclose any difference.
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
