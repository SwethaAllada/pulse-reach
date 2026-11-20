"""Configurable, explainable thresholds (organization-specific, defaults in code).

The defaults are demonstration values for the synthetic dataset — not clinical, epidemiological
or Department of Health standards. Every hotspot and alert echoes the thresholds it used.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.population.vocabulary import CONDITIONS, PERIODS

PeriodKey = Literal["7d", "30d", "90d", "6m", "12m"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrendThresholds(_Strict):
    min_trend_cases: int = Field(3, ge=1, description="Cases across both periods below this -> INSUFFICIENT_DATA")
    min_absolute_change: int = Field(2, ge=1)
    stable_band_percentage: float = Field(0.20, ge=0, le=10)
    min_population: int = Field(20, ge=1)
    min_completeness: float = Field(0.8, ge=0, le=1)


class SeverityTier(_Strict):
    severity: Literal["MODERATE", "HIGH", "CRITICAL"]
    min_absolute_increase: int = Field(ge=1)
    min_percentage_increase: float = Field(ge=0)


class HotspotThresholds(_Strict):
    comparison_period: PeriodKey = "90d"
    min_cases: int = Field(5, ge=1)
    min_absolute_increase: int = Field(3, ge=1)
    min_percentage_increase: float = Field(0.25, ge=0)
    min_population: int = Field(20, ge=1)
    min_completeness: float = Field(0.8, ge=0, le=1)
    tiers: list[SeverityTier] = Field(
        default_factory=lambda: [
            SeverityTier(severity="MODERATE", min_absolute_increase=5, min_percentage_increase=0.5),
            SeverityTier(severity="HIGH", min_absolute_increase=8, min_percentage_increase=1.0),
            SeverityTier(severity="CRITICAL", min_absolute_increase=12, min_percentage_increase=2.0),
        ]
    )

    @model_validator(mode="after")
    def _tiers_escalate(self) -> "HotspotThresholds":
        order = ["MODERATE", "HIGH", "CRITICAL"]
        if [t.severity for t in self.tiers] != order[: len(self.tiers)]:
            raise ValueError("tiers must be listed in the order MODERATE, HIGH, CRITICAL")
        prev_abs, prev_pct = self.min_absolute_increase, self.min_percentage_increase
        for t in self.tiers:
            if t.min_absolute_increase < prev_abs or t.min_percentage_increase < prev_pct:
                raise ValueError("each tier must be at least as strict as the one below it")
            prev_abs, prev_pct = t.min_absolute_increase, t.min_percentage_increase
        return self


def _per_condition(value):
    return lambda: {code: value for code in CONDITIONS}


class AlertThresholds(_Strict):
    burden_min_patients: dict[str, int] = Field(default_factory=_per_condition(30))
    prevalence_max: dict[str, float] = Field(
        default_factory=lambda: {"diabetes_type_2": 0.20, "hypertension": 0.30,
                                 "dyslipidaemia": 0.30, "asthma": 0.15}
    )
    preventive_coverage_target: float = Field(0.30, ge=0, le=1)
    follow_up_decline_percentage_points: float = Field(0.10, gt=0, le=1)
    follow_up_min_gaps: int = Field(10, ge=1)
    follow_up_period: PeriodKey = "90d"
    min_care_facilities: int = Field(10, ge=0)
    min_population: int = Field(20, ge=1)

    @model_validator(mode="after")
    def _known_conditions(self) -> "AlertThresholds":
        for name in ("burden_min_patients", "prevalence_max"):
            unknown = set(getattr(self, name)) - set(CONDITIONS)
            if unknown:
                raise ValueError(f"{name}: unknown condition codes {sorted(unknown)}")
        if any(not 0 < v <= 1 for v in self.prevalence_max.values()):
            raise ValueError("prevalence_max values must be in (0, 1]")
        return self


class PopulationThresholds(_Strict):
    reporting_delay_days: int = Field(14, ge=0, le=90)
    trend: TrendThresholds = Field(default_factory=TrendThresholds)
    hotspot: HotspotThresholds = Field(default_factory=HotspotThresholds)
    alerts: AlertThresholds = Field(default_factory=AlertThresholds)


DEFAULT_THRESHOLDS = PopulationThresholds()
assert set(PERIODS) == {"7d", "30d", "90d", "6m", "12m"}  # noqa: S101 - keep PeriodKey in sync
