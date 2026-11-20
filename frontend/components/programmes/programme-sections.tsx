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
import { useLocale } from "@/lib/i18n/use-locale";

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
  const { t } = useLocale();
  const referenceDate = data.summary.status === "ready" ? data.summary.data.reference_date : null;
  const name = t(PROGRAMME_META[pathway].name);
  return (
    <div className="flex flex-col gap-16">
      <Plate
        index="01"
        eyebrow={t("prog.sec.evidence_eyebrow")}
        title={t("prog.sec.evidence_title")}
        description={t("prog.sec.evidence_desc")}
      >
        <ResourceView resource={data.programmeSummary} what={t("prog.sec.evidence_what")} onRetry={data.retry} loading={<LoadingState rows={2} label={t("prog.sec.evidence_loading")} />}>
          {(s) => <EvidenceLedger figures={evidenceFigures(s, t)} />}
        </ResourceView>
      </Plate>

      <Plate
        index="02"
        eyebrow={t("prog.sec.rules_eyebrow")}
        title={t("prog.sec.rules_title")}
        description={t("prog.sec.rules_desc")}
        actions={
          <Segmented
            label={t("prog.sec.gap_state")}
            value={state.metric}
            onChange={(metric) => navigate({ metric })}
            options={SPECTRUM_METRICS.map((m) => ({ value: m, label: t(GAP_STATUS_META[m].short) }))}
          />
        }
      >
        <ResourceView resource={data.rules} what={t("prog.sec.rules_what")} onRetry={data.retry}>
          {() =>
            model ? (
              <>
                <StandingFilter model={model} value={state.standing} onChange={(standing) => navigate({ standing })} />
                <RuleSpectrum pathway={pathway} rows={model.rules} metric={state.metric} standing={state.standing} />
                {data.careGaps.status === "forbidden" && (
                  <p className="mt-2 text-xs text-faint">{t("prog.sec.rules_forbidden")}</p>
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
        eyebrow={t("nav.people")}
        title={state.segment ? t(SEGMENT_META[state.segment].label) : t("prog.sec.people_title")}
        description={t(state.segment ? "prog.sec.people_desc_segment" : "prog.sec.people_desc")}
      >
        <ResourceView resource={data.population} what={t("prog.sec.members_what")} onRetry={data.retry}>
          {(d) =>
            programme ? (
              <MemberList pathway={pathway} programme={programme} people={d.patientsById} state={state} referenceDate={referenceDate} />
            ) : null
          }
        </ResourceView>
      </Plate>

      <Plate
        index="04"
        eyebrow={t("prog.sec.dist_eyebrow")}
        title={t("prog.sec.dist_title")}
        description={t("prog.sec.dist_desc")}
      >
        <Distribution pathway={pathway} state={state} programme={programme} data={data} />
      </Plate>

      <Plate
        index="05"
        eyebrow={t("prog.sec.oq_eyebrow")}
        title={t("prog.sec.oq_title")}
        description={t("prog.sec.oq_desc")}
      >
        <ResourceView resource={data.openQuestions} what={t("prog.sec.oq_eyebrow")} onRetry={data.retry}>
          {() => (model ? <OpenQuestions model={model} pathway={pathway} /> : null)}
        </ResourceView>
      </Plate>

      <Plate
        index="06"
        eyebrow={t("prog.sec.trend_eyebrow")}
        title={t("prog.sec.trend_title")}
        description={t("prog.sec.trend_desc")}
      >
        <div className="flex flex-col gap-12">
          <ResourceView resource={data.programmeSummary} what={t("prog.trend.figures", { programme: name })} onRetry={data.retry}>
            {(d) => <ProgrammeTrend data={d} name={name} />}
          </ResourceView>
          <ResourceView resource={data.surveillance} what={t("prog.trend.what")} onRetry={data.retry}>
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
  const { t } = useLocale();
  return (
    <ol className="grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
      {figures.map((f, i) => {
        const meta = EVIDENCE_META[f.cls];
        return (
          <li key={f.cls} className="reveal flex flex-col bg-surface p-5" style={{ "--i": i } as React.CSSProperties}>
            <p className="flex items-center gap-2 text-xs font-semibold text-foreground">
              {EVIDENCE_GLYPH[f.cls]}
              {t(meta.title)}
            </p>
            <p className="figure mt-3 text-[32px] text-foreground">{f.value ?? "—"}</p>
            <p className="mt-1 text-xs text-muted">{f.unit}</p>
            <p className="mt-1 text-xs text-faint">{f.detail}</p>
            <p className="mt-4 border-t border-border pt-3 text-xs leading-relaxed text-muted">{t(meta.source)}</p>
            <p className="mt-2 font-display text-[13px] italic leading-snug text-foreground">{t(meta.caution)}</p>
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
  const { t } = useLocale();
  return (
    <div role="group" aria-label={t("prog.sec.highlight_label")} className="mb-6 flex flex-wrap items-center gap-2 text-xs">
      <span className="me-1 text-faint">{t("prog.sec.highlight")}</span>
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
          {t(STANDING_META[s].label)}
          <span className="font-mono text-faint">{model.standing[s]}</span>
        </button>
      ))}
    </div>
  );
}

function RuleIndex({ pathway, model, standing }: { pathway: Pathway; model: ProgrammeModel; standing: RuleStanding | null }) {
  const [open, setOpen] = useState(false);
  const { t, rich } = useLocale();
  return (
    <div className="mt-8">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-2 text-sm font-medium text-foreground underline-offset-4 hover:underline"
      >
        <ChevronDown size={16} aria-hidden="true" className={cn("transition-transform duration-300", open && "rotate-180")} />
        {t(open ? "prog.sec.index_hide" : "prog.sec.index_show", { count: model.rules.length })}
      </button>
      <div className={cn("grid transition-[grid-template-rows] duration-500 ease-[var(--ease-out)]", open ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
        <div className="min-h-0 overflow-hidden">
          <div className="mt-4 flex flex-col gap-8">
            {RULE_GROUP_ORDER.map((g) => {
              const rows = model.rules.filter((r) => r.group === g && (!standing || r.standing === standing));
              if (rows.length === 0) return null;
              return (
                <div key={g}>
                  <p className="font-display text-lg text-foreground">{t(RULE_GROUP_META[g].title)}</p>
                  <p className="text-xs text-muted">{t(RULE_GROUP_META[g].description)}</p>
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
                            <span className="block truncate text-sm font-medium text-foreground" dir="auto">{r.label}</span>
                            <span className="block font-mono text-[11px] text-faint"><span className="ltr-value">{r.rule.rule_id}</span></span>
                          </span>
                          <span className="hidden items-center gap-1.5 text-xs text-muted sm:flex">
                            <StandingGlyph standing={r.standing} size={10} />
                            {t(STANDING_META[r.standing].label)}
                          </span>
                          <span className="text-end text-xs text-muted sm:text-start">
                            {rich("prog.sec.index_counts", {
                              open: <span className="font-mono text-foreground">{r.gaps.open}</span>,
                              completed: <span className="font-mono text-foreground">{r.gaps.closed_completed}</span>,
                            })}
                          </span>
                          <ArrowUpRight size={15} aria-hidden="true" className="hidden text-faint transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 rtl:-scale-x-100 sm:block" />
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
  const { t } = useLocale();
  const cohort = state.segment ? programme.segments.find((s) => s.segment === state.segment)! : programme;
  const ids = [...cohort.patientIds].sort(
    (a, b) => (programme.openGapsByPatient.get(b) ?? 0) - (programme.openGapsByPatient.get(a) ?? 0) || a.localeCompare(b)
  );
  if (ids.length === 0)
    return <EmptyState icon={SearchX} title={t("prog.sec.nobody_title")} description={t("prog.sec.nobody_desc")} />;

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
                  <span className="block font-mono text-[13px] font-semibold text-foreground group-hover:text-accent"><span className="ltr-value">{id}</span></span>
                  <span className="block truncate text-xs text-muted">
                    {p ? `${ageLabel(p.date_of_birth, referenceDate, t)} · ${sexLabel(p.sex, t)} · ${regionLabel(p.region_id, t)}` : ""}
                  </span>
                </span>
                <span className="text-end">
                  {open > 0 ? (
                    <span className="inline-flex items-center gap-1 text-sm font-medium text-foreground">
                      <StatusGlyph status="due" size={12} />
                      <span className="tabular-nums">{open}</span>
                      <span className="sr-only">{t("prog.sec.open_in_programme")}</span>
                    </span>
                  ) : (
                    <span className="text-xs text-faint">{historyMeta(p?.history_by_pathway[pathway], t).label}</span>
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
            {t("prog.sec.show_more", { count: ids.length - shown })}
          </button>
        )}
        <p className="text-xs text-faint">
          {t("prog.sec.shown", { shown: Math.min(shown, ids.length), total: ids.length })}
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
            <span className="text-end font-mono text-xs tabular-nums text-foreground">
              {r.count}
              {total > 0 && <span className="ms-1 text-faint">{Math.round((r.count / total) * 100)}%</span>}
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
  const { t } = useLocale();
  return (
    <div className="grid grid-cols-1 gap-10 md:grid-cols-3">
      <ResourceView resource={ages} what={t("prog.sec.age_groups")} loading={<LoadingState rows={4} />}>
        {(a) => {
          const noDob = a.total - a.bands.reduce((n, b) => n + b.count, 0);
          return (
            <div>
              <Bars color={PROGRAMME_COLOR[pathway].paper} label={t("prog.sec.age_backend")} total={a.total} rows={a.bands.map((b) => ({ key: b.band, label: t(b.label), count: b.count }))} />
              <Footnote>
                {noDob > 0 ? `${t("prog.sec.no_dob", { count: noDob })} ` : ""}
                {t("prog.sec.age_filters")}
              </Footnote>
            </div>
          );
        }}
      </ResourceView>
      {model && programme ? (
        <>
          <Bars color={PROGRAMME_COLOR[pathway].paper} label={t("pop.filter.sex")} total={programme.people} rows={model.bySex.map((s) => ({ key: s.key, label: s.label, count: s.count }))} />
          <Bars
            color={PROGRAMME_COLOR[pathway].paper}
            label={t("pop.filter.region")}
            total={programme.people}
            rows={model.byRegion.filter((r) => r.total > 0).map((r) => ({ key: String(r.regionId), label: r.label, count: r.total }))}
          />
        </>
      ) : (
        <div className="md:col-span-2">
          <ResourceView resource={data.population} what={t("prog.sec.members_what")} onRetry={data.retry} loading={<LoadingState rows={4} />}>
            {() => null}
          </ResourceView>
        </div>
      )}
    </div>
  );
}

/* ── 05 Open questions ─────────────────────────────────────────────────── */

function OpenQuestions({ model, pathway }: { model: ProgrammeModel; pathway: Pathway }) {
  const { t } = useLocale();
  if (model.openQuestions.length === 0)
    return <p className="text-sm text-muted">{t("prog.sec.oq_none")}</p>;
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
            <div className="mt-3 ps-0 text-sm leading-relaxed text-muted sm:ps-32" dir="auto">
              <p>{q.detail}</p>
              {q.resolve_via && <p className="mt-2 text-xs text-faint">{t("prog.sec.resolve_via", { via: q.resolve_via })}</p>}
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

