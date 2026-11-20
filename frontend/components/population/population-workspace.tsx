"use client";

import { useCallback, useMemo, useState } from "react";
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
import { PopulationMap } from "./geo/population-map";
import { CohortComparison } from "./cohort-comparison";
import { Segmented } from "@/components/ui/segmented";
import { buttonClass } from "@/components/ui/button-styles";
import { useAuth } from "@/lib/auth/auth-context";
import { PageHeader } from "@/components/ui/page-header";
import { Plate } from "@/components/ui/plate";
import { useLocale } from "@/lib/i18n/use-locale";

export function PopulationWorkspace() {
  const searchParams = useSearchParams();
  const { scope } = useAuth();
  const { t } = useLocale();
  const [view, setView] = useState<"compare" | "people">("compare");
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

  const panel = scope === "assigned";
  return (
    <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-6 px-4 pb-16 pt-6 sm:px-6 lg:px-8">
      <PageHeader
        title={t(panel ? "nav.panel_insights" : "nav.population_overview")}
        subtitle={t(panel ? "pop.subtitle_panel" : "pop.subtitle_population")}
        meta={
          summary.status === "ready" ? (
            <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="inline-flex items-center gap-1.5">
                <Telescope size={12} aria-hidden="true" /> {t("pop.evaluation_run")}{" "}
                <span className="font-mono ltr-value">{summary.data.evaluation_run_id}</span>
              </span>
              <span>{t("pop.reference_date", { date: summary.data.reference_date })}</span>
            </span>
          ) : undefined
        }
      />

      <section aria-labelledby="population-heading" className="flex flex-col gap-6">
        <h2 id="population-heading" className="sr-only">
          {t("pop.signals")}
        </h2>
        <div className="reveal rounded-xl border border-border bg-surface-raised px-4 py-3.5">
          <PopulationFilterBar filters={filters} onChange={(next) => navigate(next, selectedId)} />
        </div>

        {population.status === "loading" && <HeroLoading />}
        {population.status === "error" && <HeroError message={population.message} onRetry={retry} />}
        {model && model.totalPeople === 0 && (
          <HeroEmpty filtered={hasActiveFilters(filters)} onClear={() => navigate({}, null)} />
        )}
        {model && model.totalPeople > 0 && (
          <>
            <PopulationOverview model={model} populationTotal={populationTotal} filters={filters} />
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
              <Plate
                title={t("pop.cohort_comparison")}
                description={t("pop.cohort_comparison_desc")}
                className="[--i:3]"
                actions={
                  <Segmented
                    label={t("pop.cohort_view")}
                    value={view}
                    onChange={setView}
                    options={[
                      { value: "compare", label: t("pop.view_compare") },
                      { value: "people", label: t("pop.view_people") },
                    ]}
                  />
                }
              >
                {view === "compare" ? (
                  <div key="compare" className="reveal-fade">
                    <CohortComparison model={model} selectedId={selectedId} onSelect={(id) => navigate(filters, id)} />
                  </div>
                ) : (
                  <div key="people" className="reveal-fade">
                    <div className="aspect-[800/400] w-full">
                      <ConstellationVisualization model={model} selectedId={selectedId} onSelect={(id) => navigate(filters, id)} />
                    </div>
                    <div className="mt-3 border-t border-border pt-3">
                      <CohortLegend />
                    </div>
                  </div>
                )}
              </Plate>
              <CohortPanel
                model={model}
                selected={selected}
                filters={filters}
                onSelect={(id) => navigate(filters, id)}
              />
            </div>
          </>
        )}
      </section>

      <PopulationMap />

      {model && model.totalPeople > 0 && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <GapsByRuleCard model={model} />
          <EvidenceCard model={model} />
          <SegmentationCard model={model} />
          <EvaluationStatusCard summary={summary} />
        </div>
      )}
      {population.status === "error" && (
        <p className="text-sm text-muted">
          {t("pop.insights_hidden")}
        </p>
      )}

      <UnavailableCapabilities />
    </div>
  );
}

function HeroLoading() {
  const { t } = useLocale();
  return (
    <div aria-busy="true" aria-label={t("pop.loading")} className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="skeleton h-[88px] rounded-xl" style={{ animationDelay: `${i * 80}ms` }} />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="skeleton aspect-[800/440] w-full rounded-xl" />
        <div className="skeleton h-64 rounded-xl lg:h-auto" />
      </div>
      <p className="flex items-center gap-3 text-xs text-faint">
        <span className="progress-track h-0.5 w-16 rounded-full bg-border text-accent" />
        {t("pop.loading_from_api")}
      </p>
    </div>
  );
}

function HeroError({ message, onRetry }: { message: string; onRetry: () => void }) {
  const { t } = useLocale();
  return (
    <div role="alert" className="reveal flex flex-col items-start gap-3 rounded-xl border border-border bg-surface-raised p-6">
      <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <AlertTriangle size={16} aria-hidden="true" className="text-status-error" />
        {t("pop.unavailable_title")}
      </span>
      <p className="max-w-xl text-sm text-muted">{t("pop.unavailable_body", { message })}</p>
      <button
        type="button"
        onClick={onRetry}
        className={buttonClass("secondary")}
      >
        <RotateCcw size={14} aria-hidden="true" /> {t("access.retry")}
      </button>
    </div>
  );
}

function HeroEmpty({ filtered, onClear }: { filtered: boolean; onClear: () => void }) {
  const { t } = useLocale();
  return (
    <div className="reveal flex flex-col items-center gap-3 rounded-xl border border-dashed border-border-strong bg-surface-raised px-6 py-12 text-center">
      <SearchX size={24} strokeWidth={1.5} aria-hidden="true" className="text-faint" />
      <p className="text-sm font-semibold text-foreground">{t("pop.empty_title")}</p>
      <p className="max-w-sm text-sm text-muted">{t(filtered ? "pop.empty_filtered" : "pop.empty_all")}</p>
      {filtered && (
        <button
          type="button"
          onClick={onClear}
          className={buttonClass("primary")}
        >
          {t("pop.clear_all_filters")}
        </button>
      )}
    </div>
  );
}
