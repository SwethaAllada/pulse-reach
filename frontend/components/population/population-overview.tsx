import type { PopulationModel } from "@/lib/population/model";
import { hasActiveFilters, type PopulationFilters } from "@/lib/population/filters";

interface Props {
  model: PopulationModel;
  /** Unfiltered population size from `/dashboard/summary`, when available. */
  populationTotal: number | null;
  filters: PopulationFilters;
}

/** Inline metric band — every value is derived from API records in the current filter set. */
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
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-6 lg:divide-x lg:divide-ink-line">
        {metrics.map((m, i) => (
          <div key={m.label} className={i > 0 ? "lg:pl-5" : undefined}>
            <dt className="text-[11px] font-medium uppercase tracking-[0.08em] text-ink-faint">{m.label}</dt>
            <dd className="mt-1 font-display text-2xl font-semibold tabular-nums text-ink-text sm:text-[28px]">
              {m.value}
            </dd>
            <dd className="text-[11px] leading-snug text-ink-muted">{m.note}</dd>
          </div>
        ))}
        <div className="col-span-2 sm:col-span-1 lg:pl-5">
          <dt className="text-[11px] font-medium uppercase tracking-[0.08em] text-ink-faint">Programme coverage</dt>
          <dd className="mt-1 text-sm font-medium text-ink-muted">Not available</dd>
          <dd className="text-[11px] leading-snug text-ink-faint">
            Completion rates need per-person outcome roll-ups the API does not provide yet.
          </dd>
        </div>
      </dl>
    </section>
  );
}
