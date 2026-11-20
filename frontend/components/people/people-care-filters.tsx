"use client";

import { X } from "lucide-react";
import {
  AGE_BAND_OPTIONS,
  careFilterChips,
  HISTORY_OPTIONS,
  OPEN_GAP_OPTIONS,
  type PeopleFilterKey,
  type PeopleFilters,
  type PeopleSort,
} from "@/lib/people/params";
import { selectClass, filterLabelClass } from "@/components/population/population-filters";

interface Props {
  filters: PeopleFilters;
  sort: PeopleSort | null;
  onChange: (filters: PeopleFilters) => void;
  onSort: (sort: PeopleSort | null) => void;
}

/** Backend-evaluated `GET /patients` filters beyond programme/region/sex, plus sort. */
export function PeopleCareFilters({ filters, sort, onChange, onSort }: Props) {
  const set = <K extends PeopleFilterKey>(key: K, value: PeopleFilters[K] | undefined) => {
    const next = { ...filters };
    if (value === undefined) delete next[key];
    else next[key] = value;
    onChange(next);
  };
  const chips = careFilterChips(filters);

  return (
    <div role="group" aria-label="Care and history filters">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:flex lg:flex-wrap lg:items-end">
        <label className={`${filterLabelClass("paper")} lg:w-52`}>
          Open care gaps
          <select
            className={selectClass("paper")}
            value={filters.has_open_care_gaps === undefined ? "" : String(filters.has_open_care_gaps)}
            onChange={(e) => set("has_open_care_gaps", e.target.value === "" ? undefined : e.target.value === "true")}
          >
            <option value="">Any</option>
            {OPEN_GAP_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className={`${filterLabelClass("paper")} lg:w-48`}>
          History
          <select
            className={selectClass("paper")}
            value={filters.history_status ?? ""}
            onChange={(e) => set("history_status", (e.target.value || undefined) as PeopleFilters["history_status"])}
          >
            <option value="">Any</option>
            {HISTORY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className={`${filterLabelClass("paper")} lg:w-40`}>
          Age group
          <select
            className={selectClass("paper")}
            value={filters.age_band ?? ""}
            onChange={(e) => set("age_band", (e.target.value || undefined) as PeopleFilters["age_band"])}
          >
            <option value="">All ages</option>
            {AGE_BAND_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className={`${filterLabelClass("paper")} lg:ml-auto lg:w-52`}>
          Order
          <select
            className={selectClass("paper")}
            value={sort ?? ""}
            onChange={(e) => onSort(e.target.value === "open_gaps" ? "open_gaps" : null)}
          >
            <option value="">Synthetic ID</option>
            <option value="open_gaps">Most open care gaps first</option>
          </select>
        </label>
      </div>
      {chips.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2" aria-live="polite">
          {chips.map((c) => (
            <button
              key={c.key}
              type="button"
              onClick={() => set(c.key, undefined)}
              aria-label={`Remove filter ${c.label}`}
              className="reveal inline-flex items-center gap-1.5 rounded-full border border-border-strong bg-surface-raised px-2.5 py-1 text-xs text-foreground transition-colors hover:border-accent"
            >
              {c.label}
              <X size={12} aria-hidden="true" className="text-muted" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
