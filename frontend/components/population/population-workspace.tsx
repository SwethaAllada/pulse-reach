"use client";

import { useCallback, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, RotateCcw, SearchX, Telescope } from "lucide-react";
import { ConstellationVisualization } from "@/components/constellation/constellation-visualization";
import { CohortLegend } from "@/components/constellation/cohort-legend";
import { filtersToSearchParams, hasActiveFilters, parseFilters, type PopulationFilters } from "@/lib/population/filters";
import { findCohort, isCohortId, type CohortId } from "@/lib/population/model";
import { usePopulationData } from "@/lib/population/use-population-data";
import { PopulationFilterBar } from "./population-filters";
import { PopulationOverview } from "./population-overview";
import { CohortPanel } from "./cohort-panel";
import { EvaluationStatusCard, EvidenceCard, GapsByRuleCard, SegmentationCard } from "./population-insights";
import { UnavailableCapabilities } from "./unavailable-capabilities";

export function PopulationWorkspace() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const filters = useMemo(() => parseFilters(searchParams), [searchParams]);
  const cohortParam = searchParams.get("cohort");
  const selectedId: CohortId | null = isCohortId(cohortParam) ? cohortParam : null;

  const { population, summary, retry } = usePopulationData(filters);

  const navigate = useCallback(
    (nextFilters: PopulationFilters, nextCohort: CohortId | null) => {
      const params = filtersToSearchParams(nextFilters);
      if (nextCohort) params.set("cohort", nextCohort);
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname]
  );

  const model = population.status === "ready" ? population.data : null;
  const selected = model ? findCohort(model, selectedId) : null;
  const populationTotal = summary.status === "ready" ? summary.data.total_patients : null;

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 sm:px-6 lg:px-8">
      <section
        aria-labelledby="population-heading"
        className="-mx-4 mb-10 border-b border-ink-line bg-ink px-4 pb-8 pt-8 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8"
      >
        <div className="mx-auto flex max-w-[1200px] flex-col gap-6">
          <header>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-ink-accent">
              <span className="flex items-center gap-2">
                <Telescope size={15} aria-hidden="true" />
                <span className="text-xs font-semibold uppercase tracking-[0.1em]">Population · Workspace</span>
              </span>
              {summary.status === "ready" && (
                <span className="text-xs text-ink-faint">
                  Evaluation run {summary.data.evaluation_run_id} · reference date {summary.data.reference_date}
                </span>
              )}
            </div>
            <h1
              id="population-heading"
              className="mt-3 font-display text-3xl font-semibold tracking-tight text-ink-text sm:text-4xl"
            >
              See the signals. Prevent the gaps.
            </h1>
            <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-ink-muted">
              Explore the synthetic population by programme and documented evidence. Select a cohort in
              the constellation to see its documented care gaps and open the matching people.
            </p>
          </header>

          <PopulationFilterBar filters={filters} onChange={(next) => navigate(next, selectedId)} />

          {population.status === "loading" && <HeroLoading />}
          {population.status === "error" && <HeroError message={population.message} onRetry={retry} />}
          {model && model.totalPeople === 0 && (
            <HeroEmpty filtered={hasActiveFilters(filters)} onClear={() => navigate({}, null)} />
          )}
          {model && model.totalPeople > 0 && (
            <>
              <PopulationOverview model={model} populationTotal={populationTotal} filters={filters} />
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
                <div className="flex min-w-0 flex-col gap-3 rounded-lg border border-ink-line bg-ink-raised/60 p-3 sm:p-4">
                  <div className="aspect-[800/440] w-full">
                    <ConstellationVisualization
                      model={model}
                      selectedId={selectedId}
                      onSelect={(id) => navigate(filters, id)}
                    />
                  </div>
                  <CohortLegend />
                </div>
                <CohortPanel
                  model={model}
                  selected={selected}
                  filters={filters}
                  onSelect={(id) => navigate(filters, id)}
                />
              </div>
            </>
          )}
        </div>
      </section>

      {model && model.totalPeople > 0 && (
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <GapsByRuleCard model={model} />
            <EvidenceCard model={model} />
          </div>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <SegmentationCard model={model} />
            <EvaluationStatusCard summary={summary} />
          </div>
        </div>
      )}
      {population.status === "error" && (
        <p className="text-sm text-muted">
          Population insights are hidden until the API responds — no values are shown in place of real data.
        </p>
      )}

      <UnavailableCapabilities />
    </div>
  );
}

function HeroLoading() {
  return (
    <div aria-busy="true" aria-label="Loading population data" className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-16 animate-pulse rounded-md bg-ink-raised" style={{ animationDelay: `${i * 80}ms` }} />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="aspect-[800/440] w-full animate-pulse rounded-lg bg-ink-raised" />
        <div className="h-64 animate-pulse rounded-lg bg-ink-raised lg:h-auto" />
      </div>
      <p className="text-xs text-ink-faint">Loading population data from the PulseReach API…</p>
    </div>
  );
}

function HeroError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-lg border border-ink-line bg-ink-raised/60 p-6">
      <span className="flex items-center gap-2 text-sm font-semibold text-ink-text">
        <AlertTriangle size={16} aria-hidden="true" className="text-ink-due" />
        Population data is unavailable
      </span>
      <p className="max-w-xl text-sm text-ink-muted">
        {message} No population figures are shown because none could be loaded.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="inline-flex items-center gap-2 rounded-md border border-ink-line px-3 py-1.5 text-sm font-medium text-ink-text transition-colors hover:border-ink-accent"
      >
        <RotateCcw size={14} aria-hidden="true" /> Retry
      </button>
    </div>
  );
}

function HeroEmpty({ filtered, onClear }: { filtered: boolean; onClear: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-ink-line px-6 py-12 text-center">
      <SearchX size={24} strokeWidth={1.5} aria-hidden="true" className="text-ink-faint" />
      <p className="text-sm font-semibold text-ink-text">No people match these filters</p>
      <p className="max-w-sm text-sm text-ink-muted">
        {filtered
          ? "The patients API returned no synthetic people for this combination."
          : "The patients API returned an empty population."}
      </p>
      {filtered && (
        <button
          type="button"
          onClick={onClear}
          className="rounded-md bg-ink-accent px-3 py-1.5 text-sm font-semibold text-ink transition-opacity hover:opacity-90"
        >
          Clear all filters
        </button>
      )}
    </div>
  );
}
