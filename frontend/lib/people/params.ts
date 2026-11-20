import type { AgeBand, HistoryStatus, PatientQuery } from "@/lib/api/types";
import {
  FILTER_KEYS,
  filtersToSearchParams,
  hasActiveFilters,
  parseFilters,
  type PopulationFilters,
} from "@/lib/population/filters";

/**
 * URL state of the People workspace. Filter keys are the `GET /patients`
 * parameter names (programme/region/sex are shared with the Population
 * workspace); `page` is 1-based and `id` holds an exact synthetic-ID lookup.
 */
export interface PeopleFilters extends PopulationFilters {
  has_open_care_gaps?: boolean;
  history_status?: HistoryStatus;
  age_band?: AgeBand;
}

export type PeopleSort = "open_gaps";

export interface PeopleState {
  filters: PeopleFilters;
  page: number;
  id: string | null;
  /** `null` = API order (patient ID). */
  sort?: PeopleSort | null;
}

export const PAGE_SIZE = 25;
const MAX_ID_LENGTH = 40;

export const CARE_FILTER_KEYS = ["has_open_care_gaps", "history_status", "age_band"] as const;
export const PEOPLE_FILTER_KEYS = [...FILTER_KEYS, ...CARE_FILTER_KEYS] as const;
export type PeopleFilterKey = (typeof PEOPLE_FILTER_KEYS)[number];

export const OPEN_GAP_OPTIONS: { value: "true" | "false"; label: string }[] = [
  { value: "true", label: "With open care gaps" },
  { value: "false", label: "Without open care gaps" },
];

export const HISTORY_OPTIONS: { value: HistoryStatus; label: string }[] = [
  { value: "available", label: "History available" },
  { value: "partial", label: "History partial" },
  { value: "not_available", label: "History unavailable" },
];

/** Bands and boundaries are computed by the backend from date of birth at the reference date. */
export const AGE_BAND_OPTIONS: { value: AgeBand; label: string }[] = [
  { value: "child", label: "Under 18" },
  { value: "adult_18_39", label: "18–39" },
  { value: "adult_40_59", label: "40–59" },
  { value: "adult_60_plus", label: "60 and over" },
];

interface ReadableParams {
  get(name: string): string | null;
}

/**
 * Normalises a typed ID: trims and upper-cases; bare digits expand to the
 * backend's `SYNTH-PAT-NNNNNN` form. Returns null for input the API could
 * never match (so no request is sent).
 */
export function normalizeIdQuery(raw: string | null | undefined): string | null {
  const v = (raw ?? "").trim().toUpperCase();
  if (!v || v.length > MAX_ID_LENGTH) return null;
  if (/^\d{1,6}$/.test(v)) return `SYNTH-PAT-${v.padStart(6, "0")}`;
  return /^[A-Z0-9][A-Z0-9-]*$/.test(v) ? v : null;
}

/** Unknown values are dropped rather than sent to the API. */
export function parsePeopleFilters(params: ReadableParams): PeopleFilters {
  const filters: PeopleFilters = parseFilters(params);
  const gaps = params.get("has_open_care_gaps");
  if (gaps === "true" || gaps === "false") filters.has_open_care_gaps = gaps === "true";
  const history = params.get("history_status");
  if (HISTORY_OPTIONS.some((o) => o.value === history)) filters.history_status = history as HistoryStatus;
  const age = params.get("age_band");
  if (AGE_BAND_OPTIONS.some((o) => o.value === age)) filters.age_band = age as AgeBand;
  return filters;
}

export function peopleFiltersToSearchParams(filters: PeopleFilters): URLSearchParams {
  const params = filtersToSearchParams(filters);
  for (const key of CARE_FILTER_KEYS) {
    const v = filters[key];
    if (v !== undefined) params.set(key, String(v));
  }
  return params;
}

/** Backend query for a People state (filters + sort). */
export function peopleQuery(state: Pick<PeopleState, "filters" | "sort">): PatientQuery {
  return { ...state.filters, ...(state.sort === "open_gaps" ? { sort_by: "open_gaps", sort_dir: "desc" } : {}) };
}

export function parsePeopleState(params: ReadableParams): PeopleState {
  const page = Number(params.get("page"));
  return {
    filters: parsePeopleFilters(params),
    page: Number.isInteger(page) && page >= 1 ? page : 1,
    id: normalizeIdQuery(params.get("id")),
    sort: params.get("sort") === "open_gaps" ? "open_gaps" : null,
  };
}

export function peopleStateToSearchParams(state: PeopleState): URLSearchParams {
  const params = peopleFiltersToSearchParams(state.filters);
  if (state.sort) params.set("sort", state.sort);
  if (state.page > 1) params.set("page", String(state.page));
  if (state.id) params.set("id", state.id);
  return params;
}

export function peopleListHref(state: PeopleState): string {
  const qs = peopleStateToSearchParams(state).toString();
  return qs ? `/people?${qs}` : "/people";
}

/** `/people` link for a set of backend filters (programme drill-downs). */
export function peopleFiltersHref(filters: PeopleFilters, sort: PeopleSort | null = null): string {
  return peopleListHref({ filters, page: 1, id: null, sort });
}

export function activeFilterCount(state: PeopleState): number {
  return PEOPLE_FILTER_KEYS.filter((k) => state.filters[k] !== undefined).length + (state.id ? 1 : 0);
}

export function hasCareFilters(filters: PeopleFilters): boolean {
  return CARE_FILTER_KEYS.some((k) => filters[k] !== undefined);
}

export function hasAnyCriteria(state: PeopleState): boolean {
  return hasActiveFilters(state.filters) || hasCareFilters(state.filters) || state.id !== null || !!state.sort;
}

export function careFilterChips(filters: PeopleFilters): { key: PeopleFilterKey; label: string }[] {
  const chips: { key: PeopleFilterKey; label: string }[] = [];
  if (filters.has_open_care_gaps !== undefined)
    chips.push({
      key: "has_open_care_gaps",
      label: filters.has_open_care_gaps ? "With open care gaps" : "Without open care gaps",
    });
  if (filters.history_status)
    chips.push({ key: "history_status", label: HISTORY_OPTIONS.find((o) => o.value === filters.history_status)!.label });
  if (filters.age_band)
    chips.push({ key: "age_band", label: `Age: ${AGE_BAND_OPTIONS.find((o) => o.value === filters.age_band)!.label}` });
  return chips;
}

/** Profile link that remembers the list state so "Back to People" restores it. */
export function profileHref(personId: string, from: PeopleState): string {
  const qs = peopleStateToSearchParams(from).toString();
  const base = `/people/${encodeURIComponent(personId)}`;
  return qs ? `${base}?from=${encodeURIComponent(qs)}` : base;
}

/** Re-parses the `from` value so only valid People state is ever linked back to. */
export function listHrefFromProfile(from: string | null): string {
  return peopleListHref(parsePeopleState(new URLSearchParams(from ?? "")));
}

/** Population workspace link carrying the shared programme/region/sex filters. */
export function populationHref(filters: PopulationFilters): string {
  const qs = filtersToSearchParams(filters).toString();
  return qs ? `/?${qs}` : "/";
}
