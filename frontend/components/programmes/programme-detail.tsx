"use client";

import { useCallback, useMemo, useState, ViewTransition } from "react";
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
import { useLocale, useT } from "@/lib/i18n/use-locale";

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
  const params = useParams<{ programme?: string }>();
  /* While this route is hidden (Cache Components keep it in <Activity>), `useParams` reports the visible
     route, which has no `programme`; keep the last slug so the page and its loaded data survive. */
  const [lastSlug, setLastSlug] = useState(params.programme ?? "");
  if (params.programme !== undefined && params.programme !== lastSlug) setLastSlug(params.programme);
  const slug = params.programme ?? lastSlug;
  const pathway = pathwayFromSlug(slug);
  if (!pathway) return <UnknownProgramme slug={slug} />;
  return <ProgrammeDetailBody pathway={pathway} />;
}

function UnknownProgramme({ slug }: { slug: string }) {
  const t = useT();
  return (
    <div className="mx-auto w-full max-w-[1280px] px-4 py-16 sm:px-6 lg:px-8">
      <p className="text-xs font-medium text-faint">{t("nav.programmes")}</p>
      <h1 className="mt-3 font-display text-[28px] font-medium text-foreground">{t("prog.unknown.title", { slug })}</h1>
      <p className="mt-3 text-sm text-muted">{t("prog.unknown.body")}</p>
      <Link href="/programmes" className={buttonClass("secondary", "mt-6")}>
        <ArrowLeft size={14} aria-hidden="true" className="rtl:-scale-x-100" /> {t("pop.filter.all_programmes")}
      </Link>
    </div>
  );
}

