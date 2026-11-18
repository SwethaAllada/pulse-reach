"use client";

import { X } from "lucide-react";
import {
  PATHWAY_OPTIONS,
  REGION_OPTIONS,
  SEX_OPTIONS,
  filterChips,
  hasActiveFilters,
  type FilterKey,
  type PopulationFilters,
} from "@/lib/population/filters";

interface Props {
  filters: PopulationFilters;
  onChange: (next: PopulationFilters) => void;
}

const SELECT_CLS =
  "h-9 min-w-0 rounded-md border border-ink-line bg-ink-raised px-2.5 text-sm text-ink-text transition-colors hover:border-ink-muted focus-visible:border-ink-accent";

/** Only filters `GET /api/v1/patients` supports: programme, region, sex. All combinable. */
export function PopulationFilterBar({ filters, onChange }: Props) {
  const set = <K extends FilterKey>(key: K, value: PopulationFilters[K] | undefined) => {
    const next = { ...filters };
    if (value === undefined) delete next[key];
    else next[key] = value;
    onChange(next);
  };
  const chips = filterChips(filters);

  return (
    <div role="search" aria-label="Population filters">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 lg:flex lg:flex-wrap lg:items-end">
        <label className="flex min-w-0 flex-col gap-1 text-[11px] font-medium uppercase tracking-[0.08em] text-ink-faint lg:w-56">
          Programme
          <select
            className={SELECT_CLS}
            value={filters.pathway ?? ""}
            onChange={(e) => set("pathway", (e.target.value || undefined) as PopulationFilters["pathway"])}
          >
            <option value="">All programmes</option>
            {PATHWAY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-[11px] font-medium uppercase tracking-[0.08em] text-ink-faint lg:w-44">
          Region
          <select
            className={SELECT_CLS}
            value={filters.region_id ?? ""}
            onChange={(e) =>
              set("region_id", e.target.value ? (Number(e.target.value) as PopulationFilters["region_id"]) : undefined)
            }
          >
            <option value="">All regions</option>
            {REGION_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-[11px] font-medium uppercase tracking-[0.08em] text-ink-faint lg:w-36">
          Sex
          <select
            className={SELECT_CLS}
            value={filters.sex ?? ""}
            onChange={(e) => set("sex", (e.target.value || undefined) as PopulationFilters["sex"])}
          >
            <option value="">All</option>
            {SEX_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-3 flex min-h-7 flex-wrap items-center gap-2" aria-live="polite">
        {chips.length === 0 ? (
          <p className="text-xs text-ink-faint">Showing the whole synthetic population.</p>
        ) : (
          <>
            <span className="sr-only">Active filters:</span>
            {chips.map((c) => (
              <button
                key={c.key}
                type="button"
                onClick={() => set(c.key, undefined)}
                aria-label={`Remove filter ${c.label}`}
                className="inline-flex items-center gap-1.5 rounded-full border border-ink-line bg-ink-raised px-2.5 py-1 text-xs text-ink-text transition-colors hover:border-ink-accent"
              >
                {c.label}
                <X size={12} aria-hidden="true" className="text-ink-muted" />
              </button>
            ))}
            {hasActiveFilters(filters) && (
              <button
                type="button"
                onClick={() => onChange({})}
                className="rounded-md px-2 py-1 text-xs font-medium text-ink-accent transition-colors hover:text-ink-text"
              >
                Clear all
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
