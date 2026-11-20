"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api/client";
import type { CareGapOut, DashboardSummaryOut, RuleSummaryOut } from "@/lib/api/types";
import { filterKey, type PopulationFilters } from "./filters";
import { buildPopulationModel, type PopulationModel } from "./model";
import type { PatientSummaryOut } from "@/lib/api/types";
import { t as activeT } from "@/lib/i18n/translate";
import { useLocale } from "@/lib/i18n/use-locale";

export type LoadState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };

interface Settled<T> {
  requestId: string;
  state: LoadState<T>;
}

interface Reference {
  rules: RuleSummaryOut[];
  careGaps: CareGapOut[];
}

function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : activeT("pop.error_unexpected");
}

/**
 * Loads the population roll-up. Patients are re-fetched (backend-filtered) on
 * every filter change; rules and care gaps are unfiltered reference data and
 * are fetched once per mount. Failures surface as errors — never fallbacks.
 */
export function usePopulationData(filters: PopulationFilters) {
  const key = filterKey(filters);
  const [attempt, setAttempt] = useState(0);
  const requestId = `${attempt}|${key}`;
  const reference = useRef<Promise<Reference> | null>(null);

  const { t } = useLocale();
  /* Raw API records; the model (with its localized labels) is rebuilt when the language changes. */
  const [population, setPopulation] = useState<Settled<{ patients: PatientSummaryOut[]; ref: Reference }> | null>(null);
  const [summary, setSummary] = useState<Settled<DashboardSummaryOut> | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    if (!reference.current) {
      reference.current = Promise.all([api.rules(), api.allCareGaps()]).then(([rules, gaps]) => ({
        rules: rules.items,
        careGaps: gaps.items,
      }));
      reference.current.catch(() => {
        reference.current = null;
      });
    }
    const query: PopulationFilters = Object.fromEntries(new URLSearchParams(key)) as PopulationFilters;
    Promise.all([reference.current, api.allPatients(query, ctrl.signal)])
      .then(([ref, patients]) => {
        setPopulation({
          requestId,
          state: { status: "ready", data: { patients: patients.items, ref } },
        });
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setPopulation({ requestId, state: { status: "error", message: errorMessage(err) } });
      });
    return () => ctrl.abort();
  }, [key, requestId]);

  useEffect(() => {
    const ctrl = new AbortController();
    const id = String(attempt);
    api
      .dashboardSummary(ctrl.signal)
      .then((data) => setSummary({ requestId: id, state: { status: "ready", data } }))
      .catch((err) => {
        if (!ctrl.signal.aborted)
          setSummary({ requestId: id, state: { status: "error", message: errorMessage(err) } });
      });
    return () => ctrl.abort();
  }, [attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  const raw = population?.requestId === requestId ? population.state : null;
  const model = useMemo(
    () => (raw?.status === "ready" ? buildPopulationModel(raw.data.patients, raw.data.ref.careGaps, raw.data.ref.rules, t) : null),
    [raw, t]
  );
  const populationState: LoadState<PopulationModel> = model
    ? { status: "ready", data: model }
    : raw?.status === "error"
      ? raw
      : { status: "loading" };
  const summaryState: LoadState<DashboardSummaryOut> =
    summary?.requestId === String(attempt) ? summary.state : { status: "loading" };

  return { population: populationState, summary: summaryState, retry };
}