function ProgrammeDetailBody({ pathway }: { pathway: Pathway }) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { scope, state: auth } = useAuth();
  const { t: tr, rich: richT } = useLocale();
  const state = useMemo(() => parseDetail(new URLSearchParams(searchParams.toString())), [searchParams]);
  const data = useProgrammesData(state.filters, pathway);
  const { summary, rules, openQuestions, careGaps, population, retry } = data;
  const meta = PROGRAMME_META[pathway];
  const name = tr(meta.name);

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
      tr,
      ids
    );
  }, [rules, careGaps, openQuestions, population, pathway, filtered, tr]);

  const segment = state.segment ? programme?.segments.find((s) => s.segment === state.segment) ?? null : null;
  /* Gap figures are shown only when the records (and, if filtered, the member set) are loaded — never as 0. */
  const gapsKnown = careGaps.status === "ready" && (!filtered || population.status === "ready");
  const gapValue = (v: number | undefined) =>
    gapsKnown && v !== undefined ? v : careGaps.status === "loading" || population.status === "loading" ? <HeroDash /> : "—";
  const memberValue = (v: number | undefined) =>
    v !== undefined ? v : population.status === "loading" ? <HeroDash /> : "—";
  const sum = summary.status === "ready" ? summary.data : null;
  const home = homeCrumb(auth.status === "signed_in" ? auth.me.role : null, tr);
  const overviewQs = peopleFiltersToSearchParams({ region_id: state.filters.region_id, sex: state.filters.sex }).toString();

  return (
    <div className="mx-auto w-full max-w-[1280px] px-4 pb-16 pt-6 sm:px-6 lg:px-8">
      <section aria-labelledby="programme-heading">
        <div className="flex flex-col gap-6">
          <header className="reveal">
            <nav aria-label={tr("shell.breadcrumb")} className="mb-3">
              <ol className="flex flex-wrap items-center gap-1.5 text-xs text-ink-faint">
                <li>
                  <Link href={home.href} className="hover:text-ink-text">
                    {home.label}
                  </Link>
                </li>
                <li aria-hidden="true"><ChevronRight size={12} className="rtl:-scale-x-100" /></li>
                <li>
                  <Link href={overviewQs ? `/programmes?${overviewQs}` : "/programmes"} transitionTypes={BACK} className="hover:text-ink-text">
                    {tr("nav.programmes")}
                  </Link>
                </li>
                <li aria-hidden="true"><ChevronRight size={12} className="rtl:-scale-x-100" /></li>
                <li aria-current="page" className="text-ink-muted">
                  {name}
                </li>
              </ol>
            </nav>
            <div className="flex flex-wrap items-end justify-between gap-6">
              <div className="max-w-3xl">
                <p className="text-xs font-medium text-ink-faint">{tr("prog.plate.eyebrow", { audience: tr(meta.audience) })}</p>
                <ViewTransition name={`programme-title-${pathway}`} share="atlas-morph" default="none">
                  <h1
                    id="programme-heading"
                    className="mt-1 font-display text-[28px] font-medium leading-tight tracking-[-0.015em] text-ink-text"
                  >
                    {name}
                  </h1>
                </ViewTransition>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">
                  {model?.source
                    ? richT("prog.detail.source", {
                        source: <span className="text-ink-text" dir="auto">{model.source.name}</span>,
                        version: model.source.version,
                      })
                    : tr(meta.full)}
                </p>
                <p className="mt-2 text-xs text-ink-faint">
                  {[
                    sum && tr("prog.run_meta", { run: sum.evaluation_run_id, date: sum.reference_date }),
                    auth.status === "signed_in" && tr("prog.scope", { scope: scopeLabel(scope, tr) }),
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
              label={tr("prog.detail.filters", { programme: name })}
              filters={{ ...state.filters, pathway }}
              onChange={(f) => navigate({ filters: { ...state.filters, region_id: f.region_id, sex: f.sex }, segment: state.segment })}
              emptyText={tr("prog.detail.filters_empty", { programme: name })}
            >
              <label className={`${filterLabelClass("paper")} lg:w-40`}>
                {tr("prog.detail.age_group")}
                <select
                  className={selectClass("paper")}
                  value={state.filters.age_band ?? ""}
                  onChange={(e) =>
                    navigate({ filters: { ...state.filters, age_band: (e.target.value || undefined) as ProgrammeFilters["age_band"] } })
                  }
                >
                  <option value="">{tr("prog.detail.all_ages")}</option>
                  {AGE_BAND_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {tr(o.label)}
                    </option>
                  ))}
                </select>
              </label>
            </PopulationFilterBar>
            {state.filters.age_band && (
              <p className="mt-1 text-xs text-ink-faint">
                {tr("prog.detail.age_note")}
              </p>
            )}
          </div>

          {rules.status === "error" && <InlineError tone="plate" message={tr("prog.rules_unavailable", { message: rules.message })} onRetry={retry} />}

          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <KpiCard label={tr("prog.plate.members")} value={memberValue(programme?.people)} note={tr("prog.plate.members_note", { unit: tr(meta.unit) })} i={2} />
            <KpiCard label={tr("pop.compare.with_gap")} value={gapValue(model?.peopleWithOpenGap)} note={tr("prog.detail.people")} i={3} />
            <KpiCard label={tr("prog.detail.open_records")} value={gapValue(model?.gaps.open)} note={tr("prog.detail.open_records_note")} i={4} />
            <KpiCard label={tr("prog.detail.completions")} value={gapValue(model?.gaps.closed_completed)} note={tr("prog.detail.completions_note")} i={5} />
            <KpiCard
              label={tr("pop.compare.no_history")}
              value={memberValue(programme?.history.not_available)}
              note={tr("prog.detail.no_history_note")}
              i={6}
            />
          </dl>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div className="reveal rounded-xl border border-border bg-surface-raised p-5" style={{ "--i": 3 } as React.CSSProperties}>
              <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-[15px] font-semibold text-ink-text">
                  {tr("prog.detail.lattice")} <span className="text-xs font-normal text-ink-faint">· {tr("prog.detail.lattice_note")}</span>
                </p>
                <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
                  {SEGMENT_ORDER.map((s) => (
                    <li key={s} className="flex items-center gap-1.5">
                      <SegmentGlyph segment={s} surface="ink" /> {tr(SEGMENT_META[s].short)}
                    </li>
                  ))}
                </ul>
              </div>
              {population.status === "ready" && programme ? (
                programme.people > 0 ? (
                  <MemberLattice programme={programme} selected={state.segment} onSelect={(s) => navigate({ segment: s })} />
                ) : (
                  <p className="py-12 text-center text-sm text-ink-muted">{tr("prog.detail.no_members")}</p>
                )
              ) : population.status === "forbidden" ? (
                <p className="py-12 text-center text-sm text-ink-muted">{tr("prog.detail.members_forbidden")}</p>
              ) : population.status === "error" ? (
                <InlineError tone="plate" message={tr("prog.detail.members_unavailable", { message: population.message })} onRetry={retry} />
              ) : (
                <div aria-busy="true" aria-label={tr("prog.detail.loading_members")} className="skeleton h-56 rounded-xl" />
              )}
              <p className="mt-4 text-[11px] text-ink-faint">{tr("prog.detail.lattice_footnote")}</p>
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
  const t = useT();
  return <span aria-label={t("state.loading")} className="skeleton inline-block h-7 w-14 rounded-md align-middle" />;
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
  const { t, tp, number } = useLocale();

  return (
    <aside
      aria-label={t("prog.focus.label")}
      aria-live="polite"
      className="reveal flex flex-col rounded-xl border border-border bg-surface-raised p-5"
      style={{ "--i": 4 } as React.CSSProperties}
    >
      <div key={segment ?? "all"} className="reveal-fade flex flex-1 flex-col">
        <p className="flex items-center justify-between gap-2 text-xs font-medium text-ink-faint">
          {t(segment ? "prog.focus.segment" : "pop.panel.whole_programme")}
          {segment && (
            <button type="button" onClick={onClear} className="rounded-full px-2 py-0.5 text-xs text-ink-accent hover:text-ink-text">
              {t("prog.focus.show_all")}
            </button>
          )}
        </p>
        <h2 className="mt-1 flex items-center gap-2 text-lg font-semibold text-ink-text">
          {segment && <SegmentGlyph segment={segment} surface="ink" size={14} />}
          {segment ? t(SEGMENT_META[segment].label) : t("prog.focus.all_members", { programme: t(PROGRAMME_META[pathway].name) })}
        </h2>
        <p className="mt-2 text-[13px] leading-relaxed text-ink-muted">
          {segment ? t(SEGMENT_META[segment].description) : t("prog.focus.hint")}
        </p>

        <dl className="mt-5 grid grid-cols-2 gap-4 border-y border-ink-line py-4">
          <Figure tone="plate" size="md" label={t("pop.panel.people")} value={cohort ? cohort.people : "—"} note={programme && segment ? t("prog.focus.of", { total: programme.people }) : undefined} />
          <Figure tone="plate" size="md" label={t("prog.plate.open_gaps")} value={cohort ? cohort.openGaps : "—"} note={t("prog.plate.records")} />
        </dl>

        {top.length > 0 && (
          <div className="mt-4">
            <p className="mb-2 text-xs font-medium text-ink-muted">{t("prog.focus.top_rules")}</p>
            <ul className="flex flex-col gap-2">
              {top.map((r, i) => (
                <li key={r.key} title={r.key}>
                  <div className="flex items-baseline justify-between gap-2 text-xs">
                    <span className="truncate text-ink-muted" dir="auto">{r.label}</span>
                    <span className="font-mono tabular-nums text-ink-text">{number(r.count)}</span>
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
            {t("prog.focus.review", { people: tp("pop.people", cohort?.people ?? 0) })}
          </a>
          <Link href={href} className={buttonClass("secondary", "mt-2 w-full")}>
            {t("prog.focus.open_people")} <ArrowRight size={14} aria-hidden="true" className="rtl:-scale-x-100" />
          </Link>
          {mismatch && (
            <p className={cn("mt-3 flex gap-2 text-[11px] leading-relaxed text-ink-faint")}>
              <Info size={13} aria-hidden="true" className="mt-px shrink-0" />
              {t("prog.focus.mismatch", { backend: backendTotal.data, expected: cohort?.people ?? 0 })}
            </p>
          )}
        </div>
      </div>
    </aside>
  );
}
