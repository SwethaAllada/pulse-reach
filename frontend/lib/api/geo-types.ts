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

/** How the published register reduces to the mappable subset (same filters as the directory). */
export interface FacilityRegisterSummary {
  /** Every published SDI record, all layers. */
  register_total: number;
  /** Records in the requested layers. */
  in_layers: number;
  excluded_unidentified: number;
  excluded_license_status: number;
  /** Missing, placeholder (0,0) or out-of-bounds coordinates (after the licence filter). */
  excluded_invalid_coordinates: number;
  /** Shown on the map and in the directory. */
  mappable: number;
  license_statuses_included: string[];
}

export interface FacilityPointsOut {
  governance_notice: string;
  source_layers: string[];
  total: number;
  excluded_without_coordinates: number;
  register?: FacilityRegisterSummary;
  items: FacilityPointOut[];
}

/** `GET /facilities/{ch_fid}` — published SDI facts only (no hours, contacts or availability). */
export interface FacilityDetailOut {
  ch_fid: string | null;
  facility_name: string | null;
  facility_name_ar: string | null;
  source_layer: string | null;
  facility_type: string | null;
  subtype: string | null;
  category: string | null;
  region_id: number | null;
  city: string | null;
  is_public: boolean | null;
  license_status: string | null;
  license_no: string | null;
  latitude: number | null;
  longitude: number | null;
  geo_quality: string | null;
  has_insurance: boolean | null;
  inpatient_bed_capacity: number | null;
  specialities_raw: string | null;
  emergency_department: boolean | null;
  pediatric_emergency_department: boolean | null;
  maternity_emergency_care: boolean | null;
  home_care_services: boolean | null;
  source_effective_date: string | null;
  capability_basis: string;
  governance_notice: string;
}
