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
