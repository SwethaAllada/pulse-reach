"""Grouped, de-identified input counts for the aggregation engine.

Both providers return the same `PopulationFacts`: counts grouped by geography
(`region_id`, `local_label`), cohort (`sex`, `age_group`) and dates — never patient ids.

- `PostgresFactsProvider`: database-side aggregation (`GROUP BY` in PostgreSQL), organization
  filter applied in the query through `identity.patient_organization`.
- `MemoryFactsProvider`: the same definitions over the in-process synthetic dataset (memory mode
  already holds it in memory by design).

Definitions (shared by both):
- population: living registered patients of the organization (`date_of_death` after as-of).
- condition rows: one row per patient and condition after de-duplication — `entered_in_error`
  entries are excluded, onset = earliest known diagnosis date (NULL if no entry is dated),
  resolved = latest resolution date only if every entry is resolved, first_recorded = earliest
  `recorded_at`; `duplicate_records` = entries beyond the first.
- care scope: a patient is in preventive scope with >= 1 evaluation in
  `IN_SCOPE_EVALUATION_STATUSES` (latest evaluation run); open gaps = `care_gap.status = 'open'`.
- screenings: completed IFHAS screenings and attended well-child visits by `performed_date`.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, NamedTuple

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.services.population.geography import facility_city_key
from app.services.population.vocabulary import CHILD_AGE_YEARS, IN_SCOPE_EVALUATION_STATUSES

ALL_ORGANIZATIONS = "*"
_USABLE_LICENSE_STATUSES = ("Active", "Temporary Closure")


class PopulationRow(NamedTuple):
    region_id: int
    local_label: str | None
    sex: str | None
    age_group: str | None
    n: int


class ConditionRow(NamedTuple):
    region_id: int
    local_label: str | None
    sex: str | None
    age_group: str | None
    condition_code: str
    onset_date: date | None
    resolved_date: date | None
    first_recorded_date: date
    n: int
    duplicate_records: int


class CoverageRow(NamedTuple):
    region_id: int
    local_label: str | None
    first_recorded_at: datetime
    last_recorded_at: datetime
    records: int
    entered_in_error: int


class CareScopeRow(NamedTuple):
    region_id: int
    local_label: str | None
    sex: str | None
    age_group: str | None
    in_scope: bool
    has_open_gap: bool
    n: int
    open_gaps: int


class GapRow(NamedTuple):
    region_id: int
    local_label: str | None
    sex: str | None
    age_group: str | None
    identified_date: date
    closed_date: date | None
    status: str
    n: int


class ScreeningRow(NamedTuple):
    region_id: int
    local_label: str | None
    sex: str | None
    age_group: str | None
    performed_date: date
    n: int


class FacilityRow(NamedTuple):
    region_id: int | None
    city_key: str | None
    city_label: str | None
    source_layer: str
    n: int
    n_located: int
    min_lat: float | None
    max_lat: float | None
    min_lon: float | None
    max_lon: float | None


@dataclass
class PopulationFacts:
    organization_key: str
    source_run_id: str | None
    reference_date: date
    latest_data_at: datetime | None
    regions: list[tuple[int, str, str, str | None]]
    population: list[PopulationRow] = field(default_factory=list)
    conditions: list[ConditionRow] = field(default_factory=list)
    coverage: list[CoverageRow] = field(default_factory=list)
    care_scope: list[CareScopeRow] = field(default_factory=list)
    gaps: list[GapRow] = field(default_factory=list)
    screenings: list[ScreeningRow] = field(default_factory=list)
    facilities: list[FacilityRow] = field(default_factory=list)

    @property
    def as_of(self) -> date:
        return as_of_date(self.reference_date, self.latest_data_at)


def as_of_date(reference_date: date, latest_data_at: datetime | None) -> date:
    """Latest data date: the dataset reference date or the newest recorded event, whichever is later."""
    latest = latest_data_at.astimezone(timezone.utc).date() if latest_data_at else reference_date
    return max(reference_date, latest)


def _child_cutoff(as_of: date) -> date:
    try:
        return as_of.replace(year=as_of.year - CHILD_AGE_YEARS)
    except ValueError:  # 29 February
        return as_of.replace(year=as_of.year - CHILD_AGE_YEARS, day=28)


def _end_of(d: date) -> datetime:
    return datetime.combine(d + timedelta(days=1), time.min, timezone.utc)


def _merge_facilities(rows: list[tuple]) -> list[FacilityRow]:
    """Group raw (region, city, layer, n, located, lat/lon extents) rows by normalized city label."""
    acc: dict[tuple, list] = {}
    labels: dict[tuple, Counter] = defaultdict(Counter)
    for rid, city, layer, n, n_loc, mnlat, mxlat, mnlon, mxlon in rows:
        key = (rid, facility_city_key(city), layer)
        labels[key[:2]][(city or "").strip()] += n
        cur = acc.setdefault(key, [0, 0, None, None, None, None])
        cur[0] += n
        cur[1] += n_loc
        for i, v, fn in ((2, mnlat, min), (3, mxlat, max), (4, mnlon, min), (5, mxlon, max)):
            if v is not None:
                cur[i] = v if cur[i] is None else fn(cur[i], v)
    out = []
    for (rid, ck, layer), (n, n_loc, *ext) in sorted(acc.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        display = labels[(rid, ck)].most_common(1)[0][0] if ck else None
        out.append(FacilityRow(rid, ck, display, layer, n, n_loc, *ext))
    return out


# --------------------------------------------------------------------------------------------
# PostgreSQL
# --------------------------------------------------------------------------------------------


class PostgresFactsProvider:
    def __init__(self, session: Session) -> None:
        self._s = session

    def _runs(self) -> tuple[str, str, date]:
        from app.repositories.read_repo import PostgresReadRepository

        gr, er = PostgresReadRepository(self._s)._latest_runs()
        return gr.run_id, er.evaluation_run_id, er.reference_date

    def _latest_data_at(self, run_id: str) -> datetime | None:
        return self._s.execute(text(
            "SELECT greatest("
            "(SELECT max(recorded_at) FROM synthetic.condition_record WHERE run_id = :r), "
            "(SELECT max(recorded_at) FROM synthetic.care_gap_follow_up_event WHERE run_id = :r), "
            "(SELECT max(recorded_at) FROM synthetic.workflow_status_event WHERE run_id = :r))"
        ), {"r": run_id}).scalar_one()

    def data_version(self, organization_key: str) -> str:
        org_filter = "" if organization_key == ALL_ORGANIZATIONS else "WHERE organization_id = :org"
        row = self._s.execute(text(
            "SELECT (SELECT max(started_at)::text FROM synthetic.generation_run), "
            "(SELECT count(*) || ':' || coalesce(max(recorded_at)::text, '') FROM synthetic.condition_record), "
            "(SELECT count(*) || ':' || coalesce(max(recorded_at)::text, '') FROM synthetic.care_gap_follow_up_event), "
            "(SELECT count(*) || ':' || coalesce(max(recorded_at)::text, '') FROM synthetic.workflow_status_event), "
            "(SELECT count(*) FILTER (WHERE status <> 'open') FROM synthetic.care_gap), "
            f"(SELECT count(*) || ':' || coalesce(max(created_at)::text, '') FROM identity.patient_organization {org_filter})"
        ), {"org": organization_key}).one()
        return hashlib.sha256("|".join(str(v) for v in row).encode()).hexdigest()[:32]

    def fetch(self, organization_key: str) -> PopulationFacts:
        run_id, eval_run_id, ref_date = self._runs()
        latest = self._latest_data_at(run_id)
        as_of = as_of_date(ref_date, latest)
        org_join = (
            "" if organization_key == ALL_ORGANIZATIONS else
            "JOIN identity.patient_organization po ON po.patient_id = p.patient_id AND po.organization_id = :org"
        )
        params: dict[str, Any] = {
            "run_id": run_id, "eval_run_id": eval_run_id, "org": organization_key, "as_of": as_of,
            "as_of_end": _end_of(as_of), "child_cutoff": _child_cutoff(as_of),
            "scope_statuses": list(IN_SCOPE_EVALUATION_STATUSES),
        }
        base = (
            "WITH base AS (SELECT p.patient_id, p.region_id, p.district_label AS local_label, p.sex, "
            "CASE WHEN p.date_of_birth IS NULL THEN NULL WHEN p.date_of_birth > :child_cutoff THEN 'child' "
            f"ELSE 'adult' END AS age_group FROM synthetic.patient p {org_join} "
            "WHERE p.run_id = :run_id AND (p.date_of_death IS NULL OR p.date_of_death > :as_of))"
        )
        geo = "b.region_id, b.local_label, b.sex, b.age_group"

        def q(sql: str) -> list[tuple]:
            return [tuple(r) for r in self._s.execute(text(base + sql), params)]

        population = q(" SELECT region_id, local_label, sex, age_group, count(*) FROM base GROUP BY 1, 2, 3, 4")
        conditions = q(
            ", valid AS (SELECT patient_id, condition_code, diagnosis_date, status, resolved_date, recorded_at "
            "FROM synthetic.condition_record WHERE run_id = :run_id AND status <> 'entered_in_error' "
            "AND recorded_at < :as_of_end), "
            "pc AS (SELECT patient_id, condition_code, min(diagnosis_date) AS onset_date, "
            "CASE WHEN bool_and(status = 'resolved') THEN max(resolved_date) END AS resolved_date, "
            "(min(recorded_at) AT TIME ZONE 'UTC')::date AS first_recorded_date, count(*) - 1 AS dups "
            "FROM valid GROUP BY 1, 2) "
            f"SELECT {geo}, pc.condition_code, pc.onset_date, pc.resolved_date, pc.first_recorded_date, "
            "count(*), sum(pc.dups) FROM pc JOIN base b USING (patient_id) GROUP BY 1, 2, 3, 4, 5, 6, 7, 8"
        )
        coverage = q(
            " SELECT b.region_id, b.local_label, min(c.recorded_at), max(c.recorded_at), "
            "count(*) FILTER (WHERE c.status <> 'entered_in_error'), "
            "count(*) FILTER (WHERE c.status = 'entered_in_error') "
            "FROM synthetic.condition_record c JOIN base b USING (patient_id) "
            "WHERE c.run_id = :run_id AND c.recorded_at < :as_of_end GROUP BY 1, 2"
        )
        care_scope = q(
            ", ev AS (SELECT patient_id, bool_or(evaluation_status = ANY(:scope_statuses)) AS in_scope "
            "FROM synthetic.eligibility_evaluation WHERE evaluation_run_id = :eval_run_id GROUP BY 1), "
            "og AS (SELECT patient_id, count(*) AS open_gaps FROM synthetic.care_gap "
            "WHERE run_id = :run_id AND status = 'open' GROUP BY 1) "
            f"SELECT {geo}, coalesce(ev.in_scope, false), og.patient_id IS NOT NULL, count(*), "
            "coalesce(sum(og.open_gaps), 0) FROM base b LEFT JOIN ev USING (patient_id) "
            "LEFT JOIN og USING (patient_id) GROUP BY 1, 2, 3, 4, 5, 6"
        )
        gaps = q(
            f" SELECT {geo}, g.identified_date, g.closed_date, g.status, count(*) FROM synthetic.care_gap g "
            "JOIN base b USING (patient_id) WHERE g.run_id = :run_id GROUP BY 1, 2, 3, 4, 5, 6, 7"
        )
        screenings = q(
            ", s AS (SELECT patient_id, performed_date FROM synthetic.ifhas_screening WHERE run_id = :run_id "
            "AND completion_status = 'complete' AND performed_date IS NOT NULL UNION ALL "
            "SELECT patient_id, performed_date FROM synthetic.well_child_visit WHERE run_id = :run_id "
            "AND attendance_status = 'attended') "
            f"SELECT {geo}, s.performed_date, count(*) FROM s JOIN base b USING (patient_id) GROUP BY 1, 2, 3, 4, 5"
        )
        regions = [tuple(r) for r in self._s.execute(text(
            "SELECT region_id, region_code, name_en, name_ar FROM official.region ORDER BY region_id"))]
        facilities = [tuple(r) for r in self._s.execute(text(
            "SELECT region_id, city, source_layer, count(*), count(latitude), min(latitude), max(latitude), "
            "min(longitude), max(longitude) FROM official.facility WHERE identity_status = 'identified' "
            "AND geo_quality = 'ok' AND license_status_raw = ANY(:st) GROUP BY 1, 2, 3"
        ), {"st": list(_USABLE_LICENSE_STATUSES)})]
        return PopulationFacts(
            organization_key=organization_key, source_run_id=run_id, reference_date=ref_date,
            latest_data_at=latest, regions=regions,
            population=[PopulationRow(*r) for r in population],
            conditions=[ConditionRow(*r[:9], int(r[9])) for r in conditions],
            coverage=[CoverageRow(*r) for r in coverage],
            care_scope=[CareScopeRow(*r[:7], int(r[7])) for r in care_scope],
            gaps=[GapRow(*r) for r in gaps],
            screenings=[ScreeningRow(*r) for r in screenings],
            facilities=_merge_facilities(facilities),
        )


# --------------------------------------------------------------------------------------------
# Memory
# --------------------------------------------------------------------------------------------


def _memory_org_patients(organization_key: str) -> frozenset[str] | None:
    if organization_key == ALL_ORGANIZATIONS:
        return None
    from app.services.identity import directory
    from app.services.identity.store import identity_session

    with identity_session() as s:
        return directory.organization_patient_ids(s, organization_key)


class MemoryFactsProvider:
    def _latest_data_at(self, ds: Any) -> datetime | None:
        from app.repositories.followup_repo import get_memory_follow_up_events, get_memory_workflow_events

        stamps = [r["recorded_at"] for r in ds.condition_records]
        stamps += [e["recorded_at"] for e in get_memory_follow_up_events() + get_memory_workflow_events()]
        return max(stamps, default=None)

    def data_version(self, organization_key: str) -> str:
        from app.models.identity import PatientOrganization
        from app.repositories.followup_repo import get_memory_follow_up_events, get_memory_workflow_events
        from app.repositories.read_repo import get_cached_dataset
        from app.services.identity.store import identity_session
        from sqlalchemy import func

        ds = get_cached_dataset()
        stmt = select(func.count(), func.max(PatientOrganization.created_at))
        if organization_key != ALL_ORGANIZATIONS:
            stmt = stmt.where(PatientOrganization.organization_id == organization_key)
        with identity_session() as s:
            owned = tuple(s.execute(stmt).one())
        parts = (id(ds), ds.generation_run["run_id"], len(ds.condition_records), len(get_memory_follow_up_events()),
                 len(get_memory_workflow_events()), sum(g["status"] != "open" for g in ds.care_gaps), owned)
        return hashlib.sha256(repr(parts).encode()).hexdigest()[:32]

    def fetch(self, organization_key: str) -> PopulationFacts:
        from app.repositories.read_repo import get_cached_dataset, get_cached_facilities
        from app.services.official_loader.parse import REGIONS

        ds = get_cached_dataset()
        allowed = _memory_org_patients(organization_key)
        ref_date = ds.evaluation_run["reference_date"]
        latest = self._latest_data_at(ds)
        as_of = as_of_date(ref_date, latest)
        cutoff, as_of_end = _child_cutoff(as_of), _end_of(as_of)

        geo: dict[str, tuple] = {}
        for p in ds.patients:
            if allowed is not None and p["patient_id"] not in allowed:
                continue
            if p.get("date_of_death") is not None and p["date_of_death"] <= as_of:
                continue
            dob = p["date_of_birth"]
            age_group = None if dob is None else ("child" if dob > cutoff else "adult")
            geo[p["patient_id"]] = (p["region_id"], p["district_label"], p["sex"], age_group)

        population = Counter(geo.values())

        per_pc: dict[tuple[str, str], list[dict]] = defaultdict(list)
        cov: dict[tuple, list] = {}
        for r in ds.condition_records:
            g = geo.get(r["patient_id"])
            if g is None or r["recorded_at"] >= as_of_end:
                continue
            c = cov.setdefault(g[:2], [r["recorded_at"], r["recorded_at"], 0, 0])
            c[0], c[1] = min(c[0], r["recorded_at"]), max(c[1], r["recorded_at"])
            if r["status"] == "entered_in_error":
                c[3] += 1
                continue
            c[2] += 1
            per_pc[(r["patient_id"], r["condition_code"])].append(r)
        cond: Counter = Counter()
        dups: Counter = Counter()
        for (pid, code), recs in per_pc.items():
            dated = [x["diagnosis_date"] for x in recs if x["diagnosis_date"] is not None]
            resolved = (max(x["resolved_date"] for x in recs)
                        if all(x["status"] == "resolved" for x in recs) else None)
            first = min(x["recorded_at"] for x in recs).astimezone(timezone.utc).date()
            key = (*geo[pid], code, min(dated, default=None), resolved, first)
            cond[key] += 1
            dups[key] += len(recs) - 1

        scope_by_patient: dict[str, bool] = defaultdict(bool)
        for e in ds.eligibility_evaluations:
            if e["evaluation_run_id"] == ds.evaluation_run["evaluation_run_id"]:
                scope_by_patient[e["patient_id"]] |= e["evaluation_status"] in IN_SCOPE_EVALUATION_STATUSES
        open_gaps: Counter = Counter()
        gaps: Counter = Counter()
        for gp in ds.care_gaps:
            g = geo.get(gp["patient_id"])
            if g is None:
                continue
            gaps[(*g, gp["identified_date"], gp.get("closed_date"), gp["status"])] += 1
            if gp["status"] == "open":
                open_gaps[gp["patient_id"]] += 1
        care: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
        for pid, g in geo.items():
            c = care[(*g, scope_by_patient[pid], pid in open_gaps)]
            c[0] += 1
            c[1] += open_gaps[pid]

        screens: Counter = Counter()
        for s in ds.ifhas_screenings:
            if s["completion_status"] == "complete" and s["performed_date"] and s["patient_id"] in geo:
                screens[(*geo[s["patient_id"]], s["performed_date"])] += 1
        for v in ds.well_child_visits:
            if v["attendance_status"] == "attended" and v["patient_id"] in geo:
                screens[(*geo[v["patient_id"]], v["performed_date"])] += 1

        fac: dict[tuple, list] = {}
        for f in get_cached_facilities():
            cur = fac.setdefault((f["region_id"], f["city"], f["source_layer"]), [0, 0, None, None, None, None])
            cur[0] += 1
            if f["latitude"] is not None:
                cur[1] += 1
                lat, lon = f["latitude"], f["longitude"]
                cur[2] = lat if cur[2] is None else min(cur[2], lat)
                cur[3] = lat if cur[3] is None else max(cur[3], lat)
                cur[4] = lon if cur[4] is None else min(cur[4], lon)
                cur[5] = lon if cur[5] is None else max(cur[5], lon)

        return PopulationFacts(
            organization_key=organization_key, source_run_id=ds.generation_run["run_id"],
            reference_date=ref_date, latest_data_at=latest,
            regions=[(rid, code, scad, None) for rid, code, scad, _ in REGIONS],
            population=[PopulationRow(*k, n) for k, n in population.items()],
            conditions=[ConditionRow(*k, n, dups[k]) for k, n in cond.items()],
            coverage=[CoverageRow(*k, *v) for k, v in cov.items()],
            care_scope=[CareScopeRow(*k, *v) for k, v in care.items()],
            gaps=[GapRow(*k, n) for k, n in gaps.items()],
            screenings=[ScreeningRow(*k, n) for k, n in screens.items()],
            facilities=_merge_facilities([(*k, *v) for k, v in fac.items()]),
        )
