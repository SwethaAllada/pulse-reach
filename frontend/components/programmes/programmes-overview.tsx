"use client";

import { homeCrumb } from "@/components/shell/nav-items";
import { useCallback, useMemo, ViewTransition } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowRight } from "lucide-react";
import type { DashboardSummaryOut, Pathway, PathwayBreakdownOut, ProgrammeSummaryOut } from "@/lib/api/types";
import { scopeLabel, useAuth } from "@/lib/auth/auth-context";
import { parsePeopleFilters, peopleFiltersToSearchParams } from "@/lib/people/params";
import { PATHWAY_OPTIONS } from "@/lib/population/filters";
import {
  buildProgrammeModel,
  countText,
  GAP_STATUS_META,
  GAP_STATUS_ORDER,
  PROGRAMME_META,
  programmeHref,
  STANDING_META,
  summaryBand,
  type ProgrammeModel,
} from "@/lib/programmes/model";
import { useProgrammesOverviewData, type ProgrammeFilters, type Resource } from "@/lib/programmes/use-programmes-data";
import { PageHeader } from "@/components/ui/page-header";
import { Plate, Footnote } from "@/components/ui/plate";
import { Figure } from "@/components/ui/figure";
import { buttonClass } from "@/components/ui/button-styles";
import { FORWARD } from "@/components/ui/page-transition";
import { PopulationFilterBar } from "@/components/population/population-filters";
import { CompositionBand } from "./composition";
import { StandingGlyph } from "./rule-spectrum";
import { InlineError, ResourceView } from "./resource-state";
import { OrganizationTrend, ProgrammeTrend } from "./organization-trend";
import { cn } from "@/lib/cn";
import { useLocale, useT } from "@/lib/i18n/use-locale";
import type { MessageKey } from "@/lib/i18n/translate";

export function ProgrammesOverview() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { scope, state: auth, role } = useAuth();
  const tr = useT();
  const filters: ProgrammeFilters = useMemo(() => {
    const f = parsePeopleFilters(searchParams);
    return { region_id: f.region_id, sex: f.sex };
  }, [searchParams]);
  const data = useProgrammesOverviewData(filters);
  const { summary, rules, openQuestions, surveillance, summaries, retry } = data;

  const navigate = useCallback(
    (next: ProgrammeFilters) => {
      const qs = peopleFiltersToSearchParams(next).toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname]
  );

  /* Rules and their standing only; every count comes from the server-side programme summaries. */
  const models = useMemo(() => {
    if (rules.status !== "ready") return null;
    const oq = openQuestions.status === "ready" ? openQuestions.data : [];
    return Object.fromEntries(
      PATHWAY_OPTIONS.map(({ value }) => [value, buildProgrammeModel(value, rules.data, [], oq, tr)])
    ) as Record<Pathway, ProgrammeModel>;
  }, [rules, openQuestions, tr]);

  const filtered = !!(filters.region_id || filters.sex);
  const qs = peopleFiltersToSearchParams(filters).toString();
  const sum = summary.status === "ready" ? summary.data : null;

  return (
    <div className="mx-auto w-full max-w-[1280px] px-4 pb-16 pt-6 sm:px-6 lg:px-8">
      <PageHeader
        index="02"
        eyebrow={tr("prog.eyebrow")}
        title={tr("nav.programmes")}
        subtitle={tr("prog.subtitle")}
        breadcrumbs={[homeCrumb(role, tr), { label: tr("nav.programmes") }]}
        meta={
          <span className="flex flex-wrap gap-x-4 gap-y-1">
            {sum && (
              <span>{tr("prog.run_meta", { run: sum.evaluation_run_id, date: sum.reference_date })}</span>
            )}
            {auth.status === "signed_in" && <span>{tr("prog.scope", { scope: scopeLabel(scope, tr) })}</span>}
          </span>
        }
        className="mb-6"
      />

      <div className="reveal mb-10" style={{ "--i": 1 } as React.CSSProperties}>
        <PopulationFilterBar
          tone="paper"
          label={tr("prog.filters")}
          hideProgramme
          filters={filters}
          onChange={(f) => navigate({ region_id: f.region_id, sex: f.sex })}
          emptyText={tr("prog.filters_empty")}
        />
      </div>

      {rules.status === "error" && <InlineError message={tr("prog.rules_unavailable", { message: rules.message })} onRetry={retry} />}

      <section aria-label={tr("nav.programmes")} className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {PATHWAY_OPTIONS.map(({ value }, i) => (
          <ProgrammePlate
            key={value}
            pathway={value}
            i={i}
            model={models?.[value] ?? null}
            programme={summaries[value]}
            href={programmeHref(value, qs)}
            onRetry={retry}
          />
        ))}
      </section>

      <div className="mt-16 flex flex-col gap-16">
        <Plate
          index="01"
          eyebrow={tr("prog.ledger.eyebrow")}
          title={tr("prog.ledger.title")}
          description={tr("prog.ledger.desc")}
          aside
        >
          <ResourceView resource={summary} what={tr("prog.ledger.what")} onRetry={retry}>
            {(d) => <ProgrammeLedger summary={d} models={models} />}
          </ResourceView>
        </Plate>

        <Plate
          index="02"
          eyebrow={tr("prog.closure.eyebrow")}
          title={tr("prog.closure.title")}
          description={
            <>
              {tr("prog.closure.desc")}
              {filtered && ` ${tr("prog.closure.filtered")}`} {tr("prog.closure.only_completed")}
            </>
          }
          aside
        >
          <GapClosure summaries={summaries} onRetry={retry} />
        </Plate>

        <Plate
          index="03"
          eyebrow={tr("prog.trend.eyebrow")}
          title={tr("prog.trend.title")}
          description={tr("prog.trend.desc")}
          aside
        >
          <div className="flex flex-col gap-12">
            <ResourceView resource={surveillance} what={tr("prog.trend.what")} onRetry={retry}>
              {(d) => <OrganizationTrend data={d} />}
            </ResourceView>
            <div className="grid grid-cols-1 gap-10 lg:grid-cols-2">
              {PATHWAY_OPTIONS.map(({ value }) => (
                <ResourceView key={value} resource={summaries[value]} what={tr("prog.trend.figures", { programme: tr(PROGRAMME_META[value].name) })} onRetry={retry}>
                  {(d) => <ProgrammeTrend data={d} name={tr(PROGRAMME_META[value].name)} />}
                </ResourceView>
              ))}
            </div>
          </div>
        </Plate>
      </div>
    </div>
  );
}

