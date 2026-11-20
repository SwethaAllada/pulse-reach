"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, ChevronDown, SearchX } from "lucide-react";
import type { Pathway, PatientSummaryOut } from "@/lib/api/types";
import { regionLabel } from "@/lib/population/filters";
import { SEGMENT_META, type Programme } from "@/lib/population/model";
import { ageLabel, historyMeta, sexLabel } from "@/lib/people/person";
import { peopleFiltersToSearchParams } from "@/lib/people/params";
import {
  EVIDENCE_META,
  evidenceFigures,
  GAP_STATUS_META,
  PROGRAMME_META,
  RULE_GROUP_META,
  RULE_GROUP_ORDER,
  ruleHref,
  segmentPeopleFilters,
  STANDING_META,
  type ProgrammeModel,
  type RuleStanding,
} from "@/lib/programmes/model";
import { useAgeBands, type useProgrammesData } from "@/lib/programmes/use-programmes-data";
import { Plate, Footnote } from "@/components/ui/plate";
import { Segmented } from "@/components/ui/segmented";
import { EmptyState } from "@/components/ui/empty-state";
import { LoadingState } from "@/components/ui/loading-state";
import { buttonClass } from "@/components/ui/button-styles";
import { FORWARD } from "@/components/ui/page-transition";
import { StatusGlyph } from "@/components/ui/status-glyph";
import { PROGRAMME_COLOR, SegmentGlyph } from "@/components/population/segment-glyph";
import { RuleSpectrum, SPECTRUM_METRICS, StandingGlyph } from "./rule-spectrum";
import { ResourceView } from "./resource-state";
import { OrganizationTrend, ProgrammeTrend } from "./organization-trend";
import type { DetailState } from "./programme-detail";
import { cn } from "@/lib/cn";

type Data = ReturnType<typeof useProgrammesData>;

export function ProgrammeSections({
  pathway,
  state,
  navigate,
  model,
  programme,
  data,
}: {
  pathway: Pathway;
  state: DetailState;
  navigate: (patch: Partial<DetailState>) => void;
  model: ProgrammeModel | null;
  programme: Programme | null;
  data: Data;
}) {
  const referenceDate = data.summary.status === "ready" ? data.summary.data.reference_date : null;
  return (
    <div className="flex flex-col gap-16">
      <Plate
        index="01"
        eyebrow="Evidence & transparency"
        title="Why people appear in this programme"
        description="Four different kinds of evidence sit behind the numbers. They are kept apart so that missing history is never read as missed care."
      >
        <ResourceView resource={data.programmeSummary} what="Programme evidence" onRetry={data.retry} loading={<LoadingState rows={2} label="Loading evidence" />}>
          {(s) => <EvidenceLedger figures={evidenceFigures(s)} />}
        </ResourceView>
      </Plate>

      <Plate
        index="02"
        eyebrow="Rules & pathways"
        title="The rules that define the programme"
        description="Each column is one rule from the versioned bundle. Its height counts care-gap records in the chosen state; the foot glyph shows how far the rule can be trusted."
        actions={
          <Segmented
            label="Care-gap state"
            value={state.metric}
            onChange={(metric) => navigate({ metric })}
            options={SPECTRUM_METRICS.map((m) => ({ value: m, label: GAP_STATUS_META[m].short }))}
          />
        }
      >
        <ResourceView resource={data.rules} what="Programme rules" onRetry={data.retry}>
          {() =>
            model ? (
              <>
                <StandingFilter model={model} value={state.standing} onChange={(standing) => navigate({ standing })} />
                <RuleSpectrum pathway={pathway} rows={model.rules} metric={state.metric} standing={state.standing} />
                {data.careGaps.status === "forbidden" && (
                  <p className="mt-2 text-xs text-faint">Care-gap counts need care_gaps.read; columns show rules only.</p>
                )}
                <RuleIndex pathway={pathway} model={model} standing={state.standing} />
              </>
            ) : null
          }
        </ResourceView>
      </Plate>

      <Plate
        id="people"
        index="03"
        eyebrow="People"
        title={state.segment ? SEGMENT_META[state.segment].label : "Members who need attention first"}
        description={
          state.segment
            ? "Members in the selected segment, most open gaps in this programme first. Open a profile to see the evidence trace."
            : "All members, ordered by open care-gap records in this programme. Select a lattice segment above to narrow the list."
        }
      >
        <ResourceView resource={data.population} what="Programme members" onRetry={data.retry}>
          {(d) =>
            programme ? (
              <MemberList pathway={pathway} programme={programme} people={d.patientsById} state={state} referenceDate={referenceDate} />
            ) : null
          }
        </ResourceView>
      </Plate>

      <Plate
        index="04"
        eyebrow="Population distribution"
        title="Who the programme reaches"
        description="Members by backend age group, sex and region for the current filters."
      >
        <Distribution pathway={pathway} state={state} programme={programme} data={data} />
      </Plate>

      <Plate
        index="05"
        eyebrow="Open questions"
        title="What the standard leaves unresolved"
        description="Questions recorded against this programme’s rules. PulseReach reports them and never answers them on the standard’s behalf."
      >
        <ResourceView resource={data.openQuestions} what="Open questions" onRetry={data.retry}>
          {() => (model ? <OpenQuestions model={model} pathway={pathway} /> : null)}
        </ResourceView>
      </Plate>

      <Plate
        index="06"
        eyebrow="Programme & organization trend"
        title="Preventive care over time"
        description="This programme’s period comparison, drawn only where persisted evaluation history covers both periods, then organization-wide surveillance for all programmes together."
      >
        <div className="flex flex-col gap-12">
          <ResourceView resource={data.programmeSummary} what={`${PROGRAMME_META[pathway].name} trend figures`} onRetry={data.retry}>
            {(d) => <ProgrammeTrend data={d} name={PROGRAMME_META[pathway].name} />}
          </ResourceView>
          <ResourceView resource={data.surveillance} what="Organization surveillance aggregates" onRetry={data.retry}>
            {(d) => <OrganizationTrend data={d} />}
          </ResourceView>
        </div>
      </Plate>
    </div>
  );
}

