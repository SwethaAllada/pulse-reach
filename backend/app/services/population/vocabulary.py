"""Fixed vocabularies of the population-intelligence engine (codes are never translated)."""

from __future__ import annotations

from dataclasses import dataclass

ENGINE_VERSION = "1.0.0"


@dataclass(frozen=True)
class Condition:
    code: str
    icd10_category: str  # reference category only; synthetic records carry no real codes
    name_en: str
    name_ar: str


CONDITIONS: dict[str, Condition] = {
    c.code: c
    for c in (
        Condition("diabetes_type_2", "E11", "Type 2 diabetes mellitus", "داء السكري من النوع الثاني"),
        Condition("hypertension", "I10", "Hypertension", "ارتفاع ضغط الدم"),
        Condition("dyslipidaemia", "E78", "Dyslipidaemia", "اضطراب دهون الدم"),
        Condition("asthma", "J45", "Asthma", "الربو"),
    )
}

# Equal-length, non-overlapping current/previous windows (days).
PERIODS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90, "6m": 182, "12m": 365}
COHORTS = ("all", "adults", "children", "female", "male")
COMPLEMENTARY_COHORTS = {"adults": "children", "children": "adults", "female": "male", "male": "female"}
LEVELS = ("country", "state", "district", "city", "local_area")
ALERT_LEVELS = ("district", "local_area")  # alerts are raised where action is possible

TREND_DIRECTIONS = ("INCREASING", "DECREASING", "STABLE", "INSUFFICIENT_DATA")
HOTSPOT_CLASSES = ("CRITICAL", "HIGH", "MODERATE", "WATCH", "NO_ALERT", "INSUFFICIENT_DATA")
SEVERITY_RANK = {"WATCH": 1, "MODERATE": 2, "HIGH": 3, "CRITICAL": 4}

# Preventive scope: the person has at least one rule evaluation with a decisive, in-programme status.
IN_SCOPE_EVALUATION_STATUSES = ("eligible", "due", "overdue", "upcoming", "completed")
# Care-facility layers of the SDI register used for coverage (pharmacies etc. are reported separately).
CARE_FACILITY_LAYERS = ("hospitals", "health_centres", "clinics")
CHILD_AGE_YEARS = 18

DISCLAIMER = (
    "Aggregates of synthetic records computed deterministically by the backend. Trends and "
    "hotspots are threshold-based signals of recorded counts, not confirmed outbreaks, "
    "statistically tested findings or clinical assessments."
)
