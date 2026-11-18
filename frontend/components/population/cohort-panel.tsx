"use client";

import Link from "next/link";
import { ArrowLeft, ArrowRight, Info } from "lucide-react";
import type { Cohort, CohortId, PopulationModel } from "@/lib/population/model";
import { pathwayLabel, peopleHref, type PopulationFilters } from "@/lib/population/filters";
import { PROGRAMME_COLOR, SegmentGlyph } from "./segment-glyph";
import { cn } from "@/lib/cn";

interface Props {
  model: PopulationModel;
  selected: Cohort | null;
  filters: PopulationFilters;
  onSelect: (id: CohortId | null) => void;
}

/** Right-hand panel: cohort list when nothing is selected, cohort detail otherwise. */
export function CohortPanel({ model, selected, filters, onSelect }: Props) {
  return (
    <aside
      aria-label="Cohort details"
      aria-live="polite"
      className="flex h-full flex-col rounded-lg border border-ink-line bg-ink-raised/60 p-5"
    >
      {selected ? (
        <CohortDetail cohort={selected} model={model} filters={filters} onSelect={onSelect} />
      ) : (
        <CohortList model={model} onSelect={onSelect} />
      )}
    </aside>
  );
}

function CohortList({ model, onSelect }: { model: PopulationModel; onSelect: (id: CohortId) => void }) {
  return (
    <div>
      <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-faint">
        Cohorts · select to explore
      </p>
      <div className="flex flex-col gap-4">
        {model.programmes.map((prog) => (
          <div key={prog.id}>
            <button
              type="button"
              onClick={() => onSelect(prog.id)}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm font-semibold text-ink-text transition-colors hover:bg-ink-line/60"
            >
              <span
                aria-hidden="true"
                className="size-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: PROGRAMME_COLOR[prog.pathway].ink }}
              />
              {pathwayLabel(prog.pathway)}
              <span className="ml-auto font-mono text-xs tabular-nums text-ink-muted">{prog.people}</span>
            </button>
            <ul className="mt-1 flex flex-col">
              {prog.segments.map((seg) => (
                <li key={seg.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(seg.id)}
                    disabled={seg.people === 0}
                    aria-label={`${pathwayLabel(prog.pathway)} — ${seg.label}: ${seg.people} people`}
                    className="flex w-full items-center gap-2.5 rounded-md py-1 pl-6 pr-2 text-left text-[13px] text-ink-muted transition-colors hover:bg-ink-line/60 hover:text-ink-text disabled:cursor-default disabled:opacity-50 disabled:hover:bg-transparent"
                  >
                    <SegmentGlyph segment={seg.segment!} surface="ink" />
                    <span className="min-w-0 flex-1 truncate">{seg.label}</span>
                    <span className="font-mono text-xs tabular-nums text-ink-text">{seg.people}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      {model.unassignedPeople > 0 && (
        <p className="mt-4 text-[11px] text-ink-faint">
          {model.unassignedPeople} people have no programme history record and are not shown.
        </p>
      )}
    </div>
  );
}

function CohortDetail({
  cohort,
  model,
  filters,
  onSelect,
}: {
  cohort: Cohort;
  model: PopulationModel;
  filters: PopulationFilters;
  onSelect: (id: CohortId | null) => void;
}) {
  const programme = model.programmes.find((p) => p.pathway === cohort.pathway)!;
  const isProgramme = cohort.segment === null;
  const topRules = cohort.gapsByRule.slice(0, 5);
  const maxRule = topRules[0]?.count ?? 0;
  const programmeHref = peopleHref({ ...filters, pathway: cohort.pathway });

  return (
    <div className="flex h-full flex-col">
      <button
        type="button"
        onClick={() => onSelect(null)}
        className="-ml-1 mb-3 inline-flex w-fit items-center gap-1 rounded-md px-1 py-0.5 text-xs text-ink-muted transition-colors hover:text-ink-text"
      >
        <ArrowLeft size={13} aria-hidden="true" /> All cohorts
      </button>

      <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em]" style={{ color: PROGRAMME_COLOR[cohort.pathway].ink }}>
        {pathwayLabel(cohort.pathway)}
        {!isProgramme && <span className="text-ink-faint">· segment</span>}
      </p>
      <h2 className="mt-1 flex items-center gap-2 text-lg font-semibold text-ink-text">
        {cohort.segment && <SegmentGlyph segment={cohort.segment} surface="ink" size={14} />}
        {isProgramme ? "Whole programme" : cohort.label}
      </h2>
      <p className="mt-1.5 text-[13px] leading-relaxed text-ink-muted">{cohort.description}</p>

      <dl className="mt-4 grid grid-cols-2 gap-3 border-y border-ink-line py-3">
        <div>
          <dt className="text-[11px] text-ink-faint">People</dt>
          <dd className="font-display text-2xl font-semibold tabular-nums text-ink-text">{cohort.people}</dd>
          {!isProgramme && (
            <dd className="text-[11px] text-ink-faint">of {programme.people} in programme</dd>
          )}
        </div>
        <div>
          <dt className="text-[11px] text-ink-faint">Open documented gaps</dt>
          <dd className="font-display text-2xl font-semibold tabular-nums text-ink-text">{cohort.openGaps}</dd>
          <dd className="text-[11px] text-ink-faint">gap records, not people</dd>
        </div>
      </dl>

      <div className="mt-4">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-faint">
          Documented gaps by rule
        </p>
        {topRules.length === 0 ? (
          <p className="text-[13px] text-ink-muted">No open documented care gaps in this cohort.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {topRules.map((r) => (
              <li key={r.key} title={r.key}>
                <div className="flex items-baseline justify-between gap-2 text-xs">
                  <span className="truncate text-ink-muted">{r.label}</span>
                  <span className="font-mono tabular-nums text-ink-text">{r.count}</span>
                </div>
                <div className="mt-1 h-1 rounded-full bg-ink-line">
                  <div
                    className="h-1 rounded-full"
                    style={{ width: `${(r.count / maxRule) * 100}%`, backgroundColor: "var(--ink-segment-gap)" }}
                  />
                </div>
              </li>
            ))}
            {cohort.gapsByRule.length > topRules.length && (
              <li className="text-[11px] text-ink-faint">
                + {cohort.gapsByRule.length - topRules.length} more rules
              </li>
            )}
          </ul>
        )}
        {cohort.gapsByType.length > 0 && (
          <p className="mt-3 text-[11px] text-ink-faint">
            By gap type:{" "}
            {cohort.gapsByType.map((t, i) => (
              <span key={t.key}>
                {i > 0 && " · "}
                {t.label} <span className="font-mono text-ink-muted">{t.count}</span>
              </span>
            ))}
          </p>
        )}
      </div>

      <div className="mt-auto pt-5">
        {isProgramme ? (
          <ExploreLink href={programmeHref} disabled={cohort.people === 0}>
            Explore {cohort.people} {cohort.people === 1 ? "person" : "people"}
          </ExploreLink>
        ) : (
          <>
            <p className="flex gap-2 rounded-md border border-ink-line px-3 py-2 text-[12px] leading-relaxed text-ink-muted">
              <Info size={14} aria-hidden="true" className="mt-0.5 shrink-0 text-ink-faint" />
              <span>
                <span className="font-medium text-ink-text">Exploring only this segment is unavailable.</span>{" "}
                The People API cannot yet filter by open care gap or history status, so it would
                return all {programme.people} programme members instead of these {cohort.people}.
              </span>
            </p>
            <ExploreLink href={programmeHref} disabled={programme.people === 0} secondary>
              Explore all {programme.people} {pathwayLabel(cohort.pathway, true)} people
            </ExploreLink>
          </>
        )}
      </div>
    </div>
  );
}

function ExploreLink({
  href,
  disabled,
  secondary,
  children,
}: {
  href: string;
  disabled?: boolean;
  secondary?: boolean;
  children: React.ReactNode;
}) {
  const cls = cn(
    "mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold transition-colors",
    secondary
      ? "border border-ink-line text-ink-text hover:border-ink-accent"
      : "bg-ink-accent text-ink hover:opacity-90"
  );
  if (disabled) {
    return (
      <span aria-disabled="true" className={cn(cls, "cursor-not-allowed opacity-50")}>
        {children}
      </span>
    );
  }
  return (
    <Link href={href} className={cls}>
      {children}
      <ArrowRight size={14} aria-hidden="true" />
    </Link>
  );
}
