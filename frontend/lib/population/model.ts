import type {
  CareGapOut,
  CareGapType,
  HistoryStatus,
  Pathway,
  PatientSummaryOut,
  RuleSummaryOut,
} from "@/lib/api/types";
import type { MessageKey, Translate } from "@/lib/i18n/translate";
import { PATHWAY_OPTIONS, REGION_OPTIONS, pathwayLabel, regionLabel, sexLabel } from "./filters";

/**
 * Person-level roll-up of the population, built from complete (all-page) API
 * results. Segments use only backend fields — open care-gap records and the
 * per-pathway `history_by_pathway` status — and are mutually exclusive within
 * a programme: an open documented gap takes precedence, otherwise the
 * person's history availability decides.
 */
export type SegmentId = "open_gap" | "available" | "partial" | "not_available";
export type CohortId = Pathway | `${Pathway}:${SegmentId}`;

export const SEGMENT_ORDER: SegmentId[] = ["open_gap", "available", "partial", "not_available"];

/** Message keys per segment (render with the bound translator). */
export const SEGMENT_META: Record<SegmentId, { label: MessageKey; short: MessageKey; description: MessageKey }> = {
  open_gap: { label: "pop.segment.open_gap", short: "pop.segment.open_gap_short", description: "pop.segment.open_gap_desc" },
  available: { label: "pop.segment.available", short: "pop.segment.available_short", description: "pop.segment.available_desc" },
  partial: { label: "pop.segment.partial", short: "pop.segment.partial_short", description: "pop.segment.partial_desc" },
  not_available: {
    label: "pop.segment.not_available",
    short: "pop.segment.not_available_short",
    description: "pop.segment.not_available_desc",
  },
};

export interface CountRow {
  key: string;
  label: string;
  count: number;
}

export interface Cohort {
  id: CohortId;
  pathway: Pathway;
  segment: SegmentId | null;
  label: string;
  description: string;
  people: number;
  /** Members of this cohort, in API order. */
  patientIds: string[];
  peopleWithOpenGap: number;
  openGaps: number;
  gapsByRule: CountRow[];
  gapsByType: CountRow[];
}

export interface Programme extends Cohort {
  segment: null;
  segments: Cohort[];
  history: Record<HistoryStatus, number>;
  /** Open gap records per member under this programme's rules. */
  openGapsByPatient: Map<string, number>;
}

export interface PopulationModel {
  totalPeople: number;
  /** IDs of every person in the (backend-filtered) set. */
  patientIds: string[];
  patientsById: Map<string, PatientSummaryOut>;
  /** People with no history row for any pathway (not placed in a programme). */
  unassignedPeople: number;
  peopleWithOpenGap: number;
  openGaps: number;
  historyAvailablePeople: number;
  programmes: Programme[];
  byRegion: { regionId: number; label: string; total: number; byPathway: Record<Pathway, number> }[];
  bySex: CountRow[];
  gapsByRule: (CountRow & { pathway: Pathway })[];
  gapsByType: CountRow[];
}

export const GAP_TYPE_LABELS: Record<CareGapType, MessageKey> = {
  no_documented_screening: "pop.gap_type.no_documented_screening",
  interval_elapsed: "pop.gap_type.interval_elapsed",
  partial_completion: "pop.gap_type.partial_completion",
  referral_not_initiated: "pop.gap_type.referral_not_initiated",
  visit_not_attended: "pop.gap_type.visit_not_attended",
};

/** Localized gap type; an unknown type is shown as its identifier. */
export function gapTypeLabel(type: string, t: Translate): string {
  const key = GAP_TYPE_LABELS[type as CareGapType];
  return key ? t(key) : type;
}

/**
 * Short display name from the rule description (text before the first colon). Rule descriptions
 * are source content of the official standards (English); they are shown as published.
 */
export function ruleShortLabel(rule: RuleSummaryOut | undefined, ruleId: string): string {
  if (!rule) return ruleId;
  const head = rule.description.split(":")[0].trim();
  return head.length > 0 && head.length <= 90 ? head : ruleId;
}

function tally<T>(items: T[], keyOf: (t: T) => string, labelOf: (k: string) => string): CountRow[] {
  const counts = new Map<string, number>();
  for (const it of items) counts.set(keyOf(it), (counts.get(keyOf(it)) ?? 0) + 1);
  return [...counts.entries()]
    .map(([key, count]) => ({ key, label: labelOf(key), count }))
    .sort((a, b) => b.count - a.count || a.key.localeCompare(b.key));
}

