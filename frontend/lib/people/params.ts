import {
  FILTER_KEYS,
  filtersToSearchParams,
  hasActiveFilters,
  parseFilters,
  type PopulationFilters,
} from "@/lib/population/filters";

/**
 * URL state of the People workspace. Filter keys are the `GET /patients`
 * parameter names (shared with the Population workspace); `page` is 1-based
 * and `id` holds an exact synthetic-ID lookup (`GET /patients/{id}`) — the
 * API has no text search, so nothing else is searchable.
 */
export interface PeopleState {
  filters: PopulationFilters;
  page: number;
  id: string | null;
}

export const PAGE_SIZE = 25;
const MAX_ID_LENGTH = 40;

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

export function parsePeopleState(params: ReadableParams): PeopleState {
  const page = Number(params.get("page"));
  return {
    filters: parseFilters(params),
    page: Number.isInteger(page) && page >= 1 ? page : 1,
    id: normalizeIdQuery(params.get("id")),
  };
}

export function peopleStateToSearchParams(state: PeopleState): URLSearchParams {
  const params = filtersToSearchParams(state.filters);
  if (state.page > 1) params.set("page", String(state.page));
  if (state.id) params.set("id", state.id);
  return params;
}

export function peopleListHref(state: PeopleState): string {
  const qs = peopleStateToSearchParams(state).toString();
  return qs ? `/people?${qs}` : "/people";
}

export function activeFilterCount(state: PeopleState): number {
  return FILTER_KEYS.filter((k) => state.filters[k] !== undefined).length + (state.id ? 1 : 0);
}

export function hasAnyCriteria(state: PeopleState): boolean {
  return hasActiveFilters(state.filters) || state.id !== null;
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
