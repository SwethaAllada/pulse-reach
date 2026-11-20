/* Geospatial population intelligence (`/population/map`, `/population/alerts`, `/facilities/points`). */

export interface PointExtent {
  min_latitude: number;
  max_latitude: number;
  min_longitude: number;
  max_longitude: number;
}

export interface GeoAreaOut {
  area_id: string;
  level: string;
  parent_area_id: string | null;
  name: string;
  region_id: number | null;
}

export interface MapAreaOut {
  area: GeoAreaOut;
  population: number | null;
  metric_value: number | null;
  disease: { condition_name?: string; new_cases?: number | null; prevalence?: number | null; trend?: { direction: string } } | null;
  hotspot_classification: string | null;
  active_alerts: number;
  preventive_coverage: number | null;
  open_care_gaps: number | null;
  care_facilities: number | null;
  facility_association: string;
  facility_point_extent: PointExtent | null;
  /** Median of the area's associated published care-facility points — approximate; null = unmapped. */
  representative_point?: { latitude: number; longitude: number; facility_count: number; kind: string } | null;
  suppressed: string[];
}

export type MapMetric = "population" | "open_care_gaps" | "preventive_coverage" | "care_facilities" | "new_cases" | "prevalence";
export type ConditionCode = "diabetes_type_2" | "hypertension" | "dyslipidaemia" | "asthma";

export interface MapOut {
  as_of: string;
  complete_through: string;
  period: string;
  geography: string;
  metric: MapMetric;
  condition: string | null;
  privacy: { min_cell_size?: number } & Record<string, unknown>;
  disclaimer: string;
  total: number;
  items: MapAreaOut[];
}

export type Severity = "CRITICAL" | "HIGH" | "MODERATE" | "WATCH";

export interface PopulationAlertOut {
  alert_id: string;
  area_id: string;
  area: GeoAreaOut | null;
  category: string;
  condition_name: string | null;
  severity: Severity;
  title: string;
  explanation: string;
  status: string;
  last_detected_at: string;
}

export interface AlertsOut {
  total: number;
  items: PopulationAlertOut[];
}

export interface FacilityPointOut {
  ch_fid: string | null;
  name: string | null;
  source_layer: string | null;
  facility_type: string | null;
  region_id: number | null;
  city: string | null;
  is_public: boolean | null;
  license_status: string | null;
  latitude: number;
  longitude: number;
  geo_quality: string;
}

export interface FacilityPointsOut {
  governance_notice: string;
  source_layers: string[];
  total: number;
  excluded_without_coordinates: number;
  items: FacilityPointOut[];
}
