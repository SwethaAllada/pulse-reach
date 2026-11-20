"""`/api/v1/population/*` — geospatial population intelligence (BE-33).

Organization-level aggregates of the caller's organization only (organization from the
authenticated session, never from the request); small cells suppressed; no patient-level
fields. Reads serve the latest persisted aggregation snapshot (computed on first use, refreshed
in the background when stale); see docs/geospatial-population-intelligence.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from sqlalchemy import func, select

from app.core.auth import Principal, legacy_write_guard, require
from app.core.config import settings
from app.core.i18n import AppError, resolve_locale
from app.models.population import ACTIVE_ALERT_STATUSES, PopulationAlert, PopulationAlertEvent
from app.schemas.population import (
    AggregationStatusOut,
    AlertDetailOut,
    AlertPatchIn,
    AlertsOut,
    AreaDetailOut,
    HotspotsOut,
    MapOut,
    SummaryOut,
    ThresholdConfigOut,
    TrendsOut,
    UpdatesOut,
)
from app.services.population.alerts import InvalidTransition, transition
from app.services.population.config import PopulationThresholds
from app.services.population.facts import ALL_ORGANIZATIONS
from app.services.population.service import RefreshInProgress, get_population_service, run_dict
from app.services.population.store import population_session
from app.services.population.views import View
from app.services.population.vocabulary import (
    ALERT_LEVELS,
    CONDITIONS,
    HOTSPOT_CLASSES,
    PERIODS,
    SEVERITY_RANK,
)

router = APIRouter(prefix="/api/v1/population", tags=["population"], dependencies=[Depends(legacy_write_guard)])

ConditionCode = Literal["diabetes_type_2", "hypertension", "dyslipidaemia", "asthma"]
Period = Literal["7d", "30d", "90d", "6m", "12m"]
Level = Literal["country", "state", "district", "city", "local_area"]
Cohort = Literal["all", "adults", "children", "female", "male"]
Metric = Literal["population", "new_cases", "patients_with_condition", "prevalence", "trend", "hotspot",
                 "open_care_gaps", "preventive_coverage", "care_facilities"]
Severity = Literal["CRITICAL", "HIGH", "MODERATE", "WATCH"]
AlertStatus = Literal["NEW", "ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "DISMISSED"]
AlertCategory = Literal["case_increase", "disease_burden", "prevalence", "preventive_coverage_low",
                        "follow_up_completion_decline", "facility_coverage_insufficient"]
DISEASE_METRICS = frozenset({"new_cases", "patients_with_condition", "prevalence", "trend", "hotspot"})
_HOTSPOT_ORDER = {c: i for i, c in enumerate(reversed(HOTSPOT_CLASSES))}  # INSUFFICIENT_DATA lowest
_POLL_SECONDS = {"map": 60, "alerts": 30, "trends": 300, "updates": 30}
_READ = require("population.read")
_ALERTS_READ = require("population.alerts.read")


def _org(p: Principal) -> str:
    """Organization scope from the authenticated session (`*` only in AUTH_MODE=legacy)."""
    if p.legacy:
        return ALL_ORGANIZATIONS
    if not p.organization_id:
        raise AppError(403, "error.forbidden")
    return p.organization_id


def _view(request: Request, p: Principal, background: BackgroundTasks | None) -> View:
    sv = _current(p, background)
    return View(sv, resolve_locale(request, p.preferred_language), settings.population_min_cell_size)


def _current(p: Principal, background: BackgroundTasks | None):
    try:
        return get_population_service().current_snapshot(
            _org(p), schedule=background.add_task if background is not None else None)
    except RefreshInProgress as exc:
        raise AppError(503, "population.refresh_in_progress", headers={"Retry-After": "5"}) from exc


def _audit(p: Principal, action: str, resource_type: str, resource_id: str | None, permission: str,
           details: dict | None = None, outcome: str = "success", status_code: int = 200) -> None:
    from app.services.identity.audit import record_event

    record_event(p, action, resource_type, resource_id=resource_id, permission=permission, details=details,
                 outcome=outcome, status_code=status_code)


def _active_alert_counts(org: str) -> dict[str, int]:
    with population_session() as s:
        rows = s.execute(select(PopulationAlert.area_id, func.count()).where(
            PopulationAlert.organization_key == org, PopulationAlert.status.in_(ACTIVE_ALERT_STATUSES))
            .group_by(PopulationAlert.area_id))
        return {a: n for a, n in rows}


def _parse_bbox(bbox: str | None) -> list[float] | None:
    if bbox is None:
        return None
    try:
        box = [float(x) for x in bbox.split(",")]
    except ValueError:
        box = []
    if (len(box) != 4 or not (-180 <= box[0] < box[2] <= 180) or not (-90 <= box[1] < box[3] <= 90)):
        raise AppError(422, "population.invalid_bbox")
    return box


def _intersects(extent: dict, box: list[float]) -> bool:
    return not (extent["max_longitude"] < box[0] or extent["min_longitude"] > box[2]
                or extent["max_latitude"] < box[1] or extent["min_latitude"] > box[3])


# --------------------------------------------------------------------------------------------
# Map, trends, hotspots, area detail, summary
# --------------------------------------------------------------------------------------------


@router.get("/map", response_model=MapOut)
def population_map(
    request: Request,
    background: BackgroundTasks,
    condition: ConditionCode | None = None,
    period: Period = "90d",
    geography: Level = "local_area",
    metric: Metric | None = None,
    cohort: Cohort = "all",
    bbox: str | None = Query(default=None, description="min_longitude,min_latitude,max_longitude,max_latitude"),
    sort: Literal["metric_desc", "name"] = "metric_desc",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    p: Principal = Depends(_READ),
) -> MapOut:
    metric = metric or ("new_cases" if condition else "population")
    if metric in DISEASE_METRICS and condition is None:
        raise AppError(422, "population.condition_required", params={"metric": metric})
    box = _parse_bbox(bbox)
    v = _view(request, p, background)
    alerts = _active_alert_counts(_org(p))
    ids = sorted(a for a, e in v.areas.items() if e["area"]["level"] == geography)
    excluded = 0
    if box is not None:
        located = [a for a in ids if v.areas[a]["facilities"]["published_point_extent"]]
        excluded = len(ids) - len(located)
        ids = [a for a in located if _intersects(v.areas[a]["facilities"]["published_point_extent"], box)]
    items = []
    for aid in ids:
        e = v.areas[aid]
        has_pop = e["population"] is not None
        disease = v.disease(aid, condition, cohort, period) if condition and has_pop else None
        care = v.care(aid, cohort, period) if has_pop else None
        fac = e["facilities"]
        hotspot = v.hotspot(aid, condition, period)["classification"] if condition and has_pop else None
        value = {
            "population": v.population(aid, cohort),
            "new_cases": disease and disease["new_cases"],
            "patients_with_condition": disease and disease["patients_with_condition"],
            "prevalence": disease and disease["prevalence"],
            "trend": disease and disease["trend"]["percentage_change"],
            "hotspot": SEVERITY_RANK.get(hotspot or "", 0) if hotspot else None,
            "open_care_gaps": care and care["open_care_gaps"],
            "preventive_coverage": care and care["preventive_coverage"],
            "care_facilities": fac["care_facilities"],
        }[metric]
        dq, dq_sup = v.sup.primary(e.get("data_quality") or {}, ("entered_in_error_records_excluded",))
        if disease:
            dq = {**dq, "condition_completeness": disease["completeness"], "history_complete": disease["history_complete"]}
        items.append({
            "area": v.area(aid), "population": v.population(aid, cohort), "metric_value": value, "disease": disease,
            "hotspot_classification": hotspot, "active_alerts": alerts.get(aid, 0),
            "preventive_coverage": care and care["preventive_coverage"],
            "open_care_gaps": care and care["open_care_gaps"], "care_facilities": fac["care_facilities"],
            "facility_association": fac["association"]["status"], "facility_point_extent": fac["published_point_extent"],
            "data_quality": dq,
            "suppressed": sorted(set((disease or {}).get("suppressed", []) + (care or {}).get("suppressed", []) + dq_sup
                                     + (["population"] if has_pop and v.population(aid, cohort) is None else []))),
        })
    if sort == "name":
        items.sort(key=lambda i: i["area"]["name"])
    else:
        items.sort(key=lambda i: (i["metric_value"] is None, -(i["metric_value"] or 0), i["area"]["area_id"]))
    return MapOut(**v.envelope(), condition=condition, period=period, geography=geography, metric=metric,
                  cohort=cohort, bbox=box, excluded_without_geometry=excluded, total=len(items), limit=limit,
                  offset=offset, items=items[offset: offset + limit])


@router.get("/trends", response_model=TrendsOut)
def population_trends(
    request: Request,
    background: BackgroundTasks,
    condition: ConditionCode,
    area_id: str | None = None,
    geography: Level | None = None,
    period: Period | None = None,
    cohort: Cohort = "all",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    p: Principal = Depends(_READ),
) -> TrendsOut:
    v = _view(request, p, background)
    if area_id is not None:
        if area_id not in v.areas or v.areas[area_id]["population"] is None:
            raise AppError(404, "population.area_not_found")
        ids = [area_id]
    else:
        level = geography or "district"
        ids = sorted(a for a, e in v.areas.items() if e["area"]["level"] == level and e["population"] is not None)
    periods = [period] if period else list(PERIODS)
    items = [{"area": v.area(a), "comparisons": {pk: v.disease(a, condition, cohort, pk) for pk in periods},
              "series": v.series(a, condition)} for a in ids[offset: offset + limit]]
    return TrendsOut(**v.envelope(), condition=condition, geography=geography, cohort=cohort, total=len(ids),
                     limit=limit, offset=offset, items=items)


@router.get("/hotspots", response_model=HotspotsOut)
def population_hotspots(
    request: Request,
    background: BackgroundTasks,
    condition: ConditionCode | None = None,
    period: Period | None = None,
    geography: Level | None = None,
    min_classification: Literal["CRITICAL", "HIGH", "MODERATE", "WATCH", "NO_ALERT", "INSUFFICIENT_DATA"] = "WATCH",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    p: Principal = Depends(_READ),
) -> HotspotsOut:
    v = _view(request, p, background)
    period = period or v.thresholds.hotspot.comparison_period
    levels = (geography,) if geography else ALERT_LEVELS
    floor = _HOTSPOT_ORDER[min_classification]
    found = []
    for aid, e in sorted(v.areas.items()):
        if e["area"]["level"] not in levels or e["population"] is None:
            continue
        for c in ([condition] if condition else CONDITIONS):
            hs = v.hotspot(aid, c, period)
            if _HOTSPOT_ORDER[hs["classification"]] >= floor:
                found.append(hs)
    found.sort(key=lambda h: (-_HOTSPOT_ORDER[h["classification"]], -(h["supporting_metrics"]["new_cases"] or 0),
                              h["area"]["area_id"], h["condition_code"]))
    return HotspotsOut(**v.envelope(), condition=condition, period=period, min_classification=min_classification,
                       total=len(found), limit=limit, offset=offset, items=found[offset: offset + limit])


@router.get("/areas/{area_id}", response_model=AreaDetailOut)
def population_area(
    area_id: str,
    request: Request,
    background: BackgroundTasks,
    period: Period | None = None,
    cohort: Cohort = "all",
    p: Principal = Depends(_READ),
) -> AreaDetailOut:
    v = _view(request, p, background)
    if area_id not in v.areas:
        raise AppError(404, "population.area_not_found")
    e = v.areas[area_id]
    period = period or v.thresholds.hotspot.comparison_period
    has_pop = e["population"] is not None
    conditions = [{
        "condition_code": c, "condition_name": v.disease(area_id, c, cohort, period)["condition_name"],
        "current": v.current(area_id, c, cohort),
        "comparisons": {pk: v.disease(area_id, c, cohort, pk) for pk in PERIODS},
        "series": v.series(area_id, c), "hotspot": v.hotspot(area_id, c, period),
        "data_quality": v.sup.primary(e["conditions"][c]["data_quality"],
                                      ("recorded_patients", "undated_patients", "duplicate_records"))[0],
    } for c in CONDITIONS] if has_pop else []
    with population_session() as s:
        active = list(s.scalars(select(PopulationAlert).where(
            PopulationAlert.organization_key == _org(p), PopulationAlert.area_id == area_id,
            PopulationAlert.status.in_(ACTIVE_ALERT_STATUSES)).order_by(PopulationAlert.last_detected_at.desc())))
    dq, dq_sup = v.sup.primary(e.get("data_quality") or {}, ("entered_in_error_records_excluded",))
    population = {c: v.population(area_id, c) for c in e["population"]} if has_pop else {}
    return AreaDetailOut(
        **v.envelope(), area=v.area(area_id), ancestors=v.ancestors(area_id), children=v.children(area_id),
        cohort=cohort, population=population,
        unassigned_local_area_population=v.unassigned(area_id) if has_pop else None,
        conditions=conditions, active_alerts=[v.alert(a) for a in active], facilities=v.facilities(area_id),
        preventive_care=v.care(area_id, cohort, period) if has_pop else None, data_quality=dq,
        suppressed=dq_sup + [f"population.{c}" for c, n in population.items() if n is None and e["population"][c]],
    )


@router.get("/summary", response_model=SummaryOut)
def population_summary(request: Request, background: BackgroundTasks, p: Principal = Depends(_READ)) -> SummaryOut:
    v = _view(request, p, background)
    cmp = v.thresholds.hotspot.comparison_period
    increasing, classes = [], dict.fromkeys(HOTSPOT_CLASSES, 0)
    monitored = 0
    for aid, e in sorted(v.areas.items()):
        if e["area"]["level"] not in ALERT_LEVELS or not (e["population"] or {}).get("all"):
            continue
        monitored += 1
        for c in CONDITIONS:
            if v.disease(aid, c, "all", cmp)["trend"]["direction"] == "INCREASING":
                increasing.append({"area_id": aid, "name": v.area(aid)["name"], "level": e["area"]["level"],
                                   "condition_code": c})
            classes[v.hotspot(aid, c, cmp)["classification"]] += 1
    with population_session() as s:
        by_sev = dict(s.execute(select(PopulationAlert.severity, func.count()).where(
            PopulationAlert.organization_key == _org(p), PopulationAlert.status.in_(ACTIVE_ALERT_STATUSES))
            .group_by(PopulationAlert.severity)).all())
    root = "AE"
    return SummaryOut(
        **v.envelope(), total_population=v.population(root, "all"),
        conditions_monitored=[{"condition_code": c, "name": v.disease(root, c, "all", cmp)["condition_name"],
                               "icd10_category": CONDITIONS[c].icd10_category} for c in CONDITIONS],
        areas_monitored=monitored, areas_with_increasing_cases=len({i["area_id"] for i in increasing}),
        increasing=increasing, comparison_period=cmp,
        active_hotspots=sum(classes[c] for c in SEVERITY_RANK), hotspots_by_classification=classes,
        active_alerts=sum(by_sev.values()), alerts_by_severity={s: by_sev.get(s, 0) for s in SEVERITY_RANK},
        preventive_care=v.care(root, "all", cmp), latest_aggregation_at=v.sv.run["finished_at"],
    )


@router.get("/updates", response_model=UpdatesOut)
def population_updates(
    background: BackgroundTasks,
    p: Principal = Depends(require("population.read", "population.refresh", any_of=True)),
) -> UpdatesOut:
    svc, org = get_population_service(), _org(p)
    latest = svc.latest_run(org, include_running=True)
    done = latest if latest is not None and latest.status == "succeeded" else svc.latest_run(org)
    changed = stale = age = None
    if done is not None:
        changed = svc.data_version(org) != done.data_version
        age = round((datetime.now(timezone.utc) - done.finished_at).total_seconds(), 1)
        stale = changed or age > settings.population_max_snapshot_age_seconds
        if stale and (latest is None or latest.status != "running"):
            background.add_task(svc.refresh_quietly, org, "stale_data")
    return UpdatesOut(
        aggregation_status=latest.status if latest else "never_aggregated",
        last_aggregation_at=done.finished_at if done else None,
        latest_aggregated_data_at=done.latest_data_at if done else None,
        data_changed_since_aggregation=changed, staleness_seconds=age, stale=stale,
        latest_run=AggregationStatusOut(**run_dict(latest)) if latest else None,
        dataset_version={"source_run_id": done.source_run_id if done else None,
                         "data_version": done.data_version if done else None,
                         "config_version": done.config_version if done else None,
                         "engine_version": done.engine_version if done else None},
        recommended_poll_seconds=_POLL_SECONDS,
    )


@router.post("/refresh", response_model=AggregationStatusOut)
def population_refresh(p: Principal = Depends(require("population.refresh"))) -> AggregationStatusOut:
    org = _org(p)
    try:
        run = get_population_service().refresh(org, trigger="manual", requested_by=p.actor_ref)
    except RefreshInProgress as exc:
        _audit(p, "population.refresh", "population_aggregation", None, "population.refresh",
               outcome="failed", status_code=409)
        raise AppError(409, "population.refresh_in_progress") from exc
    _audit(p, "population.refresh", "population_aggregation", run["run_id"], "population.refresh",
           details={"alerts": run["summary"].get("alerts")})
    return AggregationStatusOut(**run)


# --------------------------------------------------------------------------------------------
# Thresholds
# --------------------------------------------------------------------------------------------


def _config_out(p: Principal) -> ThresholdConfigOut:
    th, version, updated_at, updated_by = get_population_service().thresholds(_org(p))
    return ThresholdConfigOut(organization_scope="legacy_all" if p.legacy else "organization", version=version,
                              is_default=version == 0, updated_at=updated_at, updated_by=updated_by,
                              thresholds=th, min_cell_size=settings.population_min_cell_size)


@router.get("/config", response_model=ThresholdConfigOut)
def get_population_config(
    p: Principal = Depends(require("population.read", "population.configure", any_of=True)),
) -> ThresholdConfigOut:
    return _config_out(p)


@router.patch("/config", response_model=ThresholdConfigOut)
def update_population_config(
    body: PopulationThresholds, p: Principal = Depends(require("population.configure"))
) -> ThresholdConfigOut:
    svc, org = get_population_service(), _org(p)
    version = svc.update_thresholds(org, body, p.actor_ref)
    _audit(p, "population.config_updated", "population_config", org, "population.configure",
           details={"version": version})
    try:
        svc.refresh(org, trigger="config_change", requested_by=p.actor_ref)
    except RefreshInProgress:
        pass  # the running aggregation is superseded; the next read sees the new version as stale
    return _config_out(p)


# --------------------------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------------------------


@router.get("/alerts", response_model=AlertsOut)
def list_population_alerts(
    request: Request,
    background: BackgroundTasks,
    condition: ConditionCode | None = None,
    area_id: str | None = None,
    severity: Severity | None = None,
    status: AlertStatus | None = None,
    category: AlertCategory | None = None,
    active_only: bool = False,
    since: datetime | None = Query(default=None, description="last_detected_at >= since"),
    until: datetime | None = Query(default=None, description="first_detected_at < until"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    p: Principal = Depends(_ALERTS_READ),
) -> AlertsOut:
    v = _view(request, p, background)
    stmt = select(PopulationAlert).where(PopulationAlert.organization_key == _org(p))
    for col, val in ((PopulationAlert.condition_code, condition), (PopulationAlert.area_id, area_id),
                     (PopulationAlert.severity, severity), (PopulationAlert.status, status),
                     (PopulationAlert.category, category)):
        if val is not None:
            stmt = stmt.where(col == val)
    if active_only:
        stmt = stmt.where(PopulationAlert.status.in_(ACTIVE_ALERT_STATUSES))
    if since is not None:
        stmt = stmt.where(PopulationAlert.last_detected_at >= since)
    if until is not None:
        stmt = stmt.where(PopulationAlert.first_detected_at < until)
    with population_session() as s:
        total = int(s.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = list(s.scalars(stmt.order_by(PopulationAlert.last_detected_at.desc(), PopulationAlert.alert_id)
                              .limit(limit).offset(offset)))
    return AlertsOut(total=total, limit=limit, offset=offset, items=[v.alert(a) for a in rows],
                     privacy={"min_cell_size": settings.population_min_cell_size})


def _alert_or_404(s, org: str, alert_id: str) -> PopulationAlert:
    a = s.scalar(select(PopulationAlert).where(PopulationAlert.alert_id == alert_id,
                                               PopulationAlert.organization_key == org))
    if a is None:  # other organizations' alerts are indistinguishable from missing ones
        raise AppError(404, "population.alert_not_found")
    return a


def _alert_detail(v: View, s, a: PopulationAlert) -> AlertDetailOut:
    events = list(s.scalars(select(PopulationAlertEvent).where(PopulationAlertEvent.alert_id == a.alert_id)
                            .order_by(PopulationAlertEvent.occurred_at, PopulationAlertEvent.event_id)))
    history = [{k: getattr(ev, k) for k in ("event_id", "event_type", "from_status", "to_status", "severity",
                                             "actor_user_id", "actor_role", "run_id", "occurred_at", "note",
                                             "details")} for ev in events]
    return AlertDetailOut(**v.alert(a), history=history)


@router.get("/alerts/{alert_id}", response_model=AlertDetailOut)
def get_population_alert(alert_id: str, request: Request, background: BackgroundTasks,
                         p: Principal = Depends(_ALERTS_READ)) -> AlertDetailOut:
    v = _view(request, p, background)
    with population_session() as s:
        return _alert_detail(v, s, _alert_or_404(s, _org(p), alert_id))


@router.patch("/alerts/{alert_id}", response_model=AlertDetailOut)
def update_population_alert(alert_id: str, body: AlertPatchIn, request: Request,
                            p: Principal = Depends(require("population.alerts.manage"))) -> AlertDetailOut:
    v = _view(request, p, None)
    org = _org(p)
    error: AppError | None = None
    from_status = None
    with population_session() as s:
        a = _alert_or_404(s, org, alert_id)
        from_status = a.status
        try:
            transition(s, a, body.status, actor_user_id=p.actor_ref, actor_role=p.role, note=body.note,
                       at=datetime.now(timezone.utc))
        except InvalidTransition as exc:
            error = AppError(409, "population.invalid_transition",
                             params={"from_status": exc.from_status, "to_status": exc.to_status})
        else:
            s.flush()
            out = _alert_detail(v, s, a)
    details = {"from_status": from_status, "to_status": body.status}
    if error is not None:
        _audit(p, "population_alert.status_changed", "population_alert", alert_id, "population.alerts.manage",
               details=details, outcome="failed", status_code=409)
        raise error
    _audit(p, "population_alert.status_changed", "population_alert", alert_id, "population.alerts.manage",
           details=details)
    return out
