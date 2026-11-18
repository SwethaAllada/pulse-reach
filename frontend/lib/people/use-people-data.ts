"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api/client";
import type {
  ExplanationOut,
  PatientEvaluationsOut,
  PatientSummaryOut,
  RuleDetailOut,
  RuleSummaryOut,
} from "@/lib/api/types";
import type { LoadState } from "@/lib/population/use-population-data";
import type { PopulationFilters } from "@/lib/population/filters";
import { PAGE_SIZE, parsePeopleState, peopleStateToSearchParams, type PeopleState } from "./params";
import { openGapCountByPatient } from "./person";

interface Settled<T> {
  requestId: string;
  state: LoadState<T>;
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/** Same semantics as `GET /patients` filters (`pathway` = has a history record for it). */
export function matchesFilters(p: PatientSummaryOut, f: PopulationFilters): boolean {
  return (
    (!f.pathway || p.history_by_pathway[f.pathway] !== undefined) &&
    (!f.region_id || p.region_id === f.region_id) &&
    (!f.sex || p.sex === f.sex)
  );
}

export interface PeoplePage {
  mode: "list" | "id";
  total: number;
  rows: PatientSummaryOut[];
  /** ID lookups: the person exists but is excluded by the active filters. */
  excludedByFilters: PatientSummaryOut | null;
}

export interface PeopleReference {
  referenceDate: string;
  evaluationRunId: string;
  openGaps: Map<string, number>;
}

/**
 * One backend page of people (or an exact-ID lookup), plus reference data
 * fetched once: the evaluation reference date (for ages) and every care-gap
 * page (for per-person open-gap counts).
 */
export function usePeopleList(state: PeopleState) {
  const key = peopleStateToSearchParams(state).toString();
  const [attempt, setAttempt] = useState(0);
  const requestId = `${attempt}|${key}`;
  const [page, setPage] = useState<Settled<PeoplePage> | null>(null);
  const [reference, setReference] = useState<Settled<PeopleReference> | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    const { filters, id, page: pageNo } = parsePeopleState(new URLSearchParams(key));
    const load: Promise<PeoplePage> = id
      ? api.patient(id, ctrl.signal).then(
          (p) =>
            matchesFilters(p, filters)
              ? { mode: "id", total: 1, rows: [p], excludedByFilters: null }
              : { mode: "id", total: 0, rows: [], excludedByFilters: p },
          (err) => {
            if (err instanceof ApiError && err.status === 404)
              return { mode: "id", total: 0, rows: [], excludedByFilters: null };
            throw err;
          }
        )
      : api
          .patientsPage({ ...filters, limit: PAGE_SIZE, offset: (pageNo - 1) * PAGE_SIZE }, ctrl.signal)
          .then((r) => ({ mode: "list", total: r.total, rows: r.items, excludedByFilters: null }));
    load
      .then((data) => setPage({ requestId, state: { status: "ready", data } }))
      .catch((err) => {
        if (!ctrl.signal.aborted)
          setPage({ requestId, state: { status: "error", message: errorMessage(err, "Unexpected error while loading people.") } });
      });
    return () => ctrl.abort();
  }, [key, requestId]);

  useEffect(() => {
    const ctrl = new AbortController();
    const id = String(attempt);
    Promise.all([api.dashboardSummary(ctrl.signal), api.allCareGaps(ctrl.signal)])
      .then(([summary, gaps]) =>
        setReference({
          requestId: id,
          state: {
            status: "ready",
            data: {
              referenceDate: summary.reference_date,
              evaluationRunId: summary.evaluation_run_id,
              openGaps: openGapCountByPatient(gaps.items),
            },
          },
        })
      )
      .catch((err) => {
        if (!ctrl.signal.aborted)
          setReference({ requestId: id, state: { status: "error", message: errorMessage(err, "Reference data unavailable.") } });
      });
    return () => ctrl.abort();
  }, [attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return {
    page: page?.requestId === requestId ? page.state : ({ status: "loading" } as LoadState<PeoplePage>),
    reference:
      reference?.requestId === String(attempt) ? reference.state : ({ status: "loading" } as LoadState<PeopleReference>),
    retry,
  };
}

export interface PersonProfileData {
  patient: PatientSummaryOut;
  evaluations: PatientEvaluationsOut;
  rules: Map<string, RuleSummaryOut>;
}

export type ProfileState = LoadState<PersonProfileData> | { status: "not_found"; id: string };

export function usePersonProfile(personId: string) {
  const [attempt, setAttempt] = useState(0);
  const requestId = `${attempt}|${personId}`;
  const [settled, setSettled] = useState<{ requestId: string; state: ProfileState } | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    Promise.all([
      api.patient(personId, ctrl.signal),
      api.patientEvaluations(personId, ctrl.signal),
      api.rules(ctrl.signal),
    ])
      .then(([patient, evaluations, rules]) =>
        setSettled({
          requestId,
          state: {
            status: "ready",
            data: { patient, evaluations, rules: new Map(rules.items.map((r) => [r.rule_id, r])) },
          },
        })
      )
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.status === 404 && err.path.startsWith("/patients/"))
          return setSettled({ requestId, state: { status: "not_found", id: personId } });
        setSettled({
          requestId,
          state: { status: "error", message: errorMessage(err, "Unexpected error while loading this profile.") },
        });
      });
    return () => ctrl.abort();
  }, [personId, requestId]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const state: ProfileState = settled?.requestId === requestId ? settled.state : { status: "loading" };
  return { state, retry };
}

/* Rule definitions are immutable for a run, so detail requests are shared per session. */
const ruleDetailCache = new Map<string, Promise<RuleDetailOut>>();

export function clearRuleDetailCache() {
  ruleDetailCache.clear();
}

/** Loads `GET /rules/{id}` only while `enabled` (e.g. when a trace is expanded). */
export function useRuleDetail(ruleId: string, enabled: boolean) {
  const [attempt, setAttempt] = useState(0);
  const requestId = `${attempt}|${ruleId}`;
  const [settled, setSettled] = useState<Settled<RuleDetailOut> | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let live = true;
    let p = ruleDetailCache.get(ruleId);
    if (!p) {
      p = api.ruleDetail(ruleId);
      ruleDetailCache.set(ruleId, p);
      p.catch(() => ruleDetailCache.delete(ruleId));
    }
    p.then(
      (data) => live && setSettled({ requestId, state: { status: "ready", data } }),
      (err) =>
        live &&
        setSettled({ requestId, state: { status: "error", message: errorMessage(err, "Rule definition unavailable.") } })
    );
    return () => {
      live = false;
    };
  }, [enabled, ruleId, requestId]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  const state: LoadState<RuleDetailOut> | null = !enabled
    ? null
    : settled?.requestId === requestId
      ? settled.state
      : { status: "loading" };
  return { state, retry };
}

/** `POST /explanations`, requested explicitly by the user. */
export function useExplanation(patientId: string, ruleId: string) {
  const [state, setState] = useState<LoadState<ExplanationOut> | null>(null);
  const request = useCallback(() => {
    setState({ status: "loading" });
    api.explanation(patientId, ruleId).then(
      (data) => setState({ status: "ready", data }),
      (err) =>
        setState({
          status: "error",
          message:
            err instanceof ApiError && err.status === 404
              ? "No evaluation was found for this rule and person."
              : errorMessage(err, "Explanation unavailable."),
        })
    );
  }, [patientId, ruleId]);
  return { state, request };
}
