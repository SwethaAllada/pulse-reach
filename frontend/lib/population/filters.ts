import type { Pathway, PatientQuery, RegionId, Sex } from "@/lib/api/types";

/**
 * Population filters are exactly the filters `GET /api/v1/patients` accepts.
 * URL keys use the backend parameter names so state round-trips to /people.
 */
export type PopulationFilters = PatientQuery;

export const PATHWAY_OPTIONS: { value: Pathway; label: string; short: string }[] = [
  { value: "ifhas", label: "IFHAS adult screening", short: "IFHAS" },
  { value: "well_child", label: "Well-Child visits", short: "Well-Child" },
];

/** Region ids and labels are loader constants (`official_loader/parse.py` REGIONS). */
export const REGION_OPTIONS: { value: RegionId; label: string }[] = [
  { value: 1, label: "Abu Dhabi" },
  { value: 2, label: "Al Ain" },
  { value: 3, label: "Al Dhafra" },
];

export const SEX_OPTIONS: { value: Sex; label: string }[] = [
  { value: "female", label: "Female" },
  { value: "male", label: "Male" },
];

export const FILTER_KEYS = ["pathway", "region_id", "sex"] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];

interface ReadableParams {
  get(name: string): string | null;
}

/** Unknown or out-of-range values are dropped rather than sent to the API. */
export function parseFilters(params: ReadableParams): PopulationFilters {
  const filters: PopulationFilters = {};
  const pathway = params.get("pathway");
  if (PATHWAY_OPTIONS.some((o) => o.value === pathway)) filters.pathway = pathway as Pathway;
  const region = Number(params.get("region_id"));
  if (REGION_OPTIONS.some((o) => o.value === region)) filters.region_id = region as RegionId;
  const sex = params.get("sex");
  if (SEX_OPTIONS.some((o) => o.value === sex)) filters.sex = sex as Sex;
  return filters;
}

export function filtersToSearchParams(filters: PopulationFilters): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const v = filters[key];
    if (v !== undefined) params.set(key, String(v));
  }
  return params;
}

export function filterKey(filters: PopulationFilters): string {
  return filtersToSearchParams(filters).toString();
}

export function hasActiveFilters(filters: PopulationFilters): boolean {
  return FILTER_KEYS.some((k) => filters[k] !== undefined);
}

export function filterChips(filters: PopulationFilters): { key: FilterKey; label: string }[] {
  const chips: { key: FilterKey; label: string }[] = [];
  if (filters.pathway)
    chips.push({ key: "pathway", label: `Programme: ${pathwayLabel(filters.pathway)}` });
  if (filters.region_id) chips.push({ key: "region_id", label: `Region: ${regionLabel(filters.region_id)}` });
  if (filters.sex)
    chips.push({ key: "sex", label: `Sex: ${SEX_OPTIONS.find((o) => o.value === filters.sex)!.label}` });
  return chips;
}

export function pathwayLabel(p: Pathway, short = false): string {
  const o = PATHWAY_OPTIONS.find((x) => x.value === p)!;
  return short ? o.short : o.label;
}

export function regionLabel(id: number): string {
  return REGION_OPTIONS.find((o) => o.value === id)?.label ?? `Region ${id}`;
}

/** `/people` link carrying only filters the patients API can apply. */
export function peopleHref(filters: PopulationFilters): string {
  const qs = filtersToSearchParams(filters).toString();
  return qs ? `/people?${qs}` : "/people";
}
