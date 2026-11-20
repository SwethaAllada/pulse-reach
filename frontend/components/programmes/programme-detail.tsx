"use client";

import { useCallback, useMemo, ViewTransition } from "react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, ArrowRight, ChevronRight, Info } from "lucide-react";
import type { CareGapStatus, Pathway } from "@/lib/api/types";
import { scopeLabel, useAuth } from "@/lib/auth/auth-context";
import { AGE_BAND_OPTIONS, parsePeopleFilters, peopleFiltersHref, peopleFiltersToSearchParams } from "@/lib/people/params";
import { SEGMENT_META, SEGMENT_ORDER, type Programme, type SegmentId } from "@/lib/population/model";
import {
  buildProgrammeModel,
  PROGRAMME_META,
  pathwayFromSlug,
  segmentPeopleFilters,
  type ProgrammeModel,
  type RuleStanding,
} from "@/lib/programmes/model";
import { useProgrammesData, usePeopleTotal, type ProgrammeFilters } from "@/lib/programmes/use-programmes-data";
import { PopulationFilterBar, filterLabelClass, selectClass } from "@/components/population/population-filters";
import { SegmentGlyph } from "@/components/population/segment-glyph";
import { buttonClass } from "@/components/ui/button-styles";
import { BACK } from "@/components/ui/page-transition";
import { Figure, KpiCard } from "@/components/ui/figure";
import { MemberLattice } from "./composition";
import { InlineError } from "./resource-state";
import { ProgrammeSections } from "./programme-sections";
import { cn } from "@/lib/cn";
import { homeCrumb } from "@/components/shell/nav-items";

export interface DetailState {
  filters: ProgrammeFilters;
  segment: SegmentId | null;
  metric: CareGapStatus;
  standing: RuleStanding | null;
}

const METRICS: CareGapStatus[] = ["open", "closed_completed", "closed_refused"];
const STANDINGS: RuleStanding[] = ["authoritative", "review", "unresolved"];

function parseDetail(params: URLSearchParams): DetailState {
  const f = parsePeopleFilters(params);
  const seg = params.get("segment");
  const metric = params.get("gaps");
  const standing = params.get("standing");
  return {
    filters: { region_id: f.region_id, sex: f.sex, age_band: f.age_band },
    segment: (SEGMENT_ORDER as string[]).includes(seg ?? "") ? (seg as SegmentId) : null,
    metric: (METRICS as string[]).includes(metric ?? "") ? (metric as CareGapStatus) : "open",
    standing: (STANDINGS as string[]).includes(standing ?? "") ? (standing as RuleStanding) : null,
  };
}

function detailToParams(s: DetailState): URLSearchParams {
  const p = peopleFiltersToSearchParams(s.filters);
  if (s.segment) p.set("segment", s.segment);
  if (s.metric !== "open") p.set("gaps", s.metric);
  if (s.standing) p.set("standing", s.standing);
  return p;
}

export function ProgrammeDetail() {
  const params = useParams<{ programme: string }>();
  const pathway = pathwayFromSlug(params.programme ?? "");
  if (!pathway) return <UnknownProgramme slug={params.programme ?? ""} />;
  return <ProgrammeDetailBody pathway={pathway} />;
}

function UnknownProgramme({ slug }: { slug: string }) {
  return (
    <div className="mx-auto w-full max-w-[1280px] px-4 py-16 sm:px-6 lg:px-8">
      <p className="text-xs font-medium text-faint">Programmes</p>
      <h1 className="mt-3 font-display text-[28px] font-medium text-foreground">No programme “{slug}”</h1>
      <p className="mt-3 text-sm text-muted">PulseReach evaluates IFHAS adult screening and Well-Child visits.</p>
      <Link href="/programmes" className={buttonClass("secondary", "mt-6")}>
        <ArrowLeft size={14} aria-hidden="true" /> All programmes
      </Link>
    </div>
  );
}

