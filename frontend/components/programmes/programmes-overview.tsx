"use client";

import { useCallback, useMemo, ViewTransition } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowRight } from "lucide-react";
import type { DashboardSummaryOut, Pathway, PathwayBreakdownOut } from "@/lib/api/types";
import { scopeLabel, useAuth } from "@/lib/auth/auth-context";
import { parsePeopleFilters, peopleFiltersToSearchParams } from "@/lib/people/params";
import { PATHWAY_OPTIONS } from "@/lib/population/filters";
import type { PopulationModel } from "@/lib/population/model";
import {
  buildProgrammeModel,
  GAP_STATUS_META,
  GAP_STATUS_ORDER,
  PROGRAMME_META,
  programmeHref,
  STANDING_META,
  type ProgrammeModel,
} from "@/lib/programmes/model";
import { useProgrammesData, type ProgrammeFilters } from "@/lib/programmes/use-programmes-data";
import { PageHeader } from "@/components/ui/page-header";
import { Plate, Footnote } from "@/components/ui/plate";
import { Figure } from "@/components/ui/figure";
import { buttonClass } from "@/components/ui/button-styles";
import { FORWARD } from "@/components/ui/page-transition";
import { PopulationFilterBar } from "@/components/population/population-filters";
import { CompositionBand } from "./composition";
import { StandingGlyph } from "./rule-spectrum";
import { InlineError, ResourceView } from "./resource-state";
import { OrganizationTrend } from "./organization-trend";
import { cn } from "@/lib/cn";

export function ProgrammesOverview() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { scope, state: auth } = useAuth();
  const filters: ProgrammeFilters = useMemo(() => {
    const f = parsePeopleFilters(searchParams);
    return { region_id: f.region_id, sex: f.sex };
  }, [searchParams]);
  const data = useProgrammesData(filters);
  const { summary, rules, openQuestions, careGaps, population, surveillance, retry } = data;

  const navigate = useCallback(
    (next: ProgrammeFilters) => {
      const qs = peopleFiltersToSearchParams(next).toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname]
  );

  const models = useMemo(() => {
    if (rules.status !== "ready") return null;
    const gaps = careGaps.status === "ready" ? careGaps.data : [];
    const oq = openQuestions.status === "ready" ? openQuestions.data : [];
    const patientIds =
      population.status === "ready" && (filters.region_id || filters.sex) ? new Set(population.data.patientIds) : null;
    return Object.fromEntries(
      PATHWAY_OPTIONS.map(({ value }) => [value, buildProgrammeModel(value, rules.data, gaps, oq, patientIds)])
    ) as Record<Pathway, ProgrammeModel>;
  }, [rules, careGaps, openQuestions, population, filters]);

  const filtered = !!(filters.region_id || filters.sex);
  const qs = peopleFiltersToSearchParams(filters).toString();
  const sum = summary.status === "ready" ? summary.data : null;

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-24 pt-8 sm:px-6 lg:px-8">
      <PageHeader
        index="02"
        eyebrow="Explain"
        title="Programmes"
        subtitle="The preventive-care programmes PulseReach evaluates — who they reach, which rules define them, and where documented care gaps open and close."
        breadcrumbs={[{ label: "Population", href: "/" }, { label: "Programmes" }]}
        meta={
          <span className="flex flex-wrap gap-x-4 gap-y-1">
            {sum && (
              <span>
                Evaluation run {sum.evaluation_run_id} · reference date {sum.reference_date}
              </span>
            )}
            {auth.status === "signed_in" && <span>Scope: {scopeLabel(scope)}</span>}
          </span>
        }
        className="mb-6"
      />

      <div className="reveal mb-10" style={{ "--i": 1 } as React.CSSProperties}>
        <PopulationFilterBar
          tone="paper"
          label="Programme filters"
          hideProgramme
          filters={filters}
          onChange={(f) => navigate({ region_id: f.region_id, sex: f.sex })}
          emptyText="Membership, segments and gap records cover everyone in your scope."
        />
      </div>

      {rules.status === "error" && <InlineError message={`Programme rules are unavailable. ${rules.message}`} onRetry={retry} />}

      <section aria-label="Programmes" className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {PATHWAY_OPTIONS.map(({ value }, i) => (
          <ProgrammePlate
            key={value}
            pathway={value}
            i={i}
            model={models?.[value] ?? null}
            gapsKnown={careGaps.status === "ready" && (!filtered || population.status === "ready")}
            gapsState={careGaps.status}
            population={population.status === "ready" ? population.data : null}
            populationState={population.status}
            summary={sum}
            href={programmeHref(value, qs)}
          />
        ))}
      </section>

      <div className="mt-16 flex flex-col gap-16">
        <Plate
          index="01"
          eyebrow="Programme ledger"
          title="What the engine counts, per programme"
          description="People-level counts from the dashboard summary for your scope. Each row says what it measures — and what it does not."
          aside
        >
          <ResourceView resource={summary} what="Programme breakdowns" onRetry={retry}>
            {(d) => <ProgrammeLedger summary={d} models={models} />}
          </ResourceView>
        </Plate>

        <Plate
          index="02"
          eyebrow="Coverage & completion"
          title="How documented care gaps close"
          description={
            <>
              Every care-gap record opened under each programme’s rules, by current status.
              {filtered && " Limited to people matching the filters above."} Only “completed” is a documented completion.
            </>
          }
          aside
        >
          <ResourceView resource={careGaps} what="Care-gap records" onRetry={retry}>
            {() => (models ? <GapClosure models={models} /> : null)}
          </ResourceView>
        </Plate>

        <Plate
          index="03"
          eyebrow="Organization trend"
          title="Preventive care across your organization"
          description="Surveillance aggregates for every programme together. The API has no per-programme trend, so none is drawn."
          aside
        >
          <ResourceView resource={surveillance} what="Organization surveillance aggregates" onRetry={retry}>
            {(d) => <OrganizationTrend data={d} />}
          </ResourceView>
        </Plate>
      </div>
    </div>
  );
}

