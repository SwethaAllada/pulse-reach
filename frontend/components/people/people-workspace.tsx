"use client";

import { useCallback, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Info, RotateCcw } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { buttonClass } from "@/components/ui/button-styles";
import { PopulationFilterBar } from "@/components/population/population-filters";
import { scopeLabel, useAuth } from "@/lib/auth/auth-context";
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
import { PeopleCareFilters } from "./people-care-filters";

export function PeopleWorkspace() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { scope, state: auth } = useAuth();
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
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-20 pt-8 sm:px-6 lg:px-8">
      <PageHeader
        index="03"
        eyebrow="Find"
        title="People"
        subtitle="The synthetic people in your scope, with their programme membership, history availability and documented preventive-care gaps."
        breadcrumbs={[{ label: "Population", href: populationHref(state.filters) }, { label: "People" }]}
        actions={
          hasAnyCriteria(state) ? (
            <button
              type="button"
              onClick={() => navigate({ filters: {}, page: 1, id: null, sort: null })}
              className={buttonClass("secondary")}
            >
              <RotateCcw size={14} aria-hidden="true" /> Clear filters
            </button>
          ) : undefined
        }
        className="mb-6"
      />

      <dl aria-label="Result context" className="mb-6 flex flex-wrap items-baseline gap-x-8 gap-y-2 text-sm">
        <div className="flex items-baseline gap-2">
          <dt className="text-faint">Matching people</dt>
          <dd className="figure text-3xl text-foreground" aria-live="polite">
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
        {auth.status === "signed_in" && (
          <div className="flex items-baseline gap-2">
            <dt className="text-faint">Scope</dt>
            <dd className="text-muted">{scopeLabel(scope)}</dd>
          </div>
        )}
      </dl>

      <section aria-label="Search and filters" className="reveal mb-8 border-y border-border py-5">
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
            onChange={(filters) => navigate({ ...state, filters: { ...state.filters, ...filtersOnly(filters) }, page: 1 })}
            emptyText="No programme, region or sex filter."
          />
          <PeopleCareFilters
            filters={state.filters}
            sort={state.sort ?? null}
            onChange={(filters) => navigate({ ...state, filters, page: 1 })}
            onSort={(sort) => navigate({ ...state, sort, page: 1 })}
          />
          <p className="flex gap-2 text-xs leading-relaxed text-faint">
            <Info size={14} aria-hidden="true" className="mt-0.5 shrink-0" />
            <span>
              Every filter is applied by <code className="font-mono">GET /patients</code>. With a programme selected, open-care-gap
              and history filters apply to that programme (otherwise to any programme); age groups are computed by the backend from date of birth at the reference date (people
              without a recorded date of birth are excluded from every age group).
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

/** The population bar reports only programme/region/sex; keep care filters intact, honour removals. */
function filtersOnly(f: PeopleState["filters"]): PeopleState["filters"] {
  return { pathway: f.pathway, region_id: f.region_id, sex: f.sex };
}
