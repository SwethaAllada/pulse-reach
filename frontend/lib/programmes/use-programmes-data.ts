"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, isForbidden } from "@/lib/api/client";
import { cached } from "@/lib/api/cache";
import type {
  AgeBand,
  CareGapOut,
  DashboardSummaryOut,
  OpenQuestionOut,
  Pathway,
  PopulationSummaryOut,
  RuleDetailOut,
  RuleSummaryOut,
} from "@/lib/api/types";
import { useAuth } from "@/lib/auth/auth-context";
import { buildPopulationModel, type PopulationModel } from "@/lib/population/model";
import { AGE_BAND_OPTIONS, peopleFiltersToSearchParams, type PeopleFilters } from "@/lib/people/params";

/** A loaded resource; `forbidden` = the backend (or the role's permissions) refuse it. */
export type Resource<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "forbidden"; permission: string }
  | { status: "ready"; data: T };

function message(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/**
 * Runs `load` whenever `key` changes (null = disabled, reported as forbidden).
 * Stale responses are ignored; 403 becomes `forbidden`, never an error banner.
 */
function useResource<T>(
  key: string | null,
  permission: string,
  load: (signal: AbortSignal) => Promise<T>,
  attempt: number
): Resource<T> {
  const requestId = `${attempt}|${key}`;
  const [settled, setSettled] = useState<{ id: string; state: Resource<T> } | null>(null);
  useEffect(() => {
    if (key === null) return;
    const ctrl = new AbortController();
    load(ctrl.signal).then(
      (data) => !ctrl.signal.aborted && setSettled({ id: requestId, state: { status: "ready", data } }),
      (err) => {
        if (ctrl.signal.aborted) return;
        setSettled({
          id: requestId,
          state: isForbidden(err) ? { status: "forbidden", permission } : { status: "error", message: message(err, "Unexpected error.") },
        });
      }
    );
    return () => ctrl.abort();
    // `load` is derived from `key`; re-running on identity changes would refetch every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestId]);
  if (key === null) return { status: "forbidden", permission };
  return settled?.id === requestId ? settled.state : { status: "loading" };
}

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

export function useProgrammesData(filters: ProgrammeFilters, pathway?: Pathway) {
  const { can } = useAuth();
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const filterKey = peopleFiltersToSearchParams({ ...filters, pathway }).toString();

  const summary = useResource<DashboardSummaryOut>(can("insights.read") ? "summary" : null, "insights.read", loadSummary, attempt);
  const rules = useResource<RuleSummaryOut[]>(can("rules.read") ? "rules" : null, "rules.read", loadRules, attempt);
  const openQuestions = useResource<OpenQuestionOut[]>(
    can("rules.read") ? "oq" : null,
    "rules.read",
    loadOpenQuestions,
    attempt
  );
  const careGaps = useResource<CareGapOut[]>(can("care_gaps.read") ? "gaps" : null, "care_gaps.read", loadCareGaps, attempt);

  /** Members: backend-filtered patients joined with rules + gap records into programme segments. */
  const population = useResource<PopulationModel>(
    can("patients.read", "patients.read_assigned") && can("care_gaps.read") && can("rules.read") ? `patients|${filterKey}` : null,
    "patients.read_assigned",
    (signal) =>
      Promise.all([api.allPatients({ ...filters, pathway }, signal), loadCareGaps(), loadRules()]).then(([p, g, r]) =>
        buildPopulationModel(p.items, g, r)
      ),
    attempt
  );

  /** Organization-level surveillance aggregates (managers and clinicians). */
  const surveillance = useResource<PopulationSummaryOut>(
    can("population.read") ? "population-summary" : null,
    "population.read",
    (signal) => api.populationSummary(signal),
    attempt
  );

  return { summary, rules, openQuestions, careGaps, population, surveillance, retry };
}

/** People per backend age band for one programme (plus the share without a recorded date of birth). */
export function useAgeBands(pathway: Pathway, filters: Omit<ProgrammeFilters, "age_band">, attempt = 0) {
  const { can } = useAuth();
  const key = peopleFiltersToSearchParams({ ...filters, pathway }).toString();
  return useResource<{ total: number; bands: { band: AgeBand; label: string; count: number }[] }>(
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
