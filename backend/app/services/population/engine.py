"""Deterministic aggregation, trend, hotspot and alert-candidate engine (pure functions).

Input: `PopulationFacts` (grouped counts) + `PopulationThresholds`. Output: a JSON-serializable
snapshot holding raw aggregate counts (privacy suppression is applied when it is served). No LLM,
no randomness, no wall clock except the `generated_at` stamp passed in.

Metric definitions (never substituted for one another):
- `population`: living registered patients of the organization in the area (denominator).
- `new_cases`: patients whose earliest recorded diagnosis date falls in the window.
- `patients_with_condition`: patients with an active (not resolved) recorded condition at a
  date; undated records count from the date they were first recorded.
- `existing_patients`: patients with the condition already active at the window start.
- `prevalence`: patients_with_condition / population (unavailable without a denominator).
- `open_care_gaps` / `patients_with_open_gap`: preventive-care facts from the evaluation engine.
- `screening_completions`: completed IFHAS screenings + attended well-child visits.

Windows: current = (T - L, T], previous = (T - 2L, T - L] with L in `PERIODS`. Disease windows
end at the complete-through date T = as-of - reporting delay; care and follow-up windows end at
the as-of date (operational records have no reporting delay).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from app.core.i18n import t
from app.services.population.config import PopulationThresholds, TrendThresholds
from app.services.population.facts import ConditionRow, PopulationFacts
from app.services.population.geography import (
    COUNTRY_ID,
    STATE_ID,
    build_hierarchy,
    city_area_id,
    district_id,
    local_area_id,
    local_to_city_key,
)
from app.services.population.vocabulary import (
    ALERT_LEVELS,
    CARE_FACILITY_LAYERS,
    COHORTS,
    CONDITIONS,
    ENGINE_VERSION,
    PERIODS,
)


def _iso(d: date | datetime | None) -> str | None:
    return d.isoformat() if d is not None else None


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 6) if den > 0 else None


def in_cohort(sex: str | None, age_group: str | None, cohort: str) -> bool:
    return (cohort == "all" or (cohort == "adults" and age_group == "adult")
            or (cohort == "children" and age_group == "child") or cohort == sex)


def windows(end: date, days: int) -> dict[str, date]:
    """Exclusive lower bounds and inclusive upper bounds of the current and previous windows."""
    return {"current_end": end, "current_after": end - timedelta(days=days),
            "previous_end": end - timedelta(days=days), "previous_after": end - timedelta(days=2 * days)}


def _window_out(w: dict[str, date]) -> dict[str, str | None]:
    return {"current_start": _iso(w["current_after"] + timedelta(days=1)), "current_end": _iso(w["current_end"]),
            "previous_start": _iso(w["previous_after"] + timedelta(days=1)), "previous_end": _iso(w["previous_end"])}


# --------------------------------------------------------------------------------------------
# Trend and hotspot classification (independently testable)
# --------------------------------------------------------------------------------------------


def classify_trend(current: int, previous: int, *, population: int, history_complete: bool,
                   completeness: float | None, cfg: TrendThresholds) -> dict[str, Any]:
    change = current - previous
    pct = round(change / previous, 6) if previous > 0 else None
    reasons: list[str] = []
    if population < cfg.min_population:
        reasons.append("population_below_minimum")
    if not history_complete:
        reasons.append("history_incomplete")
    if completeness is not None and completeness < cfg.min_completeness:
        reasons.append("completeness_below_minimum")
    if current + previous < cfg.min_trend_cases:
        reasons.append("too_few_cases")
    if reasons:
        direction = "INSUFFICIENT_DATA"
    elif change >= cfg.min_absolute_change and (pct is None or pct >= cfg.stable_band_percentage):
        direction = "INCREASING"
        reasons.append("previous_period_zero" if pct is None else "increase_exceeds_stable_band")
    elif -change >= cfg.min_absolute_change and pct is not None and -pct >= cfg.stable_band_percentage:
        direction = "DECREASING"
        reasons.append("decrease_exceeds_stable_band")
    else:
        direction = "STABLE"
        reasons.append("change_within_stable_band")
    return {"direction": direction, "reason_codes": reasons, "absolute_change": change,
            "percentage_change": pct}


def classify_hotspot(m: dict[str, Any], cfg) -> dict[str, Any]:
    """Threshold rules on one area/condition/period metric block (`cfg`: HotspotThresholds)."""
    cur, prev = m["new_cases"], m["previous_new_cases"]
    change, pct = cur - prev, m["trend"]["percentage_change"]
    reasons: list[str] = []
    if m["population"] < cfg.min_population:
        reasons.append("population_below_minimum")
    if not m["history_complete"]:
        reasons.append("history_incomplete")
    if m["completeness"] is not None and m["completeness"] < cfg.min_completeness:
        reasons.append("completeness_below_minimum")
    if reasons:
        classification = "INSUFFICIENT_DATA"
    else:
        if cur < cfg.min_cases:
            reasons.append("below_min_cases")
        if change < cfg.min_absolute_increase:
            reasons.append("below_min_absolute_increase")
        if prev > 0 and (pct or 0) < cfg.min_percentage_increase:
            reasons.append("below_min_percentage_increase")
        if reasons:
            classification = "NO_ALERT"
        else:
            classification = "WATCH"
            reasons.append("previous_period_zero_absolute_rule" if prev == 0 else "thresholds_met")
            for tier in cfg.tiers:
                if change >= tier.min_absolute_increase and (prev == 0 or pct >= tier.min_percentage_increase):
                    classification = tier.severity
    return {
        "classification": classification,
        "reason_codes": reasons,
        "supporting_metrics": {k: m[k] for k in ("population", "new_cases", "previous_new_cases", "prevalence",
                                                 "completeness")}
        | {"absolute_change": change, "percentage_change": pct},
        "thresholds": cfg.model_dump(),
        "method": "threshold_rules",
        "statistical_significance": "not_assessed",
    }


# --------------------------------------------------------------------------------------------
# Snapshot
# --------------------------------------------------------------------------------------------


def _condition_block(rows: list[ConditionRow], population: int, coverage_start: date | None,
                     end: date, days: int, cfg: TrendThresholds) -> dict[str, Any]:
    w = windows(end, days)
    new_cur = new_prev = total = dated = dups = 0
    for r in rows:
        total += r.n
        dups += r.duplicate_records
        if r.onset_date is not None:
            dated += r.n
            new_cur += r.n if w["current_after"] < r.onset_date <= w["current_end"] else 0
            new_prev += r.n if w["previous_after"] < r.onset_date <= w["previous_end"] else 0
    first_day_prev = w["previous_after"] + timedelta(days=1)
    history_complete = coverage_start is not None and coverage_start <= first_day_prev
    completeness = _ratio(dated, total)
    active_end, active_start = active_at(rows, w["current_end"]), active_at(rows, w["current_after"])
    return {
        "period_days": days, **_window_out(w),
        "population": population,
        "new_cases": new_cur, "previous_new_cases": new_prev,
        "patients_with_condition": active_end, "existing_patients": active_start,
        "prevalence": _ratio(active_end, population), "previous_prevalence": _ratio(active_start, population),
        "prevalence_status": "available" if population > 0 else "unavailable_no_denominator",
        "denominator_basis": "current_registered_population",
        "completeness": completeness, "undated_patients": total - dated, "duplicate_records": dups,
        "history_complete": history_complete,
        "trend": classify_trend(new_cur, new_prev, population=population, history_complete=history_complete,
                                completeness=completeness, cfg=cfg),
    }


def active_at(rows: Iterable[ConditionRow], d: date) -> int:
    return sum(
        r.n for r in rows
        if ((r.onset_date is not None and r.onset_date <= d) or (r.onset_date is None and r.first_recorded_date <= d))
        and (r.resolved_date is None or r.resolved_date > d)
    )


def _month_series(rows: list[ConditionRow], end: date, coverage_start: date | None) -> list[dict]:
    last = (end + timedelta(days=1)).replace(day=1) if (end + timedelta(days=1)).day == 1 else end.replace(day=1)
    months = []
    y, m = last.year, last.month
    for _ in range(12):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        months.append(date(y, m, 1))
    out = []
    for first in reversed(months):
        nxt = date(first.year + first.month // 12, first.month % 12 + 1, 1)
        out.append({
            "month": first.strftime("%Y-%m"),
            "new_cases": sum(r.n for r in rows if r.onset_date and first <= r.onset_date < nxt),
            "complete": coverage_start is not None and coverage_start <= first,
        })
    return out


def _care_block(scope: list, gaps: list, screens: list, gap_start: date | None, as_of: date,
                cfg: TrendThresholds, population: int) -> dict[str, Any]:
    in_scope = sum(r.n for r in scope if r.in_scope)
    in_scope_open = sum(r.n for r in scope if r.in_scope and r.has_open_gap)
    periods = {}
    for key, days in PERIODS.items():
        w = windows(as_of, days)

        def follow_up(after: date, end: date) -> tuple[int, int]:
            eligible = sum(g.n for g in gaps if g.status not in ("superseded", "suppressed")
                           and g.identified_date <= end and (g.closed_date is None or g.closed_date > after))
            done = sum(g.n for g in gaps if g.status == "closed_completed" and g.closed_date
                       and after < g.closed_date <= end)
            return done, eligible

        new_g = sum(g.n for g in gaps if w["current_after"] < g.identified_date <= w["current_end"])
        prev_g = sum(g.n for g in gaps if w["previous_after"] < g.identified_date <= w["previous_end"])
        done, elig = follow_up(w["current_after"], w["current_end"])
        pdone, pelig = follow_up(w["previous_after"], w["previous_end"])
        hist = gap_start is not None and gap_start <= w["previous_after"] + timedelta(days=1)
        periods[key] = {
            "period_days": days, **_window_out(w),
            "screening_completions": sum(s.n for s in screens if w["current_after"] < s.performed_date <= w["current_end"]),
            "previous_screening_completions": sum(
                s.n for s in screens if w["previous_after"] < s.performed_date <= w["previous_end"]),
            "care_gaps_identified": new_g, "previous_care_gaps_identified": prev_g,
            "care_gap_trend": classify_trend(new_g, prev_g, population=population, history_complete=hist,
                                             completeness=None, cfg=cfg),
            "follow_up_completed": done, "follow_up_eligible_gaps": elig, "follow_up_completion_rate": _ratio(done, elig),
            "previous_follow_up_completed": pdone, "previous_follow_up_eligible_gaps": pelig,
            "previous_follow_up_completion_rate": _ratio(pdone, pelig),
        }
    return {
        "in_scope_patients": in_scope,
        "patients_with_open_gap": sum(r.n for r in scope if r.has_open_gap),
        "in_scope_patients_with_open_gap": in_scope_open,
        "open_care_gaps": sum(r.open_gaps for r in scope),
        "preventive_coverage": _ratio(in_scope - in_scope_open, in_scope),
        "preventive_coverage_definition": "in-scope patients without an open preventive-care gap / in-scope patients",
        "care_gap_history_start": _iso(gap_start),
        "periods": periods,
    }


def build_snapshot(facts: PopulationFacts, thresholds: PopulationThresholds, *, config_version: int,
                   generated_at: datetime) -> dict[str, Any]:
    as_of = facts.as_of
    complete_through = as_of - timedelta(days=thresholds.reporting_delay_days)
    code = {rid: c for rid, c, _, _ in facts.regions}

    local_labels = {(r.region_id, r.local_label) for r in facts.population if r.local_label}
    city_labels = {(f.region_id, f.city_key): f.city_label for f in facts.facilities
                   if f.region_id in code and f.city_key}
    areas = build_hierarchy(facts.regions, local_labels, city_labels)

    def areas_of(rid: int, label: str | None) -> list[str]:
        out = [COUNTRY_ID, STATE_ID]
        if rid in code:
            out.append(district_id(code[rid]))
            if label:
                out.append(local_area_id(code[rid], label))
        return out

    pop: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(COHORTS, 0))
    unassigned: dict[str, int] = defaultdict(int)
    for r in facts.population:
        for a in areas_of(r.region_id, r.local_label):
            for c in COHORTS:
                pop[a][c] += r.n if in_cohort(r.sex, r.age_group, c) else 0
            unassigned[a] += r.n if r.local_label is None else 0

    cond_rows: dict[tuple[str, str], list[ConditionRow]] = defaultdict(list)
    for r in facts.conditions:
        for a in areas_of(r.region_id, r.local_label):
            cond_rows[(a, r.condition_code)].append(r)
    # Coverage start of an aggregated area = the latest start among its constituent places, so a
    # trend never spans a window in which one constituent had no record feed yet.
    cov_start: dict[str, date | None] = {}
    cov_last: dict[str, datetime | None] = {}
    errors: dict[str, int] = defaultdict(int)
    for cv in facts.coverage:
        d = cv.first_recorded_at.date() if isinstance(cv.first_recorded_at, datetime) else cv.first_recorded_at
        for a in areas_of(cv.region_id, cv.local_label):
            cov_start[a] = d if cov_start.get(a) is None else max(cov_start[a], d)
            cov_last[a] = cv.last_recorded_at if cov_last.get(a) is None else max(cov_last[a], cv.last_recorded_at)
            errors[a] += cv.entered_in_error

    scope_rows, gap_rows, screen_rows = defaultdict(list), defaultdict(list), defaultdict(list)
    gap_start: dict[str, date] = {}
    for coll, src in ((scope_rows, facts.care_scope), (gap_rows, facts.gaps), (screen_rows, facts.screenings)):
        for r in src:
            for a in areas_of(r.region_id, r.local_label):
                coll[a].append(r)
    for a, rows in gap_rows.items():
        gap_start[a] = min(g.identified_date for g in rows)

    fac_by_area: dict[str, list] = defaultdict(list)
    for f in facts.facilities:
        fac_by_area[COUNTRY_ID].append(f)
        fac_by_area[STATE_ID].append(f)
        if f.region_id in code:
            fac_by_area[district_id(code[f.region_id])].append(f)
            if f.city_key:
                fac_by_area[city_area_id(code[f.region_id], f.city_key)].append(f)
    by_city = {(f.region_id, f.city_key) for f in facts.facilities}

    out_areas: dict[str, Any] = {}
    for area_id, area in areas.items():
        has_population = area.level != "city"
        population = pop[area_id] if has_population else None
        assoc_basis = None
        rows_f = fac_by_area.get(area_id, [])
        if area.level == "local_area":
            key, assoc_basis = local_to_city_key(area.name_en)
            rows_f = [f for f in facts.facilities if (f.region_id, f.city_key) == (area.region_id, key)]
            if (area.region_id, key) not in by_city:
                assoc_basis = None
        entry: dict[str, Any] = {
            "area": {"area_id": area_id, "level": area.level, "parent_area_id": area.parent_area_id,
                     "name_en": area.name_en, "name_ar": area.name_ar, "region_id": area.region_id,
                     "source": area.source, "verification_status": area.verification_status,
                     "boundary": None, "reference_point": None},
            "population": population,
            "facilities": _facility_block(area.level, rows_f, assoc_basis, population),
        }
        if has_population:
            entry["unassigned_local_area_population"] = unassigned[area_id] if area.level != "local_area" else 0
            entry["conditions"] = {}
            for c in CONDITIONS:
                rows = cond_rows.get((area_id, c), [])
                by_cohort = {coh: [x for x in rows if in_cohort(x.sex, x.age_group, coh)] for coh in COHORTS}
                total = sum(r.n for r in rows)
                entry["conditions"][c] = {
                    "current": {coh: {"as_of": _iso(as_of), "patients_with_condition": active_at(by_cohort[coh], as_of),
                                      "prevalence": _ratio(active_at(by_cohort[coh], as_of), population[coh]),
                                      "population": population[coh]} for coh in COHORTS},
                    "periods": {coh: {p: _condition_block(by_cohort[coh], population[coh], cov_start.get(area_id),
                                                          complete_through, d, thresholds.trend)
                                      for p, d in PERIODS.items()} for coh in COHORTS},
                    "series": _month_series(rows, complete_through, cov_start.get(area_id)),
                    "data_quality": {"recorded_patients": total,
                                     "undated_patients": sum(r.n for r in rows if r.onset_date is None),
                                     "duplicate_records": sum(r.duplicate_records for r in rows)},
                }
                block = entry["conditions"][c]["periods"]["all"][thresholds.hotspot.comparison_period]
                entry["conditions"][c]["hotspot"] = classify_hotspot(block, thresholds.hotspot) | {
                    "comparison_period": thresholds.hotspot.comparison_period,
                    "detected_at": _iso(generated_at),
                }
            entry["care"] = {coh: _care_block([r for r in scope_rows.get(area_id, []) if in_cohort(r.sex, r.age_group, coh)],
                                              [g for g in gap_rows.get(area_id, []) if in_cohort(g.sex, g.age_group, coh)],
                                              [s for s in screen_rows.get(area_id, []) if in_cohort(s.sex, s.age_group, coh)],
                                              gap_start.get(area_id), as_of, thresholds.trend, population[coh])
                             for coh in COHORTS}
            entry["data_quality"] = {
                "condition_history_start": _iso(cov_start.get(area_id)),
                "latest_condition_record_at": _iso(cov_last.get(area_id)),
                "entered_in_error_records_excluded": errors[area_id],
                "geographic_completeness": _ratio(population["all"] - entry["unassigned_local_area_population"],
                                                  population["all"]),
                "small_population": population["all"] < thresholds.trend.min_population,
            }
        out_areas[area_id] = entry

    snapshot = {
        "engine_version": ENGINE_VERSION,
        "organization_key": facts.organization_key,
        "source_run_id": facts.source_run_id,
        "reference_date": _iso(facts.reference_date),
        "as_of": _iso(as_of),
        "complete_through": _iso(complete_through),
        "latest_data_at": _iso(facts.latest_data_at),
        "generated_at": _iso(generated_at),
        "config_version": config_version,
        "thresholds": thresholds.model_dump(),
        "conditions": list(CONDITIONS),
        "areas": out_areas,
    }
    snapshot["alert_candidates"] = alert_candidates(snapshot, thresholds)
    return snapshot


def _facility_block(level: str, rows: list, assoc_basis: str | None, population: dict | None) -> dict[str, Any]:
    if level == "local_area" and assoc_basis is None:
        status = "no_matching_facility_label"
    else:
        status = {"local_area": "published_city_label", "city": "published_city_label"}.get(level, "region_of_record")
    by_layer: dict[str, int] = defaultdict(int)
    for f in rows:
        by_layer[f.source_layer] += f.n
    care = sum(n for layer, n in by_layer.items() if layer in CARE_FACILITY_LAYERS)
    lats = [(f.min_lat, f.max_lat, f.min_lon, f.max_lon) for f in rows if f.min_lat is not None]
    pop_all = population["all"] if population else 0
    known = status != "no_matching_facility_label"
    return {
        "association": {"status": status, "basis": assoc_basis},
        "total_facilities": sum(by_layer.values()) if known else None,
        "care_facilities": care if known else None,
        "care_facility_layers": list(CARE_FACILITY_LAYERS),
        "by_layer": dict(sorted(by_layer.items())) if known else None,
        "located_facilities": sum(f.n_located for f in rows) if known else None,
        "published_point_extent": (
            {"min_latitude": min(x[0] for x in lats), "max_latitude": max(x[1] for x in lats),
             "min_longitude": min(x[2] for x in lats), "max_longitude": max(x[3] for x in lats),
             "kind": "extent_of_published_facility_points_not_a_boundary"} if lats and known else None),
        "patients_per_care_facility": round(pop_all / care, 3) if known and care and pop_all else None,
        "nearest_facility_distance": {"available": False, "reason": "patient_locations_not_recorded"},
        "capacity": {"available": False, "reason": "not_published_by_source"},
    }


# --------------------------------------------------------------------------------------------
# Alert candidates
# --------------------------------------------------------------------------------------------


def _msg(key: str, **params: Any) -> dict[str, Any]:
    return {"message_key": key, "message_params": params}


def alert_candidates(snapshot: dict[str, Any], th: PopulationThresholds) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    al = th.alerts
    cmp_period = th.hotspot.comparison_period
    for area_id, e in sorted(snapshot["areas"].items()):
        area = e["area"]
        if area["level"] not in ALERT_LEVELS or e["population"] is None:
            continue
        name, pop = area["name_en"], e["population"]["all"]

        def add(category, severity, cond, metrics, thresholds, period_key=None, window=None, **msg):
            out.append({
                "dedup_key": f"{category}|{area_id}|{cond or '-'}|{period_key or '-'}",
                "category": category, "area_id": area_id, "condition_code": cond, "severity": severity,
                "metrics": metrics, "thresholds": thresholds, "period_key": period_key,
                "period_start": (window or {}).get("current_start"), "period_end": (window or {}).get("current_end"),
                "title_key": f"population.alert.{category}.title", "explanation_key": f"population.alert.{category}.explanation",
                "message_params": {"area": name, **msg},
            })

        for c, ce in e["conditions"].items():
            cname = CONDITIONS[c].name_en
            hs, blk = ce["hotspot"], ce["periods"]["all"][cmp_period]
            if hs["classification"] in ("WATCH", "MODERATE", "HIGH", "CRITICAL"):
                pct = blk["trend"]["percentage_change"]
                add("case_increase", hs["classification"], c, hs["supporting_metrics"], hs["thresholds"],
                    cmp_period, blk, condition=cname, current=blk["new_cases"], previous=blk["previous_new_cases"],
                    period=cmp_period, change=f"{pct:.0%}" if pct is not None else "n/a")
            cur = ce["current"]["all"]
            burden_min = al.burden_min_patients.get(c)
            if burden_min and pop >= al.min_population and cur["patients_with_condition"] >= burden_min:
                add("disease_burden", "HIGH" if cur["patients_with_condition"] >= 2 * burden_min else "MODERATE", c,
                    {"patients_with_condition": cur["patients_with_condition"], "population": pop},
                    {"burden_min_patients": burden_min, "min_population": al.min_population},
                    condition=cname, count=cur["patients_with_condition"], threshold=burden_min)
            pmax = al.prevalence_max.get(c)
            if pmax and pop >= al.min_population and cur["prevalence"] is not None and cur["prevalence"] >= pmax:
                add("prevalence", "HIGH" if cur["prevalence"] >= 1.5 * pmax else "MODERATE", c,
                    {"patients_with_condition": cur["patients_with_condition"], "population": pop,
                     "prevalence": cur["prevalence"]},
                    {"prevalence_max": pmax, "min_population": al.min_population},
                    condition=cname, prevalence=f"{cur['prevalence']:.1%}", threshold=f"{pmax:.0%}")
        care = e["care"]["all"]
        cov = care["preventive_coverage"]
        if cov is not None and care["in_scope_patients"] >= al.min_population and cov < al.preventive_coverage_target:
            add("preventive_coverage_low", "HIGH" if cov < al.preventive_coverage_target / 2 else "MODERATE", None,
                {k: care[k] for k in ("in_scope_patients", "in_scope_patients_with_open_gap", "open_care_gaps",
                                      "preventive_coverage")},
                {"preventive_coverage_target": al.preventive_coverage_target, "min_population": al.min_population},
                coverage=f"{cov:.0%}", target=f"{al.preventive_coverage_target:.0%}")
        fp = care["periods"][al.follow_up_period]
        rate, prate = fp["follow_up_completion_rate"], fp["previous_follow_up_completion_rate"]
        if (rate is not None and prate is not None and fp["follow_up_eligible_gaps"] >= al.follow_up_min_gaps
                and fp["previous_follow_up_eligible_gaps"] >= al.follow_up_min_gaps
                and prate - rate >= al.follow_up_decline_percentage_points):
            add("follow_up_completion_decline", "MODERATE", None,
                {k: fp[k] for k in ("follow_up_completed", "follow_up_eligible_gaps", "follow_up_completion_rate",
                                    "previous_follow_up_completed", "previous_follow_up_eligible_gaps",
                                    "previous_follow_up_completion_rate")},
                {"follow_up_decline_percentage_points": al.follow_up_decline_percentage_points,
                 "follow_up_min_gaps": al.follow_up_min_gaps}, al.follow_up_period, fp,
                current=f"{rate:.0%}", previous=f"{prate:.0%}")
        fac = e["facilities"]
        if (fac["care_facilities"] is not None and pop >= al.min_population
                and fac["care_facilities"] < al.min_care_facilities):
            add("facility_coverage_insufficient", "HIGH" if fac["care_facilities"] == 0 else "MODERATE", None,
                {"care_facilities": fac["care_facilities"], "population": pop,
                 "patients_per_care_facility": fac["patients_per_care_facility"],
                 "association": fac["association"]},
                {"min_care_facilities": al.min_care_facilities, "min_population": al.min_population},
                count=fac["care_facilities"], threshold=al.min_care_facilities)
    for c in out:
        c["title"] = t(c["title_key"], "en", **c["message_params"])
        c["explanation"] = t(c["explanation_key"], "en", **c["message_params"])
    return out
