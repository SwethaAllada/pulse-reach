import type { Pathway, PatientQuery, RegionId, Sex } from "@/lib/api/types";
import type { MessageKey, Translate } from "@/lib/i18n/translate";

/**
 * Population filters are exactly the filters `GET /api/v1/patients` accepts.
 * URL keys use the backend parameter names so state round-trips to /people.
 */
export type PopulationFilters = PatientQuery;

/* Labels are message keys; render them with the bound translator (`useLocale().t`). */
export const PATHWAY_OPTIONS: { value: Pathway; label: MessageKey; short: MessageKey }[] = [
  { value: "ifhas", label: "pop.pathway.ifhas", short: "pop.pathway.ifhas_short" },
  { value: "well_child", label: "pop.pathway.well_child", short: "pop.pathway.well_child_short" },
];

/** Region ids are loader constants (`official_loader/parse.py` REGIONS); names are the official ones. */
export const REGION_OPTIONS: { value: RegionId; label: MessageKey }[] = [
  { value: 1, label: "pop.region.1" },
  { value: 2, label: "pop.region.2" },
  { value: 3, label: "pop.region.3" },
];

export const SEX_OPTIONS: { value: Sex; label: MessageKey }[] = [
  { value: "female", label: "pop.sex.female" },
  { value: "male", label: "pop.sex.male" },
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

export function filterChips(filters: PopulationFilters, t: Translate): { key: FilterKey; label: string }[] {
  const chips: { key: FilterKey; label: string }[] = [];
  if (filters.pathway) chips.push({ key: "pathway", label: t("pop.chip.programme", { value: pathwayLabel(filters.pathway, t) }) });
  if (filters.region_id) chips.push({ key: "region_id", label: t("pop.chip.region", { value: regionLabel(filters.region_id, t) }) });
  if (filters.sex) chips.push({ key: "sex", label: t("pop.chip.sex", { value: sexLabel(filters.sex, t) }) });
  return chips;
}

export function pathwayLabel(p: Pathway, t: Translate, short = false): string {
  const o = PATHWAY_OPTIONS.find((x) => x.value === p)!;
  return t(short ? o.short : o.label);
}

export function regionLabel(id: number, t: Translate): string {
  const o = REGION_OPTIONS.find((x) => x.value === id);
  return o ? t(o.label) : t("pop.region.unknown", { id: String(id) });
}

/** `female` / `male`; anything else (incl. missing) is "Not recorded". */
export function sexLabel(sex: string | null | undefined, t: Translate): string {
  return sex === "female" || sex === "male" ? t(`pop.sex.${sex}`) : t("pop.sex.not_recorded");
}

/** `/people` link carrying only filters the patients API can apply. */
export function peopleHref(filters: PopulationFilters): string {
  const qs = filtersToSearchParams(filters).toString();
  return qs ? `/people?${qs}` : "/people";
}