function ProgrammeDetailBody({ pathway }: { pathway: Pathway }) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { scope, state: auth } = useAuth();
  const state = useMemo(() => parseDetail(new URLSearchParams(searchParams.toString())), [searchParams]);
  const data = useProgrammesData(state.filters, pathway);
  const { summary, rules, openQuestions, careGaps, population, retry } = data;
  const meta = PROGRAMME_META[pathway];

  const navigate = useCallback(
    (patch: Partial<DetailState>) => {
      const qs = detailToParams({ ...state, ...patch }).toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname, state]
  );

  const programme: Programme | null =
    population.status === "ready" ? population.data.programmes.find((p) => p.pathway === pathway) ?? null : null;
  const filtered = !!(state.filters.region_id || state.filters.sex || state.filters.age_band);
  const model: ProgrammeModel | null = useMemo(() => {
    if (rules.status !== "ready") return null;
    const ids = filtered && population.status === "ready" ? new Set(population.data.patientIds) : null;
    return buildProgrammeModel(
      pathway,
      rules.data,
      careGaps.status === "ready" ? careGaps.data : [],
      openQuestions.status === "ready" ? openQuestions.data : [],
      ids
    );
  }, [rules, careGaps, openQuestions, population, pathway, filtered]);

  const segment = state.segment ? programme?.segments.find((s) => s.segment === state.segment) ?? null : null;
  /* Gap figures are shown only when the records (and, if filtered, the member set) are loaded — never as 0. */
  const gapsKnown = careGaps.status === "ready" && (!filtered || population.status === "ready");
  const gapValue = (v: number | undefined) =>
    gapsKnown && v !== undefined ? v : careGaps.status === "loading" || population.status === "loading" ? <HeroDash /> : "—";
  const memberValue = (v: number | undefined) =>
    v !== undefined ? v : population.status === "loading" ? <HeroDash /> : "—";
  const sum = summary.status === "ready" ? summary.data : null;
  const home = homeCrumb(auth.status === "signed_in" ? auth.me.role : null);
  const overviewQs = peopleFiltersToSearchParams({ region_id: state.filters.region_id, sex: state.filters.sex }).toString();

  return (
    <div className="mx-auto w-full max-w-[1280px] px-4 pb-16 pt-6 sm:px-6 lg:px-8">
      <section aria-labelledby="programme-heading">
        <div className="flex flex-col gap-6">
          <header className="reveal">
            <nav aria-label="Breadcrumb" className="mb-3">
              <ol className="flex flex-wrap items-center gap-1.5 text-xs text-ink-faint">
                <li>
                  <Link href={home.href} className="hover:text-ink-text">
                    {home.label}
                  </Link>
                </li>
                <li aria-hidden="true"><ChevronRight size={12} /></li>
                <li>
                  <Link href={overviewQs ? `/programmes?${overviewQs}` : "/programmes"} transitionTypes={BACK} className="hover:text-ink-text">
                    Programmes
                  </Link>
                </li>
                <li aria-hidden="true"><ChevronRight size={12} /></li>
                <li aria-current="page" className="text-ink-muted">
                  {meta.name}
                </li>
              </ol>
            </nav>
            <div className="flex flex-wrap items-end justify-between gap-6">
              <div className="max-w-3xl">
                <p className="text-xs font-medium text-ink-faint">Programme · {meta.audience}</p>
                <ViewTransition name={`programme-title-${pathway}`} share="atlas-morph" default="none">
                  <h1
                    id="programme-heading"
                    className="mt-1 font-display text-[28px] font-medium leading-tight tracking-[-0.015em] text-ink-text"
                  >
                    {meta.name}
                  </h1>
                </ViewTransition>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">
                  {model?.source ? (
                    <>
                      Rules transcribed from <span className="text-ink-text">{model.source.name}</span> ({model.source.version}).
                    </>
                  ) : (
                    meta.full
                  )}
                </p>
                <p className="mt-2 text-xs text-ink-faint">
                  {[
                    sum && `Evaluation run ${sum.evaluation_run_id} · reference date ${sum.reference_date}`,
                    auth.status === "signed_in" && `Scope: ${scopeLabel(scope)}`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
            </div>
          </header>

          <div className="reveal rounded-xl border border-border bg-surface-raised px-4 py-3.5" style={{ "--i": 1 } as React.CSSProperties}>
            <PopulationFilterBar
              tone="paper"
              hideProgramme
              label={`${meta.name} filters`}
              filters={{ ...state.filters, pathway }}
              onChange={(f) => navigate({ filters: { ...state.filters, region_id: f.region_id, sex: f.sex }, segment: state.segment })}
              emptyText={`Every ${meta.name} member in your scope.`}
            >
              <label className={`${filterLabelClass("paper")} lg:w-40`}>
                Age group
                <select
                  className={selectClass("paper")}
                  value={state.filters.age_band ?? ""}
                  onChange={(e) =>
                    navigate({ filters: { ...state.filters, age_band: (e.target.value || undefined) as ProgrammeFilters["age_band"] } })
                  }
                >
                  <option value="">All ages</option>
                  {AGE_BAND_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
            </PopulationFilterBar>
            {state.filters.age_band && (
              <p className="mt-1 text-xs text-ink-faint">
                Age groups are computed by the backend from date of birth; members without one are excluded.
              </p>
            )}
          </div>

          {rules.status === "error" && <InlineError tone="plate" message={`Programme rules are unavailable. ${rules.message}`} onRetry={retry} />}

          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <KpiCard label="Members" value={memberValue(programme?.people)} note={`${meta.unit} with a history record`} i={2} />
            <KpiCard label="With an open gap" value={gapValue(model?.peopleWithOpenGap)} note="people" i={3} />
            <KpiCard label="Open gap records" value={gapValue(model?.gaps.open)} note="across this programme’s rules" i={4} />
            <KpiCard label="Completions" value={gapValue(model?.gaps.closed_completed)} note="gap records closed by documentation" i={5} />
            <KpiCard
              label="History unavailable"
              value={memberValue(programme?.history.not_available)}
              note="people — not evidence of missed care"
              i={6}
            />
          </dl>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div className="reveal rounded-xl border border-border bg-surface-raised p-5" style={{ "--i": 3 } as React.CSSProperties}>
              <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-[15px] font-semibold text-ink-text">Member lattice <span className="text-xs font-normal text-ink-faint">· one mark per person</span></p>
                <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
                  {SEGMENT_ORDER.map((s) => (
                    <li key={s} className="flex items-center gap-1.5">
                      <SegmentGlyph segment={s} surface="ink" /> {SEGMENT_META[s].short}
                    </li>
                  ))}
                </ul>
              </div>
              {population.status === "ready" && programme ? (
                programme.people > 0 ? (
                  <MemberLattice programme={programme} selected={state.segment} onSelect={(s) => navigate({ segment: s })} />
                ) : (
                  <p className="py-12 text-center text-sm text-ink-muted">No members match these filters.</p>
                )
              ) : population.status === "forbidden" ? (
                <p className="py-12 text-center text-sm text-ink-muted">Member-level views need patient access, which your role does not have.</p>
              ) : population.status === "error" ? (
                <InlineError tone="plate" message={`Members are unavailable. ${population.message}`} onRetry={retry} />
              ) : (
                <div aria-busy="true" aria-label="Loading members" className="skeleton h-56 rounded-xl" />
              )}
              <p className="mt-4 text-[11px] text-ink-faint">
                Marks are ordered by segment only; their position carries no clinical meaning. An open gap under any of this
                programme’s rules takes precedence, otherwise history availability decides.
              </p>
            </div>

            <SegmentFocus pathway={pathway} programme={programme} segment={segment?.segment ?? null} state={state} onClear={() => navigate({ segment: null })} />
          </div>
        </div>
      </section>

      <div className="mt-10">
        <ProgrammeSections
          pathway={pathway}
          state={state}
          navigate={navigate}
          model={model}
          programme={programme}
          data={data}
        />
      </div>
    </div>
  );
}

function HeroDash() {
  return <span aria-label="Loading" className="skeleton inline-block h-7 w-14 rounded-md align-middle" />;
}

function SegmentFocus({
  pathway,
  programme,
  segment,
  state,
  onClear,
}: {
  pathway: Pathway;
  programme: Programme | null;
  segment: SegmentId | null;
  state: DetailState;
  onClear: () => void;
}) {
  const cohort = programme ? (segment ? programme.segments.find((s) => s.segment === segment)! : programme) : null;
  const peopleFilters = segmentPeopleFilters(pathway, segment, state.filters);
  const backendTotal = usePeopleTotal(programme ? peopleFilters : null);
  const href = peopleFiltersHref(peopleFilters, "open_gaps");
  const top = cohort?.gapsByRule.slice(0, 4) ?? [];
  const max = top[0]?.count ?? 1;
  const mismatch = backendTotal.status === "ready" && cohort && backendTotal.data !== cohort.people;

  return (
    <aside
      aria-label="Segment focus"
      aria-live="polite"
      className="reveal flex flex-col rounded-xl border border-border bg-surface-raised p-5"
      style={{ "--i": 4 } as React.CSSProperties}
    >
      <div key={segment ?? "all"} className="reveal-fade flex flex-1 flex-col">
        <p className="flex items-center justify-between gap-2 text-xs font-medium text-ink-faint">
          {segment ? "Segment" : "Whole programme"}
          {segment && (
            <button type="button" onClick={onClear} className="rounded-full px-2 py-0.5 text-xs text-ink-accent hover:text-ink-text">
              Show all
            </button>
          )}
        </p>
        <h2 className="mt-1 flex items-center gap-2 text-lg font-semibold text-ink-text">
          {segment && <SegmentGlyph segment={segment} surface="ink" size={14} />}
          {segment ? SEGMENT_META[segment].label : `All ${PROGRAMME_META[pathway].name} members`}
        </h2>
        <p className="mt-2 text-[13px] leading-relaxed text-ink-muted">
          {segment
            ? SEGMENT_META[segment].description
            : "Select a block in the lattice to focus one evidence segment and see why its people appear here."}
        </p>

        <dl className="mt-5 grid grid-cols-2 gap-4 border-y border-ink-line py-4">
          <Figure tone="plate" size="md" label="People" value={cohort ? cohort.people : "—"} note={programme && segment ? `of ${programme.people}` : undefined} />
          <Figure tone="plate" size="md" label="Open gaps" value={cohort ? cohort.openGaps : "—"} note="records" />
        </dl>

        {top.length > 0 && (
          <div className="mt-4">
            <p className="mb-2 text-xs font-medium text-ink-muted">Most open gaps by rule</p>
            <ul className="flex flex-col gap-2">
              {top.map((r, i) => (
                <li key={r.key} title={r.key}>
                  <div className="flex items-baseline justify-between gap-2 text-xs">
                    <span className="truncate text-ink-muted">{r.label}</span>
                    <span className="font-mono tabular-nums text-ink-text">{r.count}</span>
                  </div>
                  <div className="mt-1 h-1 rounded-full bg-ink-line">
                    <div
                      className="grow-x h-1 rounded-full"
                      style={{ width: `${(r.count / max) * 100}%`, backgroundColor: "var(--ink-segment-gap)", "--i": i } as React.CSSProperties}
                    />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className={cn("mt-auto pt-6", !programme && "hidden")}>
          <a href="#people" className={buttonClass("primary", "w-full")}>
            Review {cohort ? cohort.people : ""} {cohort?.people === 1 ? "person" : "people"} below
          </a>
          <Link href={href} className={buttonClass("secondary", "mt-2 w-full")}>
            Open in People workspace <ArrowRight size={14} aria-hidden="true" />
          </Link>
          {mismatch && (
            <p className={cn("mt-3 flex gap-2 text-[11px] leading-relaxed text-ink-faint")}>
              <Info size={13} aria-hidden="true" className="mt-px shrink-0" />
              The People list returns {backendTotal.data} people for this segment rather than {cohort?.people}. This API
              version applies open-gap and history filters across all programmes.
            </p>
          )}
        </div>
      </div>
    </aside>
  );
}
