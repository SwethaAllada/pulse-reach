"use client";

import Link from "next/link";
import { ArrowLeft, ArrowRight, Info } from "lucide-react";
import type { Cohort, CohortId, PopulationModel } from "@/lib/population/model";
import { filtersToSearchParams, pathwayLabel, type PopulationFilters } from "@/lib/population/filters";
import { peopleFiltersHref } from "@/lib/people/params";
import { programmeHref as programmeLink, segmentPeopleFilters } from "@/lib/programmes/model";
import { buttonClass } from "@/components/ui/button-styles";
import { FORWARD } from "@/components/ui/page-transition";
import { PROGRAMME_COLOR, SegmentGlyph } from "./segment-glyph";
import { cn } from "@/lib/cn";
import { useLocale } from "@/lib/i18n/use-locale";

interface Props {
  model: PopulationModel;
  selected: Cohort | null;
  filters: PopulationFilters;
  onSelect: (id: CohortId | null) => void;
}

/** Right-hand panel: cohort list when nothing is selected, cohort detail otherwise. */
export function CohortPanel({ model, selected, filters, onSelect }: Props) {
  const { t } = useLocale();
  return (
    <aside
      aria-label={t("pop.panel.label")}
      aria-live="polite"
      className="reveal flex h-full flex-col rounded-xl border border-border bg-surface-raised p-5"
      style={{ "--i": 4 } as React.CSSProperties}
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
  const { t, number } = useLocale();
  return (
    <div>
      <p className="mb-3 text-[15px] font-semibold text-foreground">{t("pop.panel.cohorts")}</p>
      <div className="flex flex-col gap-4">
        {model.programmes.map((prog) => (
          <div key={prog.id}>
            <button
              type="button"
              onClick={() => onSelect(prog.id)}
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-start text-sm font-semibold text-ink-text transition-colors hover:bg-hover"
            >
              <span
                aria-hidden="true"
                className="size-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: PROGRAMME_COLOR[prog.pathway].ink }}
              />
              {pathwayLabel(prog.pathway, t)}
              <span className="ms-auto font-mono text-xs tabular-nums text-ink-muted">{number(prog.people)}</span>
            </button>
            <ul className="mt-1 flex flex-col">
              {prog.segments.map((seg) => (
                <li key={seg.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(seg.id)}
                    disabled={seg.people === 0}
                    aria-label={t("pop.cohort.aria", { programme: pathwayLabel(prog.pathway, t), cohort: seg.label, people: t("pop.people_n", { count: seg.people }) })}
                    className="flex w-full items-center gap-2.5 rounded-md py-1 ps-6 pe-2 text-start text-[13px] text-ink-muted transition-colors hover:bg-hover hover:text-ink-text disabled:cursor-default disabled:opacity-50 disabled:hover:bg-transparent"
                  >
                    <SegmentGlyph segment={seg.segment!} surface="ink" />
                    <span className="min-w-0 flex-1 truncate">{seg.label}</span>
                    <span className="font-mono text-xs tabular-nums text-ink-text">{number(seg.people)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      {model.unassignedPeople > 0 && (
        <p className="mt-4 text-[11px] text-ink-faint">
          {t("pop.panel.unassigned", { count: model.unassignedPeople })}
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
  const { t, tp, number } = useLocale();
  const programme = model.programmes.find((p) => p.pathway === cohort.pathway)!;
  const isProgramme = cohort.segment === null;
  const topRules = cohort.gapsByRule.slice(0, 5);
  const maxRule = topRules[0]?.count ?? 0;
  const programmeHref = peopleFiltersHref(segmentPeopleFilters(cohort.pathway, cohort.segment, filters), "open_gaps");

  return (
    <div key={cohort.id} className="reveal-fade flex h-full flex-col">
      <button
        type="button"
        onClick={() => onSelect(null)}
        className="-ms-1 mb-3 inline-flex w-fit items-center gap-1 rounded-md px-1 py-0.5 text-xs text-ink-muted transition-colors hover:text-ink-text"
      >
        <ArrowLeft size={13} aria-hidden="true" className="rtl:-scale-x-100" /> {t("pop.panel.all_cohorts")}
      </button>

      <p className="flex items-center gap-2 text-xs font-medium" style={{ color: PROGRAMME_COLOR[cohort.pathway].ink }}>
        {pathwayLabel(cohort.pathway, t)}
        {!isProgramme && <span className="text-ink-faint">· {t("pop.panel.segment")}</span>}
      </p>
      <h2 className="mt-1 flex items-center gap-2 text-lg font-semibold text-ink-text">
        {cohort.segment && <SegmentGlyph segment={cohort.segment} surface="ink" size={14} />}
        {isProgramme ? t("pop.panel.whole_programme") : cohort.label}
      </h2>
      <p className="mt-1.5 text-[13px] leading-relaxed text-ink-muted">{cohort.description}</p>

      <dl className="mt-4 grid grid-cols-2 gap-3 border-y border-ink-line py-3">
        <div>
          <dt className="text-[11px] text-ink-faint">{t("pop.panel.people")}</dt>
          <dd className="figure text-2xl text-ink-text">{number(cohort.people)}</dd>
          {!isProgramme && (
            <dd className="text-[11px] text-ink-faint">{t("pop.panel.of_programme", { total: programme.people })}</dd>
          )}
        </div>
        <div>
          <dt className="text-[11px] text-ink-faint">{t("pop.panel.open_gaps")}</dt>
          <dd className="figure text-2xl text-ink-text">{number(cohort.openGaps)}</dd>
          <dd className="text-[11px] text-ink-faint">{t("pop.panel.records_not_people")}</dd>
        </div>
      </dl>

      <div className="mt-4">
        <p className="mb-2 text-xs font-medium text-ink-muted">{t("pop.panel.by_rule")}</p>
        {topRules.length === 0 ? (
          <p className="text-[13px] text-ink-muted">{t("pop.panel.no_gaps")}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {topRules.map((r) => (
              <li key={r.key} title={r.key}>
                <div className="flex items-baseline justify-between gap-2 text-xs">
                  <span className="truncate text-ink-muted" dir="auto">{r.label}</span>
                  <span className="font-mono tabular-nums text-ink-text">{number(r.count)}</span>
                </div>
                <div className="mt-1 h-1 rounded-full bg-ink-line">
                  <div
                    className="grow-x h-1 rounded-full"
                    style={{ width: `${(r.count / maxRule) * 100}%`, backgroundColor: "var(--ink-segment-gap)" }}
                  />
                </div>
              </li>
            ))}
            {cohort.gapsByRule.length > topRules.length && (
              <li className="text-[11px] text-ink-faint">
                {t("pop.panel.more_rules", { count: cohort.gapsByRule.length - topRules.length })}
              </li>
            )}
          </ul>
        )}
        {cohort.gapsByType.length > 0 && (
          <p className="mt-3 text-[11px] text-ink-faint">
            {t("pop.panel.by_type")}{" "}
            {cohort.gapsByType.map((g, i) => (
              <span key={g.key}>
                {i > 0 && " · "}
                {g.label} <span className="font-mono text-ink-muted">{number(g.count)}</span>
              </span>
            ))}
          </p>
        )}
      </div>

      <div className="mt-auto pt-5">
        <ExploreLink href={programmeDetailHref(cohort, filters)} disabled={cohort.people === 0} forward>
          {isProgramme
            ? t("pop.panel.open_programme", { programme: pathwayLabel(cohort.pathway, t, true) })
            : t("pop.panel.open_segment")}
        </ExploreLink>
        <ExploreLink href={programmeHref} disabled={cohort.people === 0} secondary>
          {t("pop.panel.explore", { people: tp("pop.people", cohort.people) })}
        </ExploreLink>
        {!isProgramme && (
          <p className="mt-3 flex gap-2 text-[11px] leading-relaxed text-ink-faint">
            <Info size={13} aria-hidden="true" className="mt-px shrink-0" />
            <span>{t("pop.panel.scope_note")}</span>
          </p>
        )}
      </div>
    </div>
  );
}

function programmeDetailHref(cohort: Cohort, filters: PopulationFilters): string {
  const qs = filtersToSearchParams({ region_id: filters.region_id, sex: filters.sex });
  if (cohort.segment) qs.set("segment", cohort.segment);
  return programmeLink(cohort.pathway, qs);
}

function ExploreLink({
  href,
  disabled,
  secondary,
  forward,
  children,
}: {
  href: string;
  disabled?: boolean;
  secondary?: boolean;
  forward?: boolean;
  children: React.ReactNode;
}) {
  const cls = buttonClass(secondary ? "secondary" : "primary", cn("w-full", secondary ? "mt-2" : "mt-3"));
  if (disabled) {
    return (
      <span aria-disabled="true" className={cn(cls, "cursor-not-allowed opacity-50")}>
        {children}
      </span>
    );
  }
  return (
    <Link href={href} className={cls} transitionTypes={forward ? FORWARD : undefined}>
      {children}
      <ArrowRight size={14} aria-hidden="true" className="rtl:-scale-x-100" />
    </Link>
  );
}