function buildCohort(
  id: CohortId,
  pathway: Pathway,
  segment: SegmentId | null,
  people: PatientSummaryOut[],
  gapsOf: (patientId: string) => CareGapOut[],
  ruleLabel: (ruleId: string) => string,
  t: Translate
): Cohort {
  const gaps = people.flatMap((p) => gapsOf(p.patient_id));
  const meta = segment ? SEGMENT_META[segment] : null;
  return {
    id,
    pathway,
    segment,
    label: meta ? t(meta.label) : pathwayLabel(pathway, t),
    description: meta ? t(meta.description) : t("pop.cohort.programme_desc", { programme: pathwayLabel(pathway, t) }),
    people: people.length,
    patientIds: people.map((p) => p.patient_id),
    peopleWithOpenGap: people.filter((p) => gapsOf(p.patient_id).length > 0).length,
    openGaps: gaps.length,
    gapsByRule: tally(gaps, (g) => g.rule_id, ruleLabel),
    gapsByType: tally(gaps, (g) => g.gap_type, (k) => gapTypeLabel(k, t)),
  };
}

export function buildPopulationModel(
  patients: PatientSummaryOut[],
  careGaps: CareGapOut[],
  rules: RuleSummaryOut[],
  t: Translate
): PopulationModel {
  const ruleById = new Map(rules.map((r) => [r.rule_id, r]));
  const ruleLabel = (id: string) => ruleShortLabel(ruleById.get(id), id);
  const patientIds = new Set(patients.map((p) => p.patient_id));

  // Open gaps for people in the (backend-filtered) patient set, keyed by patient + rule pathway.
  const openGaps = careGaps.filter(
    (g) => g.status === "open" && patientIds.has(g.patient_id) && ruleById.has(g.rule_id)
  );
  const openByPatientPathway = new Map<string, CareGapOut[]>();
  for (const g of openGaps) {
    const k = `${g.patient_id}|${ruleById.get(g.rule_id)!.pathway}`;
    openByPatientPathway.set(k, [...(openByPatientPathway.get(k) ?? []), g]);
  }

  const programmes: Programme[] = PATHWAY_OPTIONS.map(({ value: pathway }) => {
    const members = patients.filter((p) => p.history_by_pathway[pathway] !== undefined);
    const gapsOf = (id: string) => openByPatientPathway.get(`${id}|${pathway}`) ?? [];
    const segmentOf = (p: PatientSummaryOut): SegmentId =>
      gapsOf(p.patient_id).length > 0 ? "open_gap" : p.history_by_pathway[pathway]!;
    const history: Record<HistoryStatus, number> = { available: 0, partial: 0, not_available: 0 };
    for (const p of members) history[p.history_by_pathway[pathway]!] += 1;
    return {
      ...buildCohort(pathway, pathway, null, members, gapsOf, ruleLabel, t),
      segment: null,
      history,
      openGapsByPatient: new Map(members.map((p) => [p.patient_id, gapsOf(p.patient_id).length])),
      segments: SEGMENT_ORDER.map((seg) =>
        buildCohort(
          `${pathway}:${seg}`,
          pathway,
          seg,
          members.filter((p) => segmentOf(p) === seg),
          gapsOf,
          ruleLabel,
          t
        )
      ),
    };
  });

  const byRegion = REGION_OPTIONS.map(({ value }) => {
    const inRegion = patients.filter((p) => p.region_id === value);
    return {
      regionId: value as number,
      label: regionLabel(value, t),
      total: inRegion.length,
      byPathway: {
        ifhas: inRegion.filter((p) => p.history_by_pathway.ifhas !== undefined).length,
        well_child: inRegion.filter((p) => p.history_by_pathway.well_child !== undefined).length,
      },
    };
  });

  const openPeople = new Set(openGaps.map((g) => g.patient_id));
  return {
    totalPeople: patients.length,
    patientIds: patients.map((p) => p.patient_id),
    patientsById: new Map(patients.map((p) => [p.patient_id, p])),
    unassignedPeople: patients.filter((p) => Object.keys(p.history_by_pathway).length === 0).length,
    peopleWithOpenGap: openPeople.size,
    openGaps: openGaps.length,
    historyAvailablePeople: patients.filter((p) =>
      Object.values(p.history_by_pathway).some((h) => h === "available")
    ).length,
    programmes,
    byRegion,
    bySex: tally(
      patients,
      (p) => p.sex ?? "not_recorded",
      (k) => sexLabel(k, t)
    ),
    gapsByRule: tally(openGaps, (g) => g.rule_id, ruleLabel).map((row) => ({
      ...row,
      pathway: ruleById.get(row.key)!.pathway,
    })),
    gapsByType: tally(openGaps, (g) => g.gap_type, (k) => gapTypeLabel(k, t)),
  };
}

export function findCohort(model: PopulationModel, id: string | null): Cohort | Programme | null {
  if (!id) return null;
  for (const p of model.programmes) {
    if (p.id === id) return p;
    const seg = p.segments.find((s) => s.id === id);
    if (seg) return seg;
  }
  return null;
}

export function isCohortId(id: string | null): id is CohortId {
  if (!id) return false;
  const [pathway, segment] = id.split(":");
  if (!PATHWAY_OPTIONS.some((o) => o.value === pathway)) return false;
  return segment === undefined || (SEGMENT_ORDER as string[]).includes(segment);
}
