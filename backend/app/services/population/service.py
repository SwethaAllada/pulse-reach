"""Aggregation orchestration: refresh, persisted snapshots, staleness and threshold configuration.

- `refresh(org)`: one aggregation for one organization. Guarded by an in-process lock per
  organization and by the `uq_aggregation_run_one_running` unique index (across workers), so
  concurrent refreshes never run twice; abandoned `running` rows are failed after
  `POPULATION_REFRESH_TIMEOUT_SECONDS`. The snapshot is persisted on the run; alerts are synced
  in the same transaction.
- `current_snapshot(org)`: the latest succeeded snapshot (cached in process by run id). Requests
  never recompute it unless none exists yet; a stale one (data or configuration changed, or older
  than `POPULATION_MAX_SNAPSHOT_AGE_SECONDS`) is served with `stale: true` while a background
  refresh is scheduled.
- Data version: a cheap fingerprint of the inputs (record counts / latest timestamps, care-gap
  closures, patient ownership, threshold version), re-checked at most every
  `POPULATION_FRESHNESS_CHECK_SECONDS`.
"""

from __future__ import annotations

import logging
import threading
import time as _time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from app.core.config import settings
from app.models.population import AggregationRun, GeoArea, ThresholdConfig
from app.services.population.alerts import sync_alerts
from app.services.population.config import DEFAULT_THRESHOLDS, PopulationThresholds
from app.services.population.engine import build_snapshot
from app.services.population.facts import MemoryFactsProvider, PostgresFactsProvider
from app.services.population.store import population_session
from app.services.population.vocabulary import ENGINE_VERSION

logger = logging.getLogger("pulsereach.population")


