"""Response/request models of `/api/v1/population/*` (aggregates only; no patient fields)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.population.config import PopulationThresholds


class AggregationStatusOut(BaseModel):
    run_id: str
    status: str
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    engine_version: str
    data_version: str | None
    config_version: int | None
    source_run_id: str | None
    as_of: date | None
    complete_through: date | None
    latest_data_at: datetime | None
    error_code: str | None
    summary: dict[str, Any] = Field(default_factory=dict)
    stale: bool = False
    data_changed: bool = False
    refresh_scheduled: bool = False


class PrivacyOut(BaseModel):
    min_cell_size: int
    method: str = "primary_cohort_and_complementary_cell_suppression"
    notice: str = ("Counts between 1 and min_cell_size - 1, values derivable from them, and their "
                   "complementary cells are returned as null and listed in `suppressed`.")


class AreaOut(BaseModel):
    area_id: str
    level: str
    parent_area_id: str | None
    name: str
    name_en: str
    name_ar: str | None
    region_id: int | None
    source: str
    verification_status: str
    boundary: dict[str, Any] | None = None
    reference_point: dict[str, Any] | None = None


class TrendOut(BaseModel):
    direction: str
    reason_codes: list[str]
    absolute_change: int | None
    percentage_change: float | None


class DiseaseMetricsOut(BaseModel):
    condition_code: str
    condition_name: str
    period: str
    period_days: int
    current_start: date
    current_end: date
    previous_start: date
    previous_end: date
    population: int | None
    new_cases: int | None
    previous_new_cases: int | None
    patients_with_condition: int | None
    existing_patients: int | None
    prevalence: float | None
    previous_prevalence: float | None
    prevalence_status: str
    denominator_basis: str
    completeness: float | None
    undated_patients: int | None
    duplicate_records: int
    history_complete: bool
    trend: TrendOut
    suppressed: list[str] = Field(default_factory=list)


class HotspotOut(BaseModel):
    area: AreaOut
    condition_code: str
    condition_name: str
    classification: str
    reason_codes: list[str]
    supporting_metrics: dict[str, Any]
    thresholds: dict[str, Any]
    comparison_period: str
    current_start: date
    current_end: date
    previous_start: date
    previous_end: date
    detected_at: datetime | None
    data_freshness_at: datetime | None
    method: str
    statistical_significance: str
    notice: str = "Threshold-based signal of recorded counts; not a confirmed outbreak."
    suppressed: list[str] = Field(default_factory=list)


class _Envelope(BaseModel):
    is_synthetic: bool = True
    as_of: date
    complete_through: date
    latest_data_at: datetime | None
    aggregation: AggregationStatusOut
    privacy: PrivacyOut
    disclaimer: str


class MapAreaOut(BaseModel):
    area: AreaOut
    population: int | None
    metric_value: float | None
    disease: DiseaseMetricsOut | None
    hotspot_classification: str | None
    active_alerts: int
    preventive_coverage: float | None
    open_care_gaps: int | None
    care_facilities: int | None
    facility_association: str
    facility_point_extent: dict[str, Any] | None
    data_quality: dict[str, Any]
    suppressed: list[str] = Field(default_factory=list)


class MapOut(_Envelope):
    condition: str | None
    period: str
    geography: str
    metric: str
    cohort: str
    bbox: list[float] | None
    excluded_without_geometry: int
    total: int
    limit: int
    offset: int
    items: list[MapAreaOut]


class TrendAreaOut(BaseModel):
    area: AreaOut
    comparisons: dict[str, DiseaseMetricsOut]
    series: list[dict[str, Any]]


class TrendsOut(_Envelope):
    condition: str
    geography: str | None
    cohort: str
    total: int
    limit: int
    offset: int
    items: list[TrendAreaOut]


class HotspotsOut(_Envelope):
    condition: str | None
    period: str
    min_classification: str
    total: int
    limit: int
    offset: int
    items: list[HotspotOut]


class AlertEventOut(BaseModel):
    event_id: str
    event_type: str
    from_status: str | None
    to_status: str | None
    severity: str | None
    actor_user_id: str | None
    actor_role: str | None
    run_id: str | None
    occurred_at: datetime
    note: str | None
    details: dict[str, Any]


class AlertOut(BaseModel):
    alert_id: str
    area_id: str
    area: AreaOut | None
    category: str
    condition_code: str | None
    condition_name: str | None
    severity: str
    title: str
    explanation: str
    metrics: dict[str, Any]
    thresholds: dict[str, Any]
    period_key: str | None
    period_start: date | None
    period_end: date | None
    first_detected_at: datetime
    last_detected_at: datetime
    data_freshness_at: datetime | None
    status: str
    condition_active: bool
    occurrence_count: int
    acknowledged_by: str | None
    acknowledged_at: datetime | None
    investigating_by: str | None
    investigating_at: datetime | None
    closed_by: str | None
    closed_at: datetime | None
    allowed_transitions: list[str]
    suppressed: list[str] = Field(default_factory=list)


class AlertDetailOut(AlertOut):
    history: list[AlertEventOut]


class AlertsOut(BaseModel):
    is_synthetic: bool = True
    total: int
    limit: int
    offset: int
    items: list[AlertOut]
    privacy: PrivacyOut


class AlertPatchIn(BaseModel):
    status: Literal["ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "DISMISSED"]
    note: str | None = Field(default=None, max_length=500)


class AreaConditionOut(BaseModel):
    condition_code: str
    condition_name: str
    current: dict[str, Any]
    comparisons: dict[str, DiseaseMetricsOut]
    series: list[dict[str, Any]]
    hotspot: HotspotOut
    data_quality: dict[str, Any]


class AreaDetailOut(_Envelope):
    area: AreaOut
    ancestors: list[AreaOut]
    children: list[AreaOut]
    cohort: str
    population: dict[str, int | None]
    unassigned_local_area_population: int | None
    conditions: list[AreaConditionOut]
    active_alerts: list[AlertOut]
    facilities: dict[str, Any]
    preventive_care: dict[str, Any] | None
    data_quality: dict[str, Any]
    suppressed: list[str] = Field(default_factory=list)


class SummaryOut(_Envelope):
    total_population: int | None
    conditions_monitored: list[dict[str, str]]
    areas_monitored: int
    areas_with_increasing_cases: int
    increasing: list[dict[str, Any]]
    comparison_period: str
    active_hotspots: int
    hotspots_by_classification: dict[str, int]
    active_alerts: int
    alerts_by_severity: dict[str, int]
    preventive_care: dict[str, Any]
    latest_aggregation_at: datetime | None


class UpdatesOut(BaseModel):
    aggregation_status: str
    last_aggregation_at: datetime | None
    latest_aggregated_data_at: datetime | None
    data_changed_since_aggregation: bool | None
    staleness_seconds: float | None
    stale: bool | None
    latest_run: AggregationStatusOut | None
    dataset_version: dict[str, Any]
    recommended_poll_seconds: dict[str, int]


class ThresholdConfigOut(BaseModel):
    organization_scope: str
    version: int
    is_default: bool
    updated_at: datetime | None
    updated_by: str | None
    thresholds: PopulationThresholds
    min_cell_size: int