function ProgrammePlate({
  pathway,
  model,
  population,
  populationState,
  summary,
  href,
  i,
  gapsKnown,
  gapsState,
}: {
  pathway: Pathway;
  gapsKnown: boolean;
  gapsState: string;
  model: ProgrammeModel | null;
  population: PopulationModel | null;
  populationState: string;
  summary: DashboardSummaryOut | null;
  href: string;
  i: number;
}) {
  const meta = PROGRAMME_META[pathway];
  const programme = population?.programmes.find((p) => p.pathway === pathway) ?? null;
  const breakdown = summary?.pathway_breakdown?.[pathway];
  return (
    <article
      aria-labelledby={`programme-${pathway}`}
      className="reveal group relative flex flex-col overflow-hidden rounded-2xl bg-ink p-6 text-ink-text sm:p-8"
      style={{ "--i": i + 2 } as React.CSSProperties}
    >
      <span
        aria-hidden="true"
        className="pointer-events-none absolute -right-16 -top-16 size-56 rounded-full border border-ink-line transition-transform duration-700 ease-[var(--ease-out)] group-hover:scale-110"
      />
      <span
        aria-hidden="true"
        className="pointer-events-none absolute -right-4 -top-4 size-32 rounded-full border border-dashed border-ink-line transition-transform duration-700 ease-[var(--ease-out)] group-hover:rotate-45"
      />
      <p className="relative text-[11px] font-semibold uppercase tracking-[0.16em] text-ink-accent">
        Programme · {meta.audience}
      </p>
      <ViewTransition name={`programme-title-${pathway}`} share="atlas-morph" default="none">
        <h2 id={`programme-${pathway}`} className="relative mt-3 font-display text-5xl font-normal tracking-[-0.03em] text-ink-text">
          {meta.name}
        </h2>
      </ViewTransition>
      <p className="relative mt-2 min-h-10 max-w-md text-sm leading-relaxed text-ink-muted">
        {model?.source ? `${model.source.name} (${model.source.version})` : "\u00a0"}
      </p>

      <dl className="relative mt-7 grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-4">
        <Figure
          tone="plate"
          size="md"
          label="Members"
          value={programme ? programme.people : populationState === "loading" ? <Dash /> : "—"}
          note={`${meta.unit} with a history record`}
          i={i + 3}
        />
        <Figure
          tone="plate"
          size="md"
          label="Due or upcoming"
          value={breakdown ? breakdown.due_or_upcoming_patients : summary ? "—" : <Dash />}
          note="people · whole scope"
          i={i + 4}
        />
        <Figure
          tone="plate"
          size="md"
          label="Open gaps"
          value={model && gapsKnown ? model.gaps.open : gapsState === "loading" ? <Dash /> : "—"}
          note={model && gapsKnown ? `records · ${model.peopleWithOpenGap} people` : "records"}
          i={i + 5}
        />
        <Figure
          tone="plate"
          size="md"
          label="Completed"
          value={model && gapsKnown ? model.gaps.closed_completed : gapsState === "loading" ? <Dash /> : "—"}
          note="gaps closed by documentation"
          i={i + 6}
        />
      </dl>

      <div className="relative mt-7">
        {programme ? (
          programme.people > 0 ? (
            <CompositionBand programme={programme} tone="ink" />
          ) : (
            <p className="text-sm text-ink-muted">No members match the current filters.</p>
          )
        ) : populationState === "forbidden" ? (
          <p className="text-xs text-ink-faint">Member segments need patient access, which your role does not have.</p>
        ) : populationState === "error" ? (
          <p className="text-xs text-ink-faint">Member segments are unavailable.</p>
        ) : (
          <div className="skeleton-ink h-3 rounded-full" />
        )}
      </div>

      <div className="relative mt-auto flex flex-wrap items-end justify-between gap-4 pt-8">
        {model ? (
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-muted">
            <span className="text-ink-text">{model.rules.length} rules</span>
            {(["authoritative", "review", "unresolved"] as const).map((s) =>
              model.standing[s] > 0 ? (
                <span key={s} className="inline-flex items-center gap-1.5">
                  <span className="[--accent:var(--ink-accent-2)] [--status-review:var(--ink-review)] [--status-insufficient:var(--ink-insufficient)]">
                    <StandingGlyph standing={s} size={10} />
                  </span>
                  {model.standing[s]} {STANDING_META[s].label.toLowerCase()}
                </span>
              ) : null
            )}
          </p>
        ) : (
          <span />
        )}
        <Link href={href} transitionTypes={FORWARD} className={buttonClass("plate-primary")}>
          Explore {meta.name}
          <ArrowRight size={15} aria-hidden="true" className="transition-transform duration-300 group-hover:translate-x-0.5" />
        </Link>
      </div>
    </article>
  );
}