/* ── 01 Evidence ledger ────────────────────────────────────────────────── */

const EVIDENCE_GLYPH = {
  calculated: <StatusGlyph status="upcoming" size={16} />,
  recorded_gap: <StatusGlyph status="due" size={16} />,
  completed: <StatusGlyph status="completed" size={16} />,
  missing_history: <StatusGlyph status="unknown" size={16} />,
};

function EvidenceLedger({ figures }: { figures: ReturnType<typeof evidenceFigures> }) {
  return (
    <ol className="grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
      {figures.map((f, i) => {
        const meta = EVIDENCE_META[f.cls];
        return (
          <li key={f.cls} className="reveal flex flex-col bg-surface p-5" style={{ "--i": i } as React.CSSProperties}>
            <p className="flex items-center gap-2 text-xs font-semibold text-foreground">
              {EVIDENCE_GLYPH[f.cls]}
              {meta.title}
            </p>
            <p className="figure mt-3 text-[32px] text-foreground">{f.value ?? "—"}</p>
            <p className="mt-1 text-xs text-muted">{f.unit}</p>
            <p className="mt-1 text-xs text-faint">{f.detail}</p>
            <p className="mt-4 border-t border-border pt-3 text-xs leading-relaxed text-muted">{meta.source}</p>
            <p className="mt-2 font-display text-[13px] italic leading-snug text-foreground">{meta.caution}</p>
          </li>
        );
      })}
    </ol>
  );
}

/* ── 02 Rules ──────────────────────────────────────────────────────────── */

function StandingFilter({
  model,
  value,
  onChange,
}: {
  model: ProgrammeModel;
  value: RuleStanding | null;
  onChange: (v: RuleStanding | null) => void;
}) {
  return (
    <div role="group" aria-label="Highlight rules by standing" className="mb-6 flex flex-wrap items-center gap-2 text-xs">
      <span className="mr-1 text-faint">Highlight</span>
      {(["authoritative", "review", "unresolved"] as const).map((s) => (
        <button
          key={s}
          type="button"
          aria-pressed={value === s}
          onClick={() => onChange(value === s ? null : s)}
          disabled={model.standing[s] === 0}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 transition-colors duration-200 disabled:opacity-40",
            value === s ? "border-foreground bg-surface-raised text-foreground" : "border-border text-muted hover:border-border-strong hover:text-foreground"
          )}
        >
          <StandingGlyph standing={s} size={10} />
          {STANDING_META[s].label}
          <span className="font-mono text-faint">{model.standing[s]}</span>
        </button>
      ))}
    </div>
  );
}