function ProgrammePlate({
  pathway,
  model,
  programme,
  href,
  i,
  onRetry,
}: {
  pathway: Pathway;
  model: ProgrammeModel | null;
  programme: Resource<ProgrammeSummaryOut>;
  href: string;
  i: number;
  onRetry: () => void;
}) {
  const { t } = useLocale();
  const meta = PROGRAMME_META[pathway];
  const name = t(meta.name);
  const s = programme.status === "ready" ? programme.data : null;
  const value = (v: number | null | undefined) =>
    s ? (v ?? <Suppressed />) : programme.status === "loading" ? <Dash /> : "—";
  const band = s ? summaryBand(s, t) : null;
  return (
    <article
      aria-labelledby={`programme-${pathway}`}
      className="reveal group relative flex flex-col overflow-hidden rounded-xl border border-border bg-surface-raised p-6 text-ink-text sm:p-8"
      style={{ "--i": i + 2 } as React.CSSProperties}
    >
      <p className="relative text-xs font-medium text-ink-faint">
        {t("prog.plate.eyebrow", { audience: t(meta.audience) })}
      </p>
      <ViewTransition name={`programme-title-${pathway}`} share="atlas-morph" default="none">
        <h2 id={`programme-${pathway}`} className="relative mt-1 font-display text-2xl font-medium tracking-[-0.01em] text-ink-text">
          {name}
        </h2>
      </ViewTransition>
      <p className="relative mt-2 min-h-10 max-w-md text-sm leading-relaxed text-ink-muted" dir="auto">
        {model?.source ? `${model.source.name} (${model.source.version})` : "\u00a0"}
      </p>

      <dl className="relative mt-7 grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-4">
        <Figure tone="plate" size="md" label={t("prog.plate.members")} value={value(s?.members)} note={t("prog.plate.members_note", { unit: t(meta.unit) })} i={i + 3} />
        <Figure
          tone="plate"
          size="md"
          label={t("prog.plate.due")}
          value={value(s?.eligibility.due_or_upcoming_patients)}
          note={t("prog.plate.due_note")}
          i={i + 4}
        />
        <Figure
          tone="plate"
          size="md"
          label={t("prog.plate.open_gaps")}
          value={value(s?.care_gaps.open)}
          note={s ? t("prog.plate.open_gaps_note", { count: countText(s.people_with_open_gap, t) }) : t("prog.plate.records")}
          i={i + 5}
        />
        <Figure tone="plate" size="md" label={t("prog.plate.completed")} value={value(s?.care_gaps.closed_completed)} note={t("prog.plate.completed_note")} i={i + 6} />
      </dl>

      <div className="relative mt-7">
        {s ? (
          s.members === 0 ? (
            <p className="text-sm text-ink-muted">{t("prog.plate.no_members")}</p>
          ) : band ? (
            <CompositionBand programme={band} tone="ink" />
          ) : (
            <p className="text-xs text-ink-faint">
              {t("prog.plate.segments_suppressed", { min: s.min_cell_size })}
            </p>
          )
        ) : programme.status === "forbidden" ? (
          <p className="text-xs text-ink-faint">{t("prog.plate.forbidden")}</p>
        ) : programme.status === "error" ? (
          <InlineError tone="plate" message={programme.message} onRetry={onRetry} />
        ) : (
          <div className="skeleton h-3 rounded-full" />
        )}
      </div>

      <div className="relative mt-auto flex flex-wrap items-end justify-between gap-4 pt-8">
        {model ? (
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-muted">
            <span className="text-ink-text">{t("prog.plate.rules", { count: model.rules.length })}</span>
            {(["authoritative", "review", "unresolved"] as const).map((st) =>
              model.standing[st] > 0 ? (
                <span key={st} className="inline-flex items-center gap-1.5">
                  <span className="[--accent:var(--ink-accent-2)] [--status-review:var(--ink-review)] [--status-insufficient:var(--ink-insufficient)]">
                    <StandingGlyph standing={st} size={10} />
                  </span>
                  {t("prog.plate.standing_count", { count: model.standing[st], label: t(STANDING_META[st].label).toLowerCase() })}
                </span>
              ) : null
            )}
          </p>
        ) : (
          <span />
        )}
        <Link href={href} transitionTypes={FORWARD} className={buttonClass("plate-primary")}>
          {t("prog.plate.explore", { programme: name })}
          <ArrowRight size={15} aria-hidden="true" className="transition-transform duration-300 group-hover:translate-x-0.5 rtl:-scale-x-100 rtl:group-hover:-translate-x-0.5" />
        </Link>
      </div>
    </article>
  );
}

