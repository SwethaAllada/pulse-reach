import Link from "next/link";
import type { PopulationModel } from "@/lib/population/model";
import { hasActiveFilters, type PopulationFilters } from "@/lib/population/filters";
import { Figure } from "@/components/ui/figure";
import { FORWARD } from "@/components/ui/page-transition";

interface Props {
  model: PopulationModel;
  /** Unfiltered population size from `/dashboard/summary`, when available. */
  populationTotal: number | null;
  filters: PopulationFilters;
}

/** Inline figure band — every value is derived from API records in the current filter set. */
export function PopulationOverview({ model, populationTotal, filters }: Props) {
  const [ifhas, wcv] = model.programmes;
  const filtered = hasActiveFilters(filters);
  const metrics: { label: string; value: string; note: string }[] = [
    {
      label: "People represented",
      value: String(model.totalPeople),
      note: filtered && populationTotal !== null ? `of ${populationTotal} synthetic people` : "synthetic people",
    },
    {
      label: "Programme membership",
      value: `${ifhas.people} · ${wcv.people}`,
      note: "IFHAS adults · Well-Child children",
    },
    {
      label: "With an open documented gap",
      value: String(model.peopleWithOpenGap),
      note: `of ${model.totalPeople} people`,
    },
    {
      label: "Open documented care gaps",
      value: String(model.openGaps),
      note: "gap records across all rules",
    },
    {
      label: "History available",
      value: String(model.historyAvailablePeople),
      note: `of ${model.totalPeople} people have screening/visit history on record`,
    },
  ];

  return (
    <section aria-label="Population overview">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-3 lg:grid-cols-6 lg:divide-x lg:divide-ink-line">
        {metrics.map((m, i) => (
          <Figure key={m.label} tone="plate" label={m.label} value={m.value} note={m.note} className={i > 0 ? "lg:pl-5" : undefined} i={i} />
        ))}
        <div className="reveal col-span-2 sm:col-span-1 lg:pl-5" style={{ "--i": 5 } as React.CSSProperties}>
          <dt className="text-[11px] font-medium uppercase tracking-[0.12em] text-ink-faint">Programme coverage</dt>
          <dd className="mt-2 text-sm font-medium text-ink-muted">Not available</dd>
          <dd className="mt-1 text-[11px] leading-snug text-ink-faint">
            No per-programme completion rate exists in the API.{" "}
            <Link href="/programmes" transitionTypes={FORWARD} className="text-ink-accent underline-offset-4 hover:underline">
              See documented completions
            </Link>
          </dd>
        </div>
      </dl>
    </section>
  );
}
