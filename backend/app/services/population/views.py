"""Shape snapshot data for the API: localization and privacy suppression (never raw counts)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.core.i18n import t
from app.models.population import PopulationAlert
from app.services.population.alerts import TRANSITIONS
from app.services.population.config import PopulationThresholds
from app.services.population.engine import classify_hotspot
from app.services.population.privacy import Suppressor
from app.services.population.service import SnapshotView
from app.services.population.vocabulary import CONDITIONS

DISEASE_COUNTS = ("new_cases", "previous_new_cases", "patients_with_condition", "existing_patients",
                  "undated_patients")
CARE_COUNTS = ("in_scope_patients", "patients_with_open_gap", "in_scope_patients_with_open_gap", "open_care_gaps")
CARE_PERIOD_COUNTS = ("screening_completions", "previous_screening_completions", "care_gaps_identified",
                      "previous_care_gaps_identified", "follow_up_completed", "follow_up_eligible_gaps",
                      "previous_follow_up_completed", "previous_follow_up_eligible_gaps")
ALERT_METRIC_COUNTS = ("population", "new_cases", "previous_new_cases", "patients_with_condition",
                       "in_scope_patients", "in_scope_patients_with_open_gap", "open_care_gaps",
                       "follow_up_completed", "follow_up_eligible_gaps", "previous_follow_up_completed",
                       "previous_follow_up_eligible_gaps", "absolute_change")
_ALERT_INTERNAL = ("message_key", "title_key", "message_params")


def condition_name(code: str | None, locale: str) -> str | None:
    if code is None:
        return None
    c = CONDITIONS[code]
    return c.name_ar if locale == "ar" else c.name_en


class View:
    def __init__(self, sv: SnapshotView, locale: str, k: int) -> None:
        self.sv, self.snap, self.locale = sv, sv.snapshot, locale
        self.areas = self.snap["areas"]
        self.sup = Suppressor(self.snap, k)
        self.k = k
        self.thresholds = PopulationThresholds.model_validate(self.snap["thresholds"])

    # --- envelope ---------------------------------------------------------------------------

    def envelope(self) -> dict[str, Any]:
        from app.services.population.vocabulary import DISCLAIMER

        run = self.sv.run
        return {
            "as_of": self.snap["as_of"], "complete_through": self.snap["complete_through"],
            "latest_data_at": self.snap["latest_data_at"],
            "aggregation": {**run, "stale": self.sv.stale, "data_changed": self.sv.data_changed,
                            "refresh_scheduled": self.sv.refresh_scheduled},
            "privacy": {"min_cell_size": self.k}, "disclaimer": DISCLAIMER,
        }

    # --- areas ------------------------------------------------------------------------------

    def area(self, area_id: str) -> dict[str, Any]:
        a = self.areas[area_id]["area"]
        return {**a, "name": (a["name_ar"] if self.locale == "ar" and a["name_ar"] else a["name_en"])}

    def ancestors(self, area_id: str) -> list[dict[str, Any]]:
        out, parent = [], self.areas[area_id]["area"]["parent_area_id"]
        while parent:
            out.insert(0, self.area(parent))
            parent = self.areas[parent]["area"]["parent_area_id"]
        return out

    def children(self, area_id: str) -> list[dict[str, Any]]:
        return [self.area(a) for a, e in sorted(self.areas.items()) if e["area"]["parent_area_id"] == area_id]

    def population(self, area_id: str, cohort: str) -> int | None:
        if self.areas[area_id]["population"] is None:
            return None
        return self.sup.value(area_id, ("population", cohort))

    def unassigned(self, area_id: str) -> int | None:
        v = self.areas[area_id].get("unassigned_local_area_population")
        return None if v is None or self.sup.remainder_hidden(area_id) or self.sup.small(v) else v

    def facilities(self, area_id: str) -> dict[str, Any]:
        fac = dict(self.areas[area_id]["facilities"])
        if self.areas[area_id]["population"] is not None and self.population(area_id, "all") is None:
            fac["patients_per_care_facility"] = None  # would reveal a suppressed population
        return fac

    # --- disease ----------------------------------------------------------------------------

    def disease(self, area_id: str, cond: str, cohort: str, period: str) -> dict[str, Any]:
        base = ("conditions", cond, "periods", cohort, period)
        block, suppressed = self.sup.counts(area_id, base, DISEASE_COUNTS)
        pop = self.population(area_id, cohort)
        if pop is None and block["population"]:
            suppressed.append("population")
        block["population"] = pop
        hidden = set(suppressed)
        if hidden & {"patients_with_condition", "population"}:
            block["prevalence"] = None
            suppressed.append("prevalence")
        if hidden & {"existing_patients", "population"}:
            block["previous_prevalence"] = None
            suppressed.append("previous_prevalence")
        trend = dict(block["trend"])
        if hidden & {"new_cases", "previous_new_cases"}:
            trend["absolute_change"] = trend["percentage_change"] = None
            suppressed.append("change")
        return {**block, "trend": trend, "condition_code": cond, "condition_name": condition_name(cond, self.locale),
                "period": period, "suppressed": suppressed}

    def current(self, area_id: str, cond: str, cohort: str) -> dict[str, Any]:
        block, suppressed = self.sup.counts(area_id, ("conditions", cond, "current", cohort),
                                            ("patients_with_condition",))
        pop = self.population(area_id, cohort)
        block["population"] = pop
        if suppressed or pop is None:
            block["prevalence"] = None
            suppressed.append("prevalence")
        return {**block, "suppressed": suppressed}

    def hotspot(self, area_id: str, cond: str, period: str | None = None) -> dict[str, Any]:
        stored = self.areas[area_id]["conditions"][cond]["hotspot"]
        period = period or stored["comparison_period"]
        block = self.areas[area_id]["conditions"][cond]["periods"]["all"][period]
        hs = stored if period == stored["comparison_period"] else classify_hotspot(
            block, self.thresholds.hotspot.model_copy(update={"comparison_period": period})) | {
            "comparison_period": period, "detected_at": stored["detected_at"]}
        shown = self.disease(area_id, cond, "all", period)
        metrics = dict(hs["supporting_metrics"])
        for f in ("population", "new_cases", "previous_new_cases", "prevalence"):
            metrics[f] = shown[f]
        if "change" in shown["suppressed"]:
            metrics["absolute_change"] = metrics["percentage_change"] = None
        return {
            **{k: hs[k] for k in ("classification", "reason_codes", "thresholds", "method",
                                  "statistical_significance", "comparison_period", "detected_at")},
            "supporting_metrics": metrics, "area": self.area(area_id), "condition_code": cond,
            "condition_name": condition_name(cond, self.locale),
            **{k: block[k] for k in ("current_start", "current_end", "previous_start", "previous_end")},
            "data_freshness_at": self.snap["latest_data_at"], "suppressed": shown["suppressed"],
        }

    def series(self, area_id: str, cond: str) -> list[dict[str, Any]]:
        out = []
        for m in self.areas[area_id]["conditions"][cond]["series"]:
            hidden = area_id in self.sup.small_areas or self.sup.small(m["new_cases"])
            out.append({**m, "new_cases": None if hidden else m["new_cases"], "suppressed": hidden})
        return out

    # --- care -------------------------------------------------------------------------------

    def care(self, area_id: str, cohort: str, period: str) -> dict[str, Any] | None:
        if self.areas[area_id].get("care") is None:
            return None
        block, suppressed = self.sup.counts(area_id, ("care", cohort), CARE_COUNTS)
        if {"in_scope_patients", "in_scope_patients_with_open_gap"} & set(suppressed):
            block["preventive_coverage"] = None
            suppressed.append("preventive_coverage")
        per, psup = self.sup.counts(area_id, ("care", cohort, "periods", period), CARE_PERIOD_COUNTS)
        if area_id in self.sup.small_areas:
            psup = list(CARE_PERIOD_COUNTS)
            per.update(dict.fromkeys(CARE_PERIOD_COUNTS))
        for rate, inputs in (("follow_up_completion_rate", ("follow_up_completed", "follow_up_eligible_gaps")),
                             ("previous_follow_up_completion_rate",
                              ("previous_follow_up_completed", "previous_follow_up_eligible_gaps"))):
            if set(inputs) & set(psup):
                per[rate] = None
                psup.append(rate)
        block.pop("periods", None)
        return {**block, "period": period, "period_metrics": {**per, "suppressed": psup}, "suppressed": suppressed}

    # --- alerts -----------------------------------------------------------------------------

    def alert(self, a: PopulationAlert) -> dict[str, Any]:
        metrics, suppressed = self.sup.primary({k: v for k, v in a.metrics.items() if k not in _ALERT_INTERNAL},
                                               ALERT_METRIC_COUNTS)
        if "population" in suppressed and "patients_per_care_facility" in metrics:
            metrics["patients_per_care_facility"] = None
            suppressed.append("patients_per_care_facility")
        params = dict(a.metrics.get("message_params") or {})
        if a.category in ("case_increase", "disease_burden"):
            for key in ("current", "previous", "count"):
                if self.sup.small(params.get(key)):
                    params[key] = f"<{self.k}"
                    if key == "previous":
                        params["change"] = "n/a"
        if self.locale == "ar":
            params = {**params, "area": self.area(a.area_id)["name"] if a.area_id in self.areas else params.get("area"),
                      "condition": condition_name(a.condition_code, "ar") or params.get("condition")}
        title = t(a.metrics["title_key"], self.locale, **params) if "title_key" in a.metrics else a.title
        explanation = (t(a.metrics["message_key"], self.locale, **params)
                       if "message_key" in a.metrics else a.explanation)
        return {
            **{k: getattr(a, k) for k in (
                "alert_id", "area_id", "category", "condition_code", "severity", "thresholds", "period_key",
                "period_start", "period_end", "first_detected_at", "last_detected_at", "data_freshness_at",
                "status", "condition_active", "occurrence_count", "acknowledged_by", "acknowledged_at",
                "investigating_by", "investigating_at", "closed_by", "closed_at")},
            "area": self.area(a.area_id) if a.area_id in self.areas else None,
            "condition_name": condition_name(a.condition_code, self.locale),
            "title": title, "explanation": explanation, "metrics": metrics,
            "allowed_transitions": sorted(TRANSITIONS[a.status]), "suppressed": suppressed,
        }


def parse_iso(v: str | None) -> date | datetime | None:
    if v is None:
        return None
    return datetime.fromisoformat(v) if "T" in v else date.fromisoformat(v)