/** A count the backend suppressed for privacy (small cell) — never shown as zero. */
function Suppressed() {
  const { t } = useLocale();
  return (
    <span title={t("prog.suppressed_title")} aria-label={t("prog.suppressed_title")} className="text-base text-ink-faint">
      {t("prog.suppressed")}
    </span>
  );
}

function Dash() {
  const { t } = useLocale();
  return <span aria-label={t("state.loading")} className="skeleton inline-block h-7 w-14 rounded-md align-middle" />;
}

const LEDGER_ROWS: {
  key: keyof PathwayBreakdownOut;
  label: MessageKey;
  means: MessageKey;
  caution?: boolean;
}[] = [
  { key: "programme_eligible_patients", label: "prog.ledger.in_scope", means: "prog.ledger.in_scope_means" },
  { key: "due_or_upcoming_patients", label: "prog.ledger.due", means: "prog.ledger.due_means" },
  { key: "open_care_gaps_count", label: "prog.ledger.open_gaps", means: "prog.ledger.open_gaps_means" },
  { key: "patients_with_history", label: "prog.ledger.history", means: "prog.ledger.history_means" },
  { key: "unknown_history_patients", label: "prog.ledger.no_history", means: "prog.ledger.no_history_means" },
  { key: "review_flagged_patients", label: "prog.ledger.review", means: "prog.ledger.review_means" },
  { key: "rule_review_patients", label: "prog.ledger.rule_review", means: "prog.ledger.rule_review_means", caution: true },
];