class RefreshInProgress(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotView:
    run: dict[str, Any]
    snapshot: dict[str, Any]
    stale: bool
    data_changed: bool
    refresh_scheduled: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def facts_provider() -> Iterator[MemoryFactsProvider | PostgresFactsProvider]:
    if settings.data_source == "memory":
        yield MemoryFactsProvider()
        return
    from app.db.session import get_engine

    with Session(get_engine()) as s:
        yield PostgresFactsProvider(s)


def run_dict(r: AggregationRun) -> dict[str, Any]:
    return {k: getattr(r, k) for k in (
        "run_id", "organization_key", "status", "trigger", "requested_by", "started_at", "finished_at",
        "engine_version", "data_version", "config_version", "source_run_id", "as_of", "complete_through",
        "latest_data_at", "error_code", "summary")}


class PopulationService:
    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        self._snapshots: dict[str, tuple[str, dict[str, Any]]] = {}  # org -> (run_id, snapshot)
        self._versions: dict[str, tuple[float, str]] = {}  # org -> (checked monotonic, version)

    def reset(self) -> None:
        self._snapshots.clear()
        self._versions.clear()

    def _lock(self, org: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(org, threading.Lock())

    # --- configuration -------------------------------------------------------------------

    def thresholds(self, org: str) -> tuple[PopulationThresholds, int, datetime | None, str | None]:
        with population_session() as s:
            row = s.get(ThresholdConfig, org)
            if row is None:
                return DEFAULT_THRESHOLDS, 0, None, None
            return PopulationThresholds.model_validate(row.thresholds), row.version, row.updated_at, row.updated_by

    def update_thresholds(self, org: str, new: PopulationThresholds, actor: str) -> int:
        with population_session() as s:
            row = s.get(ThresholdConfig, org)
            if row is None:
                row = ThresholdConfig(organization_key=org, version=0, thresholds={}, updated_at=_now())
                s.add(row)
            row.version += 1
            row.thresholds, row.updated_at, row.updated_by = new.model_dump(), _now(), actor
            version = row.version
        self._versions.pop(org, None)
        return version

    # --- data version ----------------------------------------------------------------------

    def data_version(self, org: str, *, force: bool = False) -> str:
        cached = self._versions.get(org)
        if not force and cached and _time.monotonic() - cached[0] < settings.population_freshness_check_seconds:
            return cached[1]
        _, config_version, _, _ = self.thresholds(org)
        with facts_provider() as fp:
            version = f"{fp.data_version(org)}-c{config_version}"
        self._versions[org] = (_time.monotonic(), version)
        return version

    # --- refresh ---------------------------------------------------------------------------

    def refresh(self, org: str, *, trigger: str, requested_by: str | None = None) -> dict[str, Any]:
        lock = self._lock(org)
        if not lock.acquire(blocking=False):
            raise RefreshInProgress(org)
        try:
            return self._refresh_locked(org, trigger, requested_by)
        finally:
            lock.release()

    def _refresh_locked(self, org: str, trigger: str, requested_by: str | None) -> dict[str, Any]:
        started = _now()
        run_id = str(uuid.uuid4())
        try:
            with population_session() as s:
                cutoff = started - timedelta(seconds=settings.population_refresh_timeout_seconds)
                for stale in s.scalars(select(AggregationRun).where(
                        AggregationRun.organization_key == org, AggregationRun.status == "running",
                        AggregationRun.started_at < cutoff)):
                    stale.status, stale.finished_at, stale.error_code = "failed", started, "abandoned"
                s.flush()
                s.add(AggregationRun(run_id=run_id, organization_key=org, status="running", trigger=trigger,
                                     requested_by=requested_by, started_at=started, engine_version=ENGINE_VERSION,
                                     summary={}))
        except IntegrityError as exc:
            raise RefreshInProgress(org) from exc
        try:
            thresholds, config_version, _, _ = self.thresholds(org)
            with facts_provider() as fp:
                version = f"{fp.data_version(org)}-c{config_version}"
                facts = fp.fetch(org)
            snapshot = build_snapshot(facts, thresholds, config_version=config_version, generated_at=_now())
            candidates = snapshot.pop("alert_candidates")
            finished = _now()
            with population_session() as s:
                self._upsert_areas(s, snapshot, finished)
                alerts = sync_alerts(s, org, run_id, candidates, finished, facts.latest_data_at)
                run = s.get(AggregationRun, run_id)
                run.status, run.finished_at, run.snapshot = "succeeded", finished, snapshot
                run.data_version, run.config_version, run.source_run_id = version, config_version, facts.source_run_id
                run.as_of, run.latest_data_at = facts.as_of, facts.latest_data_at
                run.complete_through = facts.as_of - timedelta(days=thresholds.reporting_delay_days)
                run.summary = {"alerts": alerts, "alert_candidates": len(candidates),
                               "areas": len(snapshot["areas"]),
                               "duration_ms": round((finished - started).total_seconds() * 1000, 1)}
                s.flush()
                self._prune(s, org)
                out = run_dict(run)
            self._snapshots[org] = (run_id, snapshot)
            self._versions[org] = (_time.monotonic(), version)
            logger.info("population aggregation succeeded", extra={"population": {
                "run_id": run_id, "organization_key": org, "trigger": trigger, **out["summary"]}})
            return out
        except Exception as exc:
            logger.exception("population aggregation failed (run_id=%s, org=%s)", run_id, org)
            with population_session() as s:
                run = s.get(AggregationRun, run_id)
                if run is not None and run.status == "running":
                    run.status, run.finished_at, run.error_code = "failed", _now(), type(exc).__name__[:64]
            raise

    @staticmethod
    def _upsert_areas(s: Session, snapshot: dict[str, Any], at: datetime) -> None:
        existing = {a.area_id: a for a in s.scalars(select(GeoArea))}
        levels = ("country", "state", "district", "local_area", "city")
        for level in levels:  # parents first (self-referencing foreign key)
            for aid, e in snapshot["areas"].items():
                a = e["area"]
                if a["level"] != level:
                    continue
                row = existing.get(aid)
                if row is None:
                    row = GeoArea(area_id=aid, first_seen_at=at)
                    s.add(row)
                row.level, row.parent_area_id, row.name_en, row.name_ar = a["level"], a["parent_area_id"], a["name_en"], a["name_ar"]
                row.region_id, row.source, row.verification_status = a["region_id"], a["source"], a["verification_status"]
                row.source_label, row.updated_at = a["name_en"], at
            s.flush()

    @staticmethod
    def _prune(s: Session, org: str) -> None:
        keep = list(s.scalars(select(AggregationRun.run_id).where(
            AggregationRun.organization_key == org, AggregationRun.status != "running")
            .order_by(AggregationRun.started_at.desc()).limit(settings.population_runs_retained)))
        s.execute(delete(AggregationRun).where(
            AggregationRun.organization_key == org, AggregationRun.status != "running",
            AggregationRun.run_id.not_in(keep)))

    def refresh_quietly(self, org: str, trigger: str) -> None:
        """Background-task entry point: never raises (a concurrent refresh simply wins)."""
        try:
            self.refresh(org, trigger=trigger)
        except Exception:  # RefreshInProgress, or a failure already logged with its run id
            pass

    # --- reads -----------------------------------------------------------------------------

    def latest_run(self, org: str, *, include_running: bool = False) -> AggregationRun | None:
        statuses = ("succeeded", "running", "failed") if include_running else ("succeeded",)
        with population_session() as s:
            return s.scalars(select(AggregationRun).options(defer(AggregationRun.snapshot)).where(
                AggregationRun.organization_key == org, AggregationRun.status.in_(statuses))
                .order_by(AggregationRun.started_at.desc())).first()

    @staticmethod
    def _load_snapshot(run_id: str) -> dict[str, Any]:
        with population_session() as s:
            return s.scalar(select(AggregationRun.snapshot).where(AggregationRun.run_id == run_id))

    def current_snapshot(self, org: str, *, schedule=None) -> SnapshotView:
        """`schedule(fn, *args)` (FastAPI BackgroundTasks.add_task) receives stale refreshes."""
        run = self.latest_run(org)
        if run is None:
            try:
                self.refresh(org, trigger="on_demand")
            except RefreshInProgress:
                for _ in range(50):  # another request is computing the first snapshot
                    _time.sleep(0.1)
                    if (run := self.latest_run(org)) is not None:
                        break
                else:
                    raise
            run = run or self.latest_run(org)
        cached = self._snapshots.get(org)
        if cached is None or cached[0] != run.run_id:
            self._snapshots[org] = cached = (run.run_id, self._load_snapshot(run.run_id))
        snapshot = cached[1]
        age = (_now() - run.finished_at).total_seconds()
        data_changed = self.data_version(org) != run.data_version
        stale = data_changed or age > settings.population_max_snapshot_age_seconds
        scheduled = False
        if stale and schedule is not None:
            schedule(self.refresh_quietly, org, "stale_data")
            scheduled = True
        return SnapshotView(run_dict(run), snapshot, stale, data_changed, scheduled)


_service = PopulationService()


def get_population_service() -> PopulationService:
    return _service
