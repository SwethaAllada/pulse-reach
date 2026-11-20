"use client";

import { useCallback, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api/client";
import { useResource, type Resource } from "@/lib/api/resource";
import { cached } from "@/lib/api/cache";
import type {
  AgeBand,
  CareGapOut,
  DashboardSummaryOut,
  OpenQuestionOut,
  Pathway,
  PopulationSummaryOut,
  ProgrammeSummaryOut,
  RuleDetailOut,
  RuleSummaryOut,
} from "@/lib/api/types";
import { useAuth } from "@/lib/auth/auth-context";
import { useLocale } from "@/lib/i18n/use-locale";
import type { MessageKey } from "@/lib/i18n/translate";
import { buildPopulationModel, type PopulationModel } from "@/lib/population/model";
import { AGE_BAND_OPTIONS, peopleFiltersToSearchParams, type PeopleFilters } from "@/lib/people/params";

export type { Resource } from "@/lib/api/resource";

/* Reference data: shared across views for the session (cleared on sign-in/out). */
const loadRules = () => cached("rules", () => api.rules().then((r) => r.items));
const loadOpenQuestions = () => cached("open-questions", () => api.openQuestions().then((r) => r.items));
const loadCareGaps = () => cached("care-gaps", () => api.allCareGaps().then((r) => r.items));
const loadSummary = () => cached("dashboard-summary", () => api.dashboardSummary());

export interface ProgrammeReference {
  rules: RuleSummaryOut[];
  careGaps: CareGapOut[];
}

/** Programme explorer filters: the `GET /patients` filters that keep a programme's meaning intact. */
export type ProgrammeFilters = Pick<PeopleFilters, "region_id" | "sex" | "age_band">;

/** Dashboard summary, rules, open questions and organization surveillance — shared by every programme view. */
function useProgrammeReference(attempt: number) {
  const { can } = useAuth();
  const summary = useResource<DashboardSummaryOut>(can("insights.read") ? "summary" : null, "insights.read", loadSummary, attempt);
  const rules = useResource<RuleSummaryOut[]>(can("rules.read") ? "rules" : null, "rules.read", loadRules, attempt);
  const openQuestions = useResource<OpenQuestionOut[]>(
    can("rules.read") ? "oq" : null,
    "rules.read",
    loadOpenQuestions,
    attempt
  );
  /** Organization-level surveillance aggregates (managers and clinicians). */
  const surveillance = useResource<PopulationSummaryOut>(
    can("population.read") ? "population-summary" : null,
    "population.read",
    (signal) => api.populationSummary(signal),
    attempt
  );
  return { summary, rules, openQuestions, surveillance };
}

/**
 * Server-side programme aggregates (`GET /programmes/{pathway}/summary`) for the role's patient
 * scope and the filters. An API without the endpoint is reported as such, never approximated.
 */
function useProgrammeSummary(pathway: Pathway, filters: ProgrammeFilters, attempt: number): Resource<ProgrammeSummaryOut> {
  const { can } = useAuth();
  const query = { region_id: filters.region_id, sex: filters.sex, age_band: filters.age_band };
  const key = peopleFiltersToSearchParams({ ...query, pathway }).toString();
  return useResource<ProgrammeSummaryOut>(
    can("insights.read") && can("care_gaps.read") ? `programme-summary|${key}` : null,
    "insights.read and care_gaps.read",
    (signal) =>
      api.programmeSummary(pathway, query, signal).catch((err) => {
        if (err instanceof ApiError && err.status === 404)
          throw new ApiError(
            "This API version has no programme summary (GET /programmes/{pathway}/summary), so programme figures are not shown.",
            404,
            err.path
          );
        throw err;
      }),
    attempt
  );
}

/** Programmes overview: reference data plus one server-side summary per programme — no patient or gap pages. */
export function useProgrammesOverviewData(filters: ProgrammeFilters) {
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const reference = useProgrammeReference(attempt);
  const ifhas = useProgrammeSummary("ifhas", filters, attempt);
  const wellChild = useProgrammeSummary("well_child", filters, attempt);
  const summaries: Record<Pathway, Resource<ProgrammeSummaryOut>> = { ifhas, well_child: wellChild };
  return { ...reference, summaries, retry };
}

export function useProgrammesData(filters: ProgrammeFilters, pathway: Pathway) {
  const { can } = useAuth();
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const filterKey = peopleFiltersToSearchParams({ ...filters, pathway }).toString();

  const { summary, rules, openQuestions, surveillance } = useProgrammeReference(attempt);
  const programmeSummary = useProgrammeSummary(pathway, filters, attempt);
  const careGaps = useResource<CareGapOut[]>(can("care_gaps.read") ? "gaps" : null, "care_gaps.read", loadCareGaps, attempt);

  /** Members: backend-filtered patients joined with rules + gap records into programme segments. */
  const raw = useResource(
    can("patients.read", "patients.read_assigned") && can("care_gaps.read") && can("rules.read") ? `patients|${filterKey}` : null,
    "patients.read_assigned",
    (signal) => Promise.all([api.allPatients({ ...filters, pathway }, signal), loadCareGaps(), loadRules()]),
    attempt,
    false
  );
  // Labels are rebuilt for a language switch without refetching every patient page.
  const { t } = useLocale();
  const population = useMemo<Resource<PopulationModel>>(
    () => (raw.status === "ready" ? { status: "ready", data: buildPopulationModel(raw.data[0].items, raw.data[1], raw.data[2], t) } : raw),
    [raw, t]
  );

  return { summary, rules, openQuestions, careGaps, population, surveillance, programmeSummary, retry };
}

/** People per backend age band for one programme (plus the share without a recorded date of birth). */
export function useAgeBands(pathway: Pathway, filters: Omit<ProgrammeFilters, "age_band">, attempt = 0) {
  const { can } = useAuth();
  const key = peopleFiltersToSearchParams({ ...filters, pathway }).toString();
  return useResource<{ total: number; bands: { band: AgeBand; label: MessageKey; count: number }[] }>(
    can("patients.read", "patients.read_assigned") ? `age|${key}` : null,
    "patients.read_assigned",
    (signal) =>
      Promise.all([
        api.patientsTotal({ ...filters, pathway }, signal),
        ...AGE_BAND_OPTIONS.map((o) => api.patientsTotal({ ...filters, pathway, age_band: o.value }, signal)),
      ]).then(([total, ...counts]) => ({
        total,
        bands: AGE_BAND_OPTIONS.map((o, i) => ({ band: o.value, label: o.label, count: counts[i] })),
      })),
    attempt
  );
}

/** Backend total for a People drill-down query — used to disclose filter-semantics differences. */
export function usePeopleTotal(filters: PeopleFilters | null) {
  const { can } = useAuth();
  const key = filters ? peopleFiltersToSearchParams(filters).toString() : null;
  return useResource<number>(
    key !== null && can("patients.read", "patients.read_assigned") ? `total|${key}` : null,
    "patients.read_assigned",
    (signal) => api.patientsTotal(filters!, signal),
    0
  );
}

export interface RuleView {
  detail: RuleDetailOut;
  gaps: CareGapOut[];
}

/** One rule: definition (`/rules/{id}`) + its care-gap records (`/care-gaps?rule_id=`). */
export function useRuleView(ruleId: string) {
  const { can } = useAuth();
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const detail = useResource<RuleDetailOut>(
    can("rules.read") ? `rule|${ruleId}` : null,
    "rules.read",
    () => cached(`rule:${ruleId}`, () => api.ruleDetail(ruleId)),
    attempt
  );
  const gaps = useResource<CareGapOut[]>(
    can("care_gaps.read") ? `rule-gaps|${ruleId}` : null,
    "care_gaps.read",
    (signal) => api.allCareGaps(signal, { rule_id: ruleId }).then((r) => r.items),
    attempt
  );
  const openQuestions = useResource<OpenQuestionOut[]>(can("rules.read") ? "oq" : null, "rules.read", loadOpenQuestions, attempt);
  return { detail, gaps, openQuestions, retry };
}
