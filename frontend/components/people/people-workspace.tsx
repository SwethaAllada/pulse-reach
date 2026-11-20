"use client";

import { homeCrumb } from "@/components/shell/nav-items";
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
import { useLocale } from "@/lib/i18n/use-locale";

export function PeopleWorkspace() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { scope, state: auth, role } = useAuth();
  const { t: tr, rich: richT } = useLocale();
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
    <div className="mx-auto w-full max-w-[1280px] px-4 pb-20 pt-8 sm:px-6 lg:px-8">
      <PageHeader
        index="03"
        eyebrow={tr("people.ws.eyebrow")}
        title={tr("nav.people")}
        subtitle={tr("people.ws.subtitle")}
        breadcrumbs={[homeCrumb(role, tr, populationHref(state.filters)), { label: tr("nav.people") }]}
        actions={
          hasAnyCriteria(state) ? (
            <button
              type="button"
              onClick={() => navigate({ filters: {}, page: 1, id: null, sort: null })}
              className={buttonClass("secondary")}
            >
              <RotateCcw size={14} aria-hidden="true" /> {tr("people.ws.clear")}
            </button>
          ) : undefined
        }
        className="mb-6"
      />

      <dl aria-label={tr("people.ws.context")} className="mb-6 flex flex-wrap items-baseline gap-x-8 gap-y-2 text-sm">
        <div className="flex items-baseline gap-2">
          <dt className="text-faint">{tr("people.ws.matching")}</dt>
          <dd className="figure text-3xl text-foreground" aria-live="polite">
            {data ? data.total : "…"}
          </dd>
        </div>
        <div className="flex items-baseline gap-2">
          <dt className="text-faint">{tr("people.ws.active")}</dt>
          <dd className="font-semibold tabular-nums text-foreground">{active}</dd>
        </div>
        {ref && (
          <div className="flex items-baseline gap-2">
            <dt className="text-faint">{tr("pop.evaluation_run")}</dt>
            <dd className="text-muted">
              <span className="ltr-value">{ref.evaluationRunId}</span> · {tr("pop.reference_date", { date: ref.referenceDate })}
            </dd>
          </div>
        )}
        {auth.status === "signed_in" && (
          <div className="flex items-baseline gap-2">
            <dt className="text-faint">{tr("people.ws.scope")}</dt>
            <dd className="text-muted">{scopeLabel(scope, tr)}</dd>
          </div>
        )}
      </dl>

      <section aria-label={tr("people.ws.search")} className="reveal mb-8 border-y border-border py-5">
        <div className="flex flex-col gap-5">
          <PeopleIdSearch
            value={state.id}
            busy={page.status === "loading"}
            onSearch={(id) => navigate({ ...state, id, page: 1 })}
          />
          <PopulationFilterBar
            tone="paper"
            label={tr("people.ws.filters")}
            filters={state.filters}
            onChange={(filters) => navigate({ ...state, filters: { ...state.filters, ...filtersOnly(filters) }, page: 1 })}
            emptyText={tr("people.ws.filters_empty")}
          />
          <PeopleCareFilters
            filters={state.filters}
            sort={state.sort ?? null}
            onChange={(filters) => navigate({ ...state, filters, page: 1 })}
            onSort={(sort) => navigate({ ...state, sort, page: 1 })}
          />
          <p className="flex gap-2 text-xs leading-relaxed text-faint">
            <Info size={14} aria-hidden="true" className="mt-0.5 shrink-0" />
            <span>{richT("people.ws.note", { endpoint: <code className="font-mono">GET /patients</code> })}</span>
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
