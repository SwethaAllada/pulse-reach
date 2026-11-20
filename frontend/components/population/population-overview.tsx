import Link from "next/link";
import type { PopulationModel } from "@/lib/population/model";
import { hasActiveFilters, type PopulationFilters } from "@/lib/population/filters";
import { KpiCard } from "@/components/ui/figure";
import { FORWARD } from "@/components/ui/page-transition";

interface Props {
  model: PopulationModel;
  /** Unfiltered population size from `/dashboard/summary`, when available. */
  populationTotal: number | null;
  filters: PopulationFilters;
}

/** KPI row — every value is derived from API records in the current filter set. */
export function PopulationOverview({ model, populationTotal, filters }: Props) {
  const [ifhas, wcv] = model.programmes;
  const filtered = hasActiveFilters(filters);
  const metrics: { label: string; value: string | number; note: string }[] = [
    {
      label: "People represented",
      value: model.totalPeople,
      note: filtered && populationTotal !== null ? `of ${populationTotal} synthetic people` : "synthetic people",
    },
    {
      label: "Programme membership",
      value: `${ifhas.people} · ${wcv.people}`,
      note: "IFHAS adults · Well-Child children",
    },
    {
      label: "With an open documented gap",
      value: model.peopleWithOpenGap,
      note: `of ${model.totalPeople} people`,
    },
    {
      label: "Open documented care gaps",
      value: model.openGaps,
      note: "gap records across all rules",
    },
    {
      label: "History available",
      value: model.historyAvailablePeople,
      note: `of ${model.totalPeople} people have screening/visit history on record`,
    },
  ];

  return (
    <section aria-label="Population overview">
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {metrics.map((m, i) => (
          <KpiCard key={m.label} label={m.label} value={m.value} note={m.note} i={i} />
        ))}
        <div
          className="reveal rounded-xl border border-dashed border-border-strong px-4 py-3.5"
          style={{ "--i": 5 } as React.CSSProperties}
        >
          <dt className="text-xs font-medium text-muted">Programme coverage</dt>
          <dd className="mt-1.5 text-sm font-semibold text-foreground">Not available</dd>
          <dd className="mt-1 text-[11px] leading-snug text-faint">
            No per-programme completion rate exists in the API.{" "}
            <Link href="/programmes" transitionTypes={FORWARD} className="text-accent underline-offset-4 hover:underline">
              See documented completions
            </Link>
          </dd>
        </div>
      </dl>
    </section>
  );
}
