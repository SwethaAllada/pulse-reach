"use client";

import { useCallback, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Info, RotateCcw } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { PopulationFilterBar } from "@/components/population/population-filters";
import {
  activeFilterCount,
  hasAnyCriteria,
  parsePeopleState,
  peopleStateToSearchParams,
  populationHref,
  type PeopleState,
} from "@/lib/people/params";
import { usePeopleList } from "@/lib/people/use-people-data";
import { PeopleIdSearch } from "./people-id-search";
import { PeopleResults } from "./people-results";

export function PeopleWorkspace() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const state = useMemo(() => parsePeopleState(searchParams), [searchParams]);
  const { page, reference, retry } = usePeopleList(state);

  const navigate = useCallback(
    (next: PeopleState) => {
      const qs = peopleStateToSearchParams(next).toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname]
  );

  const active = activeFilterCount(state);
  const data = page.status === "ready" ? page.data : null;
  const ref = reference.status === "ready" ? reference.data : null;

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-8">
      <PageHeader
        eyebrow="Find"
        title="People"
        subtitle="The synthetic people represented in the population dataset, with their programme membership, history availability and documented preventive-care gaps."
        breadcrumbs={[{ label: "Population", href: populationHref(state.filters) }, { label: "People" }]}
        actions={
          hasAnyCriteria(state) ? (
            <button
              type="button"
              onClick={() => navigate({ filters: {}, page: 1, id: null })}
              className="inline-flex items-center gap-1.5 rounded-md border border-border-strong px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:border-accent"
            >
              <RotateCcw size={14} aria-hidden="true" /> Clear filters
            </button>
          ) : undefined
        }
        className="mb-6"
      />

      <dl aria-label="Result context" className="mb-6 flex flex-wrap gap-x-6 gap-y-2 text-sm">
        <div className="flex items-baseline gap-2">
          <dt className="text-faint">Matching people</dt>
          <dd className="font-display text-lg font-semibold tabular-nums text-foreground" aria-live="polite">
            {data ? data.total : "…"}
          </dd>
        </div>
        <div className="flex items-baseline gap-2">
          <dt className="text-faint">Active filters</dt>
          <dd className="font-semibold tabular-nums text-foreground">{active}</dd>
        </div>
        {ref && (
          <div className="flex items-baseline gap-2">
            <dt className="text-faint">Evaluation run</dt>
            <dd className="text-muted">
              {ref.evaluationRunId} · reference date {ref.referenceDate}
            </dd>
          </div>
        )}
      </dl>

      <section aria-label="Search and filters" className="mb-6 rounded-lg border border-border bg-surface p-4 shadow-[var(--shadow-card)] sm:p-5">
        <div className="flex flex-col gap-5">
          <PeopleIdSearch
            value={state.id}
            busy={page.status === "loading"}
            onSearch={(id) => navigate({ ...state, id, page: 1 })}
          />
          <PopulationFilterBar
            tone="paper"
            label="People filters"
            filters={state.filters}
            onChange={(filters) => navigate({ ...state, filters, page: 1 })}
            emptyText="No filters — showing every synthetic person."
          />
          <p className="flex gap-2 text-xs leading-relaxed text-faint">
            <Info size={14} aria-hidden="true" className="mt-0.5 shrink-0" />
            <span>
              Filters by age group, care-gap status, history availability and evaluation status are not offered:
              <code className="mx-1 font-mono">GET /patients</code>does not support them yet (backend task T-06). Sorting is
              not supported either; people are listed in API order.
            </span>
          </p>
        </div>
      </section>

      <PeopleResults
        state={state}
        page={page}
        reference={reference}
        onRetry={retry}
        onNavigate={navigate}
      />
    </div>
  );
}
