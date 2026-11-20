import { describe, expect, it } from "vitest";
import type { FacilityPointOut, MapAreaOut, PopulationAlertOut } from "@/lib/api/geo-types";
import { areaMarkersGeoJSON, facilitiesGeoJSON, maxSeverityByArea, metricText, unmappedAreas } from "./geo";

const area = (id: string, extent: MapAreaOut["facility_point_extent"], alerts = 0, value: number | null = 10): MapAreaOut => ({
  area: { area_id: id, level: "local_area", parent_area_id: "AE-AZ-AD", name: id, region_id: 1 },
  population: 50,
  metric_value: value,
  disease: null,
  hotspot_classification: null,
  active_alerts: alerts,
  preventive_coverage: 0.4,
  open_care_gaps: 10,
  care_facilities: 3,
  facility_association: "matched",
  facility_point_extent: extent,
  representative_point: extent ? { latitude: 24.35, longitude: 54.45, facility_count: 5, kind: "median" } : null,
  suppressed: [],
});
const alert = (area_id: string, severity: PopulationAlertOut["severity"]) =>
  ({ alert_id: `${area_id}-${severity}`, area_id, severity }) as PopulationAlertOut;
const EXT = { min_latitude: 24.3, max_latitude: 24.4, min_longitude: 54.4, max_longitude: 54.5 };

describe("population geo helpers", () => {
  it("keeps the highest active severity per area", () => {
    const m = maxSeverityByArea([alert("A", "WATCH"), alert("A", "HIGH"), alert("A", "MODERATE"), alert("B", "CRITICAL")]);
    expect(m.get("A")).toBe("HIGH");
    expect(m.get("B")).toBe("CRITICAL");
    expect(m.has("C")).toBe(false);
  });

  it("draws one marker per mapped area at its representative point; unmapped areas are listed, never placed", () => {
    const sev = maxSeverityByArea([alert("A", "HIGH")]);
    const areas = [area("A", EXT, 1, 100), area("B", EXT, 0, 25), area("C", null, 2), area("D", EXT, 0, null)];
    const g = areaMarkersGeoJSON(areas, sev, "open_care_gaps");
    expect(g.features.map((f) => f.properties.area_id)).toEqual(["A", "B", "D"]);
    expect(g.features[0].geometry.coordinates).toEqual([54.45, 24.35]);
    expect(g.features[0].properties).toMatchObject({ severity: "HIGH", size: 1 });
    expect(g.features[1].properties).toMatchObject({ severity: "NONE", size: 0.5 });
    expect(g.features[2].properties.size).toBe(-1); // suppressed: hollow, not zero
    expect(g.features[2].properties.label).toBe("D · —");
    expect(unmappedAreas(areas).map((a) => a.area.area_id)).toEqual(["C"]);
  });

  it("plots facilities at their published coordinates and flags repaired ones", () => {
    const f = facilitiesGeoJSON([
      { ch_fid: "X", name: "Clinic", source_layer: "clinics", latitude: 24.1, longitude: 54.2, geo_quality: "swapped_repaired" } as FacilityPointOut,
    ]);
    expect(f.features[0].geometry.coordinates).toEqual([54.2, 24.1]);
    expect(f.features[0].properties.repaired).toBe(true);
  });

  it("shows suppressed or unavailable values as a dash, never zero", () => {
    expect(metricText("open_care_gaps", null)).toBe("—");
    expect(metricText("open_care_gaps", 0)).toBe("0");
    expect(metricText("preventive_coverage", 0.355)).toBe("35.5%");
  });
});
