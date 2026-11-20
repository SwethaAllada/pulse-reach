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
import { buttonClass } from "@/components/ui/button-styles";

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
    <div className="pb-20">
      <section aria-labelledby="population-heading" className="mb-14 bg-ink px-4 pb-10 pt-8 sm:px-6 lg:px-8">
        <div className="mx-auto flex max-w-[1200px] flex-col gap-7">
          <header className="reveal">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="flex items-center gap-2.5 text-ink-accent">
                <span className="font-mono text-[11px] text-ink-faint">01</span>
                <Telescope size={14} aria-hidden="true" />
                <span className="text-[11px] font-semibold uppercase tracking-[0.16em]">Population · Identify</span>
              </span>
              {summary.status === "ready" && (
                <span className="text-xs text-ink-faint">
                  Evaluation run {summary.data.evaluation_run_id} · reference date {summary.data.reference_date}
                </span>
              )}
            </div>
            <h1
              id="population-heading"
              className="mt-4 max-w-4xl font-display text-4xl font-normal leading-[1.02] tracking-[-0.03em] text-ink-text sm:text-6xl"
            >
              See the signals. <em className="italic text-ink-accent">Prevent</em> the gaps.
            </h1>
            <p className="mt-4 max-w-2xl text-[15px] leading-relaxed text-ink-muted">
              Explore the synthetic population by programme and documented evidence. Select a cohort in
              the constellation to see its documented care gaps, then follow it into its programme and people.
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
              <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
                <div className="reveal flex min-w-0 flex-col gap-3 rounded-2xl border border-ink-line p-3 sm:p-5" style={{ "--i": 3 } as React.CSSProperties}>
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

      <div className="mx-auto w-full max-w-[1200px] px-4 sm:px-6 lg:px-8">
        {model && model.totalPeople > 0 && (
          <div className="grid grid-cols-1 gap-x-12 gap-y-16 lg:grid-cols-2">
            <GapsByRuleCard model={model} />
            <EvidenceCard model={model} />
            <SegmentationCard model={model} />
            <EvaluationStatusCard summary={summary} />
          </div>
        )}
        {population.status === "error" && (
          <p className="text-sm text-muted">
            Population insights are hidden until the API responds — no values are shown in place of real data.
          </p>
        )}

        <UnavailableCapabilities />
      </div>
    </div>
  );
}

function HeroLoading() {
  return (
    <div aria-busy="true" aria-label="Loading population data" className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="skeleton-ink h-16 rounded-lg" style={{ animationDelay: `${i * 80}ms` }} />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="skeleton-ink aspect-[800/440] w-full rounded-2xl" />
        <div className="skeleton-ink h-64 rounded-2xl lg:h-auto" />
      </div>
      <p className="flex items-center gap-3 text-xs text-ink-faint">
        <span className="progress-track h-0.5 w-16 rounded-full bg-ink-line text-ink-accent" />
        Loading population data from the PulseReach API…
      </p>
    </div>
  );
}

function HeroError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="reveal flex flex-col items-start gap-3 rounded-2xl border border-ink-line p-6">
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
        className={buttonClass("plate")}
      >
        <RotateCcw size={14} aria-hidden="true" /> Retry
      </button>
    </div>
  );
}

function HeroEmpty({ filtered, onClear }: { filtered: boolean; onClear: () => void }) {
  return (
    <div className="reveal flex flex-col items-center gap-3 rounded-2xl border border-dashed border-ink-line px-6 py-12 text-center">
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
          className={buttonClass("plate-primary")}
        >
          Clear all filters
        </button>
      )}
    </div>
  );
}
