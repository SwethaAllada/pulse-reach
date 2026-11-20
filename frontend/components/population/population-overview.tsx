"use client";

import Link from "next/link";
import type { PopulationModel } from "@/lib/population/model";
import { hasActiveFilters, type PopulationFilters } from "@/lib/population/filters";
import { KpiCard } from "@/components/ui/figure";
import { FORWARD } from "@/components/ui/page-transition";
import { useLocale } from "@/lib/i18n/use-locale";

interface Props {
  model: PopulationModel;
  /** Unfiltered population size from `/dashboard/summary`, when available. */
  populationTotal: number | null;
  filters: PopulationFilters;
}

/** KPI row — every value is derived from API records in the current filter set. */
export function PopulationOverview({ model, populationTotal, filters }: Props) {
  const [ifhas, wcv] = model.programmes;
  const { t, number } = useLocale();
  const filtered = hasActiveFilters(filters);
  const metrics: { label: string; value: React.ReactNode; note: string }[] = [
    {
      label: t("pop.kpi.people"),
      value: model.totalPeople,
      note: filtered && populationTotal !== null ? t("pop.kpi.people_of", { total: populationTotal }) : t("pop.kpi.people_note"),
    },
    {
      label: t("pop.kpi.membership"),
      // Paired figures keep their IFHAS · Well-Child order in both directions.
      value: <span className="ltr-value">{`${number(ifhas.people)} · ${number(wcv.people)}`}</span>,
      note: t("pop.kpi.membership_note"),
    },
    {
      label: t("pop.kpi.with_gap"),
      value: model.peopleWithOpenGap,
      note: t("pop.kpi.of_people", { total: model.totalPeople }),
    },
    {
      label: t("pop.kpi.open_gaps"),
      value: model.openGaps,
      note: t("pop.kpi.open_gaps_note"),
    },
    {
      label: t("pop.kpi.history"),
      value: model.historyAvailablePeople,
      note: t("pop.kpi.history_note", { total: model.totalPeople }),
    },
  ];

  return (
    <section aria-label={t("nav.population_overview")}>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {metrics.map((m, i) => (
          <KpiCard key={m.label} label={m.label} value={m.value} note={m.note} i={i} />
        ))}
        <div
          className="reveal rounded-xl border border-dashed border-border-strong px-4 py-3.5"
          style={{ "--i": 5 } as React.CSSProperties}
        >
          <dt className="text-xs font-medium text-muted">{t("pop.kpi.coverage")}</dt>
          <dd className="mt-1.5 text-sm font-semibold text-foreground">{t("pop.kpi.not_available")}</dd>
          <dd className="mt-1 text-[11px] leading-snug text-faint">
            {t("pop.kpi.coverage_note")}{" "}
            <Link href="/programmes" transitionTypes={FORWARD} className="text-accent underline-offset-4 hover:underline">
              {t("pop.kpi.coverage_link")}
            </Link>
          </dd>
        </div>
      </dl>
    </section>
  );
}