function ProgrammeLedger({ summary, models }: { summary: DashboardSummaryOut; models: Record<Pathway, ProgrammeModel> | null }) {
  const { t } = useLocale();
  const bd = summary.pathway_breakdown;
  if (!bd) return <p className="text-sm text-muted">{t("prog.ledger.no_breakdown")}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-start text-sm">
        <caption className="sr-only">{t("prog.ledger.caption")}</caption>
        <thead>
          <tr className="border-b border-border-strong text-[11px] uppercase tracking-[0.12em] text-faint">
            <th scope="col" className="py-2 pe-4 text-start font-medium">
              {t("pop.compare.measure")}
            </th>
            {PATHWAY_OPTIONS.map((o) => (
              <th key={o.value} scope="col" className="w-28 py-2 pe-4 text-end font-medium">
                {t(PROGRAMME_META[o.value].name)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {LEDGER_ROWS.map((row, i) => (
            <tr key={row.key} className="reveal-fade align-top" style={{ "--i": i } as React.CSSProperties}>
              <th scope="row" className="py-3 pe-4 text-start font-normal">
                <span className="block font-medium text-foreground">{t(row.label)}</span>
                <span className={cn("mt-0.5 block text-xs", row.caution ? "font-display text-[13px] italic text-foreground" : "text-muted")}>{t(row.means)}</span>
              </th>
              {PATHWAY_OPTIONS.map((o) => (
                <td key={o.value} className="figure py-3 pe-4 text-end text-xl text-foreground">
                  {bd[o.value]?.[row.key] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
          {models && (
            <tr className="align-top">
              <th scope="row" className="py-3 pe-4 text-start font-normal">
                <span className="block font-medium text-foreground">{t("prog.ledger.rules")}</span>
                <span className="mt-0.5 block text-xs text-muted">{t("prog.ledger.rules_means")}</span>
              </th>
              {PATHWAY_OPTIONS.map((o) => (
                <td key={o.value} className="figure py-3 pe-4 text-end text-xl text-foreground">
                  {models[o.value].rules.length}
                </td>
              ))}
            </tr>
          )}
        </tbody>
      </table>
      <Footnote>
        {summary.governance_disclaimer} {t("prog.ledger.footnote")}
      </Footnote>
    </div>
  );
}

const CLOSURE_COLOR: Record<string, string> = {
  open: "var(--segment-gap)",
  closed_completed: "var(--status-completed)",
  closed_refused: "var(--status-not-eligible)",
  suppressed: "var(--status-unknown)",
  superseded: "var(--border-strong)",
};

export function GapClosure({ summaries, onRetry }: { summaries: Record<Pathway, Resource<ProgrammeSummaryOut>>; onRetry: () => void }) {
  const { t, rich } = useLocale();
  return (
    <div className="flex flex-col gap-8">
      {PATHWAY_OPTIONS.map(({ value }, pi) => (
        <ResourceView key={value} resource={summaries[value]} what={t("prog.closure.what", { programme: t(PROGRAMME_META[value].name) })} onRetry={onRetry}>
          {(s) => {
            const g = s.care_gaps;
            const complete = g.total !== null && GAP_STATUS_ORDER.every((st) => g[st] !== null);
            return (
              <div className="reveal" style={{ "--i": pi } as React.CSSProperties}>
                <div className="mb-2 flex items-baseline justify-between gap-3">
                  <p className="font-display text-lg text-foreground">{t(PROGRAMME_META[value].name)}</p>
                  <p className="text-xs text-muted">
                    {rich("prog.closure.records", { count: <span className="font-mono text-foreground">{countText(g.total, t)}</span> })}
                  </p>
                </div>
                {g.total === 0 ? (
                  <p className="text-sm text-muted">{t("prog.closure.none")}</p>
                ) : (
                  <>
                    {complete ? (
                      <div
                        className="flex h-6 w-full gap-[2px] overflow-hidden rounded-md"
                        role="img"
                        aria-label={t("prog.closure.aria", {
                          programme: t(PROGRAMME_META[value].name),
                          values: GAP_STATUS_ORDER.map((st) => `${t(GAP_STATUS_META[st].short)} ${g[st]}`).join(t("list.sep")),
                        })}
                      >
                        {GAP_STATUS_ORDER.filter((st) => (g[st] ?? 0) > 0).map((st, i) => (
                          <span
                            key={st}
                            className="grow-x h-full"
                            style={{ width: `${((g[st] ?? 0) / (g.total ?? 1)) * 100}%`, backgroundColor: CLOSURE_COLOR[st], "--i": i } as React.CSSProperties}
                          />
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-faint">
                        {t("prog.closure.suppressed", { min: s.min_cell_size })}
                      </p>
                    )}
                    <ul className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs sm:grid-cols-5">
                      {GAP_STATUS_ORDER.map((st) => (
                        <li key={st} className="flex items-center gap-2 text-muted">
                          <span aria-hidden="true" className="size-2 shrink-0 rounded-sm" style={{ backgroundColor: CLOSURE_COLOR[st] }} />
                          {t(GAP_STATUS_META[st].short)}
                          <span className="ms-auto font-mono tabular-nums text-foreground sm:ms-0">{countText(g[st], t)}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            );
          }}
        </ResourceView>
      ))}
      <Footnote>
        {t("prog.closure.footnote")}
      </Footnote>
    </div>
  );
}