function Dash() {
  return <span aria-label="Loading" className="skeleton-ink inline-block h-7 w-14 rounded-md align-middle" />;
}

const LEDGER_ROWS: {
  key: keyof PathwayBreakdownOut;
  label: string;
  means: string;
  caution?: boolean;
}[] = [
  {
    key: "programme_eligible_patients",
    label: "In programme scope",
    means: "People with an in-band programme “eligible” result. Not a care need.",
  },
  {
    key: "due_or_upcoming_patients",
    label: "Due or upcoming",
    means: "People with at least one in-band due, upcoming or overdue result.",
  },
  { key: "open_care_gaps_count", label: "Open care-gap records", means: "Gap records, not people." },
  {
    key: "patients_with_history",
    label: "History on record",
    means: "People whose screening or visit history is available or partial.",
  },
  {
    key: "unknown_history_patients",
    label: "History unavailable",
    means: "Evaluations resolve to “unknown” — never evidence that care did not happen.",
  },
  {
    key: "review_flagged_patients",
    label: "Records need clinical review",
    means: "People whose own records route a result to a healthcare professional.",
  },
  {
    key: "rule_review_patients",
    label: "Touched by a rule under review",
    means: "In scope of a rule that is itself unresolved or review-flagged. Not “people needing review”.",
    caution: true,
  },
];

