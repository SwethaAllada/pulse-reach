import type { FacilityPointOut, MapAreaOut, PopulationAlertOut, Severity } from "@/lib/api/geo-types";

/*
 * Pure helpers for the population map. Nothing here invents geography: areas have no published
 * boundary, so an area is drawn as ONE marker at the backend's representative point — the median of
 * its associated published care-facility coordinates (approximate; not the area's centre, not where
 * patients live). Areas without one are listed as unmapped. Facilities appear only at published
 * coordinates; patients never.
 */

export const SEVERITY_ORDER: Severity[] = ["CRITICAL", "HIGH", "MODERATE", "WATCH"];

export const SEVERITY_META: Record<Severity, { label: string; token: string }> = {
  CRITICAL: { label: "Critical", token: "--danger" },
  HIGH: { label: "High", token: "--status-due" },
  MODERATE: { label: "Moderate", token: "--warning" },
  WATCH: { label: "Watch", token: "--accent-secondary" },
};

export const FACILITY_LAYER_META: Record<string, { label: string; radius: number }> = {
  hospitals: { label: "Hospital", radius: 5.5 },
  health_centres: { label: "Health centre", radius: 3.5 },
  clinics: { label: "Clinic", radius: 3 },
};

/** Highest active-alert severity per area. */
export function maxSeverityByArea(alerts: PopulationAlertOut[]): Map<string, Severity> {
  const out = new Map<string, Severity>();
  for (const a of alerts) {
    const cur = out.get(a.area_id);
    if (!cur || SEVERITY_ORDER.indexOf(a.severity) < SEVERITY_ORDER.indexOf(cur)) out.set(a.area_id, a.severity);
  }
  return out;
}

export function facilitiesGeoJSON(points: FacilityPointOut[]) {
  return {
    type: "FeatureCollection" as const,
    features: points.map((p, i) => ({
      type: "Feature" as const,
      id: i,
      properties: {
        ch_fid: p.ch_fid ?? "",
        name: p.name ?? "Unnamed facility",
        layer: p.source_layer ?? "",
        type: p.facility_type ?? "",
        city: p.city ?? "",
        region_id: p.region_id ?? 0,
        is_public: p.is_public === null ? "unknown" : p.is_public ? "public" : "private",
        license: p.license_status ?? "",
        repaired: p.geo_quality === "swapped_repaired",
      },
      geometry: { type: "Point" as const, coordinates: [p.longitude, p.latitude] },
    })),
  };
}

/** Display a map metric honestly: null = suppressed/unavailable, never 0. */
export function metricText(metric: string, v: number | null): string {
  if (v === null || v === undefined) return "—";
  if (metric === "preventive_coverage" || metric === "prevalence") return `${Math.round(v * 1000) / 10}%`;
  return v.toLocaleString("en");
}

export interface AreaMarkerProps {
  area_id: string;
  name: string;
  severity: Severity | "NONE";
  /** 0–1 share of the largest value in view; -1 = suppressed / unavailable (drawn hollow). */
  size: number;
  label: string;
}

/** One marker per mapped area; size follows the selected measure, colour the highest active alert. */
export function areaMarkersGeoJSON(areas: MapAreaOut[], severity: Map<string, Severity>, metric: string) {
  const mapped = areas.filter((a) => a.representative_point);
  const max = Math.max(0, ...mapped.map((a) => a.metric_value ?? 0));
  return {
    type: "FeatureCollection" as const,
    features: mapped.map((a) => ({
      type: "Feature" as const,
      id: a.area.area_id,
      properties: {
        area_id: a.area.area_id,
        name: a.area.name,
        severity: severity.get(a.area.area_id) ?? "NONE",
        size: a.metric_value === null ? -1 : max > 0 ? Math.sqrt(a.metric_value / max) : 0,
        label: `${a.area.name} · ${metricText(metric, a.metric_value)}`,
      } satisfies AreaMarkerProps,
      geometry: { type: "Point" as const, coordinates: [a.representative_point!.longitude, a.representative_point!.latitude] },
    })),
  };
}

