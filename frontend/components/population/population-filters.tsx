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
import { useLocale } from "@/lib/i18n/use-locale";

type Tone = "ink" | "paper";

interface Props {
  filters: PopulationFilters;
  onChange: (next: PopulationFilters) => void;
  /** `ink` for the plate hero band, `paper` for theme surfaces. */
  tone?: Tone;
  emptyText?: string;
  label?: string;
  /** Hide the programme select (e.g. inside a programme's own workspace). */
  hideProgramme?: boolean;
  /** Extra controls rendered in the same row (e.g. age band). */
  children?: React.ReactNode;
}

const TONES = {
  ink: {
    label: "text-ink-faint",
    select: "border-ink-line bg-ink-raised text-ink-text hover:border-ink-muted focus-visible:border-ink-accent",
    chip: "border-ink-line bg-ink-raised text-ink-text hover:border-ink-accent",
    chipIcon: "text-ink-muted",
    clear: "text-ink-accent hover:text-ink-text",
    empty: "text-ink-faint",
  },
  paper: {
    label: "text-muted",
    select: "border-border-strong bg-surface-raised text-foreground hover:border-faint focus-visible:border-accent",
    chip: "border-border-strong bg-surface-raised text-foreground hover:border-accent",
    chipIcon: "text-muted",
    clear: "text-accent hover:text-foreground",
    empty: "text-faint",
  },
} as const;

export function selectClass(tone: Tone): string {
  return `h-9 min-w-0 cursor-pointer rounded-lg border px-3 text-sm transition-colors duration-200 ${TONES[tone].select}`;
}

export function filterLabelClass(tone: Tone): string {
  return `flex min-w-0 flex-col gap-1.5 text-xs font-medium ${TONES[tone].label}`;
}

/** Filters `GET /api/v1/patients` supports: programme, region, sex. All combinable. */
export function PopulationFilterBar({
  filters,
  onChange,
  tone = "paper",
  emptyText,
  label,
  hideProgramme,
  children,
}: Props) {
  const { t: tr } = useLocale();
  const t = TONES[tone];
  const selectCls = selectClass(tone);
  const labelCls = filterLabelClass(tone);
  const set = <K extends FilterKey>(key: K, value: PopulationFilters[K] | undefined) => {
    const next = { ...filters };
    if (value === undefined) delete next[key];
    else next[key] = value;
    onChange(next);
  };
  const chips = filterChips(filters, tr).filter((c) => !(hideProgramme && c.key === "pathway"));

  return (
    <div role="search" aria-label={label ?? tr("pop.filters_label")}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 lg:flex lg:flex-wrap lg:items-end">
        {!hideProgramme && (
          <label className={`${labelCls} lg:w-56`}>
            {tr("pop.filter.programme")}
            <select
              className={selectCls}
              value={filters.pathway ?? ""}
              onChange={(e) => set("pathway", (e.target.value || undefined) as PopulationFilters["pathway"])}
            >
              <option value="">{tr("pop.filter.all_programmes")}</option>
              {PATHWAY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {tr(o.label)}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className={`${labelCls} lg:w-44`}>
          {tr("pop.filter.region")}
          <select
            className={selectCls}
            value={filters.region_id ?? ""}
            onChange={(e) =>
              set("region_id", e.target.value ? (Number(e.target.value) as PopulationFilters["region_id"]) : undefined)
            }
          >
            <option value="">{tr("pop.filter.all_regions")}</option>
            {REGION_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {tr(o.label)}
              </option>
            ))}
          </select>
        </label>
        <label className={`${labelCls} lg:w-36`}>
          {tr("pop.filter.sex")}
          <select
            className={selectCls}
            value={filters.sex ?? ""}
            onChange={(e) => set("sex", (e.target.value || undefined) as PopulationFilters["sex"])}
          >
            <option value="">{tr("pop.filter.all")}</option>
            {SEX_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {tr(o.label)}
              </option>
            ))}
          </select>
        </label>
        {children}
      </div>

      <div className="mt-3 flex min-h-7 flex-wrap items-center gap-2" aria-live="polite">
        {chips.length === 0 ? (
          <p className={`text-xs ${t.empty}`}>{emptyText ?? tr("pop.filter.showing_all")}</p>
        ) : (
          <>
            <span className="sr-only">{tr("pop.filter.active")}</span>
            {chips.map((c) => (
              <button
                key={c.key}
                type="button"
                onClick={() => set(c.key, undefined)}
                aria-label={tr("pop.filter.remove", { filter: c.label })}
                className={`reveal inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors ${t.chip}`}
              >
                {c.label}
                <X size={12} aria-hidden="true" className={t.chipIcon} />
              </button>
            ))}
            {hasActiveFilters(filters) && (
              <button
                type="button"
                onClick={() => onChange(hideProgramme && filters.pathway ? { pathway: filters.pathway } : {})}
                className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${t.clear}`}
              >
                {tr("pop.filter.clear_all")}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