function ProgrammeLedger({ summary, models }: { summary: DashboardSummaryOut; models: Record<Pathway, ProgrammeModel> | null }) {
  const bd = summary.pathway_breakdown;
  if (!bd) return <p className="text-sm text-muted">This API version does not return a per-programme breakdown.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-left text-sm">
        <caption className="sr-only">People-level programme breakdown from the dashboard summary</caption>
        <thead>
          <tr className="border-b border-border-strong text-[11px] uppercase tracking-[0.12em] text-faint">
            <th scope="col" className="py-2 pr-4 font-medium">
              Measure
            </th>
            {PATHWAY_OPTIONS.map((o) => (
              <th key={o.value} scope="col" className="w-28 py-2 pr-4 text-right font-medium">
                {PROGRAMME_META[o.value].name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {LEDGER_ROWS.map((row, i) => (
            <tr key={row.key} className="reveal-fade align-top" style={{ "--i": i } as React.CSSProperties}>
              <th scope="row" className="py-3 pr-4 font-normal">
                <span className="block font-medium text-foreground">{row.label}</span>
                <span className={cn("mt-0.5 block text-xs", row.caution ? "font-display text-[13px] italic text-foreground" : "text-muted")}>{row.means}</span>
              </th>
              {PATHWAY_OPTIONS.map((o) => (
                <td key={o.value} className="figure py-3 pr-4 text-right text-xl text-foreground">
                  {bd[o.value]?.[row.key] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
          {models && (
            <tr className="align-top">
              <th scope="row" className="py-3 pr-4 font-normal">
                <span className="block font-medium text-foreground">Rules defining the programme</span>
                <span className="mt-0.5 block text-xs text-muted">From the versioned rule bundle (`GET /rules`).</span>
              </th>
              {PATHWAY_OPTIONS.map((o) => (
                <td key={o.value} className="figure py-3 pr-4 text-right text-xl text-foreground">
                  {models[o.value].rules.length}
                </td>
              ))}
            </tr>
          )}
        </tbody>
      </table>
      <Footnote>
        {summary.governance_disclaimer} Counts follow the backend’s dashboard semantics (in-band results only; people, not
        evaluations, unless stated).
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

export function GapClosure({ models }: { models: Record<Pathway, ProgrammeModel> }) {
  return (
    <div className="flex flex-col gap-8">
      {PATHWAY_OPTIONS.map(({ value }, pi) => {
        const m = models[value];
        const total = m.gaps.total;
        return (
          <div key={value} className="reveal" style={{ "--i": pi } as React.CSSProperties}>
            <div className="mb-2 flex items-baseline justify-between gap-3">
              <p className="font-display text-lg text-foreground">{PROGRAMME_META[value].name}</p>
              <p className="text-xs text-muted">
                <span className="font-mono text-foreground">{total}</span> gap records
              </p>
            </div>
            {total === 0 ? (
              <p className="text-sm text-muted">No care-gap records for these rules in your scope.</p>
            ) : (
              <>
                <div
                  className="flex h-6 w-full gap-[2px] overflow-hidden rounded-md"
                  role="img"
                  aria-label={`${PROGRAMME_META[value].name} gap records: ${GAP_STATUS_ORDER.map((s) => `${GAP_STATUS_META[s].short} ${m.gaps[s]}`).join(", ")}`}
                >
                  {GAP_STATUS_ORDER.filter((s) => m.gaps[s] > 0).map((s, i) => (
                    <span
                      key={s}
                      className="grow-x h-full"
                      style={{ width: `${(m.gaps[s] / total) * 100}%`, backgroundColor: CLOSURE_COLOR[s], "--i": i } as React.CSSProperties}
                    />
                  ))}
                </div>
                <ul className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs sm:grid-cols-5">
                  {GAP_STATUS_ORDER.map((s) => (
                    <li key={s} className="flex items-center gap-2 text-muted">
                      <span aria-hidden="true" className="size-2 shrink-0 rounded-sm" style={{ backgroundColor: CLOSURE_COLOR[s] }} />
                      {GAP_STATUS_META[s].short}
                      <span className="ml-auto font-mono tabular-nums text-foreground sm:ml-0">{m.gaps[s]}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        );
      })}
      <Footnote>
        Completion here means a gap closed by a documented screening, visit or referral. People with no gap record are not
        counted as complete or incomplete.
      </Footnote>
    </div>
  );
}