export function unmappedAreas(areas: MapAreaOut[]): MapAreaOut[] {
  return areas.filter((a) => !a.representative_point);
}

/** Map response `period` ("90d", "12m", "1y") as a readable window; unknown codes are shown as-is. */
export function periodLabel(period: string | null | undefined): string | null {
  if (!period) return null;
  const m = /^(\d+)\s*([dwmy])$/i.exec(period.trim());
  if (!m) return period;
  const n = Number(m[1]);
  const unit = { d: "day", w: "week", m: "month", y: "year" }[m[2].toLowerCase() as "d" | "w" | "m" | "y"];
  return `Last ${n} ${unit}${n === 1 ? "" : "s"}`;
}

const SUPPRESSED_FIELD_LABELS: Record<string, string> = {
  population: "Registered population",
  metric_value: "Selected measure",
  open_care_gaps: "Open care gaps",
  preventive_coverage: "Preventive coverage",
  care_facilities: "Care facilities",
  new_cases: "New diagnoses",
  prevalence: "Prevalence",
  disease: "Condition statistics",
  "disease.new_cases": "New diagnoses",
  "disease.prevalence": "Prevalence",
};

/** Friendly names for an area's suppressed fields (deduplicated, original order). */
export function suppressedLabels(fields: string[]): string[] {
  const out: string[] = [];
  for (const f of fields) {
    const label = SUPPRESSED_FIELD_LABELS[f] ?? f.replace(/[._]/g, " ").replace(/^./, (c) => c.toUpperCase());
    if (!out.includes(label)) out.push(label);
  }
  return out;
}

/** "lat, lon" to 5 dp, or null when either coordinate is unpublished. */
export function coordinateText(lat: number | null | undefined, lon: number | null | undefined): string | null {
  if (lat === null || lat === undefined || lon === null || lon === undefined) return null;
  return `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
}

export function sectorLabel(isPublic: boolean | null | undefined): string {
  if (isPublic === null || isPublic === undefined) return "Unknown";
  return isPublic ? "Public" : "Private";
}

export function geoQualityLabel(q: string | null | undefined): string {
  if (!q) return "—";
  if (q === "swapped_repaired") return "Published coordinates were transposed and have been repaired";
  if (q === "ok" || q === "valid") return "As published";
  return q.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

/** Published service flags that are present (null = not published → omitted). */
export function publishedServiceFlags(d: {
  emergency_department: boolean | null;
  pediatric_emergency_department: boolean | null;
  maternity_emergency_care: boolean | null;
  home_care_services: boolean | null;
  inpatient_bed_capacity: number | null;
}): [string, string][] {
  const yn = (v: boolean) => (v ? "Yes" : "No");
  const rows: [string, string][] = [];
  if (d.emergency_department !== null) rows.push(["Emergency department", yn(d.emergency_department)]);
  if (d.pediatric_emergency_department !== null) rows.push(["Paediatric emergency", yn(d.pediatric_emergency_department)]);
  if (d.maternity_emergency_care !== null) rows.push(["Maternity emergency", yn(d.maternity_emergency_care)]);
  if (d.home_care_services !== null) rows.push(["Home care", yn(d.home_care_services)]);
  if (d.inpatient_bed_capacity !== null) rows.push(["Inpatient beds", d.inpatient_bed_capacity.toLocaleString("en")]);
  return rows;
}

/** Legend facility count: "<mappable> mapped of <register_total> published records" when the register summary exists. */
export function facilityCountText(total: number, register?: { mappable: number; register_total: number } | null): string {
  if (register) return `${register.mappable.toLocaleString("en")} mapped of ${register.register_total.toLocaleString("en")} published records`;
  return total.toLocaleString("en");
}