function RuleIndex({ pathway, model, standing }: { pathway: Pathway; model: ProgrammeModel; standing: RuleStanding | null }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-8">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-2 text-sm font-medium text-foreground underline-offset-4 hover:underline"
      >
        <ChevronDown size={16} aria-hidden="true" className={cn("transition-transform duration-300", open && "rotate-180")} />
        {open ? "Hide" : "Show"} the rule index ({model.rules.length} rules)
      </button>
      <div className={cn("grid transition-[grid-template-rows] duration-500 ease-[var(--ease-out)]", open ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
        <div className="min-h-0 overflow-hidden">
          <div className="mt-4 flex flex-col gap-8">
            {RULE_GROUP_ORDER.map((g) => {
              const rows = model.rules.filter((r) => r.group === g && (!standing || r.standing === standing));
              if (rows.length === 0) return null;
              return (
                <div key={g}>
                  <p className="font-display text-lg text-foreground">{RULE_GROUP_META[g].title}</p>
                  <p className="text-xs text-muted">{RULE_GROUP_META[g].description}</p>
                  <ul className="mt-3 divide-y divide-border border-y border-border">
                    {rows.map((r) => (
                      <li key={r.rule.rule_id}>
                        <Link
                          href={ruleHref(pathway, r.rule.rule_id)}
                          transitionTypes={FORWARD}
                          tabIndex={open ? 0 : -1}
                          className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 py-3 transition-colors hover:bg-highlight/50 sm:grid-cols-[minmax(0,1fr)_170px_150px_20px] sm:px-2"
                        >
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-medium text-foreground">{r.label}</span>
                            <span className="block font-mono text-[11px] text-faint">{r.rule.rule_id}</span>
                          </span>
                          <span className="hidden items-center gap-1.5 text-xs text-muted sm:flex">
                            <StandingGlyph standing={r.standing} size={10} />
                            {STANDING_META[r.standing].label}
                          </span>
                          <span className="text-right text-xs text-muted sm:text-left">
                            <span className="font-mono text-foreground">{r.gaps.open}</span> open ·{" "}
                            <span className="font-mono text-foreground">{r.gaps.closed_completed}</span> completed
                          </span>
                          <ArrowUpRight size={15} aria-hidden="true" className="hidden text-faint transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 sm:block" />
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── 03 People ─────────────────────────────────────────────────────────── */

const PAGE = 12;

function MemberList({
  pathway,
  programme,
  people,
  state,
  referenceDate,
}: {
  pathway: Pathway;
  programme: Programme;
  people: Map<string, PatientSummaryOut>;
  state: DetailState;
  referenceDate: string | null;
}) {
  const [shown, setShown] = useState(PAGE);
  const cohort = state.segment ? programme.segments.find((s) => s.segment === state.segment)! : programme;
  const ids = [...cohort.patientIds].sort(
    (a, b) => (programme.openGapsByPatient.get(b) ?? 0) - (programme.openGapsByPatient.get(a) ?? 0) || a.localeCompare(b)
  );
  if (ids.length === 0)
    return <EmptyState icon={SearchX} title="Nobody in this segment" description="No members of this programme match the segment and filters." />;

  const from = peopleFiltersToSearchParams(segmentPeopleFilters(pathway, state.segment, state.filters)).toString();
  const via = typeof window === "undefined" ? "" : window.location.pathname + window.location.search;
  const profile = (id: string) =>
    `/people/${encodeURIComponent(id)}?${new URLSearchParams({ from, via }).toString()}#evidence`;
  const segOf = (id: string) => programme.segments.find((s) => s.patientIds.includes(id))?.segment ?? "not_available";

  return (
    <div>
      <ul className="grid grid-cols-1 gap-x-8 sm:grid-cols-2 lg:grid-cols-3">
        {ids.slice(0, shown).map((id, i) => {
          const p = people.get(id);
          const open = programme.openGapsByPatient.get(id) ?? 0;
          return (
            <li key={id} className="reveal-fade border-b border-border" style={{ "--i": i % PAGE } as React.CSSProperties}>
              <Link
                href={profile(id)}
                transitionTypes={FORWARD}
                className="group flex items-center gap-3 py-3 transition-colors hover:bg-highlight/50 sm:px-2"
              >
                <SegmentGlyph segment={segOf(id)} size={12} />
                <span className="min-w-0 flex-1">
                  <span className="block font-mono text-[13px] font-semibold text-foreground group-hover:text-accent">{id}</span>
                  <span className="block truncate text-xs text-muted">
                    {p ? `${ageLabel(p.date_of_birth, referenceDate)} · ${sexLabel(p.sex)} · ${regionLabel(p.region_id)}` : ""}
                  </span>
                </span>
                <span className="text-right">
                  {open > 0 ? (
                    <span className="inline-flex items-center gap-1 text-sm font-medium text-foreground">
                      <StatusGlyph status="due" size={12} />
                      <span className="tabular-nums">{open}</span>
                      <span className="sr-only">open gaps in this programme</span>
                    </span>
                  ) : (
                    <span className="text-xs text-faint">{historyMeta(p?.history_by_pathway[pathway]).label}</span>
                  )}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        {shown < ids.length && (
          <button type="button" onClick={() => setShown((n) => n + PAGE * 2)} className={buttonClass("secondary")}>
            Show more ({ids.length - shown} remaining)
          </button>
        )}
        <p className="text-xs text-faint">
          {Math.min(shown, ids.length)} of {ids.length} shown · open-gap counts are gap records under this programme’s rules
        </p>
      </div>
    </div>
  );
}

/* ── 04 Distribution ───────────────────────────────────────────────────── */

function Bars({ rows, total, label, color }: { rows: { key: string; label: string; count: number }[]; total: number; label: string; color: string }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <div>
      <p className="mb-3 text-xs font-medium text-faint">{label}</p>
      <ul className="flex flex-col gap-2.5">
        {rows.map((r, i) => (
          <li key={r.key} className="grid grid-cols-[96px_minmax(0,1fr)_56px] items-center gap-3 text-sm">
            <span className="truncate text-muted">{r.label}</span>
            <span className="h-2 rounded-full bg-surface-sunken">
              <span
                className="grow-x block h-2 rounded-full"
                style={{ width: `${(r.count / max) * 100}%`, backgroundColor: color, "--i": i } as React.CSSProperties}
              />
            </span>
            <span className="text-right font-mono text-xs tabular-nums text-foreground">
              {r.count}
              {total > 0 && <span className="ml-1 text-faint">{Math.round((r.count / total) * 100)}%</span>}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Distribution({ pathway, state, programme, data }: { pathway: Pathway; state: DetailState; programme: Programme | null; data: Data }) {
  const ages = useAgeBands(pathway, { region_id: state.filters.region_id, sex: state.filters.sex }, 0);
  const model = data.population.status === "ready" ? data.population.data : null;
  return (
    <div className="grid grid-cols-1 gap-10 md:grid-cols-3">
      <ResourceView resource={ages} what="Age groups" loading={<LoadingState rows={4} />}>
        {(a) => {
          const noDob = a.total - a.bands.reduce((n, b) => n + b.count, 0);
          return (
            <div>
              <Bars color={PROGRAMME_COLOR[pathway].paper} label="Age group (backend)" total={a.total} rows={a.bands.map((b) => ({ key: b.band, label: b.label, count: b.count }))} />
              <Footnote>
                {noDob > 0 ? `${noDob} members have no recorded date of birth and are in no age group. ` : ""}
                Region and sex filters apply; the age-group filter does not.
              </Footnote>
            </div>
          );
        }}
      </ResourceView>
      {model && programme ? (
        <>
          <Bars color={PROGRAMME_COLOR[pathway].paper} label="Sex" total={programme.people} rows={model.bySex.map((s) => ({ key: s.key, label: s.label, count: s.count }))} />
          <Bars
            color={PROGRAMME_COLOR[pathway].paper}
            label="Region"
            total={programme.people}
            rows={model.byRegion.filter((r) => r.total > 0).map((r) => ({ key: String(r.regionId), label: r.label, count: r.total }))}
          />
        </>
      ) : (
        <div className="md:col-span-2">
          <ResourceView resource={data.population} what="Programme members" onRetry={data.retry} loading={<LoadingState rows={4} />}>
            {() => null}
          </ResourceView>
        </div>
      )}
    </div>
  );
}

/* ── 05 Open questions ─────────────────────────────────────────────────── */

function OpenQuestions({ model, pathway }: { model: ProgrammeModel; pathway: Pathway }) {
  if (model.openQuestions.length === 0)
    return <p className="text-sm text-muted">No open questions are linked to this programme’s rules.</p>;
  const ruleIds = new Set(model.rules.map((r) => r.rule.rule_id));
  return (
    <ul className="divide-y divide-border border-y border-border">
      {model.openQuestions.map((q, i) => (
        <li key={q.oq_id} className="reveal-fade" style={{ "--i": i } as React.CSSProperties}>
          <details className="group py-4">
            <summary className="flex cursor-pointer list-none items-start gap-4">
              <span className="mt-0.5 w-28 shrink-0 font-mono text-[11px] text-faint">{q.oq_id.replace("OQ-", "")}</span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-foreground">{q.title}</span>
                <span className="mt-0.5 block text-xs text-muted">
                  {q.category} · {q.status}
                </span>
              </span>
              <ChevronDown size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-faint transition-transform duration-300 group-open:rotate-180" />
            </summary>
            <div className="mt-3 pl-0 text-sm leading-relaxed text-muted sm:pl-32">
              <p>{q.detail}</p>
              {q.resolve_via && <p className="mt-2 text-xs text-faint">Resolve via: {q.resolve_via}</p>}
              <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
                {q.rule_ids
                  .filter((id) => ruleIds.has(id))
                  .map((id) => (
                    <Link key={id} href={ruleHref(pathway, id)} transitionTypes={FORWARD} className="font-mono text-accent underline-offset-4 hover:underline">
                      {id}
                    </Link>
                  ))}
              </p>
            </div>
          </details>
        </li>
      ))}
    </ul>
  );
}

