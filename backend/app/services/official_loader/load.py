"""Database side of the `official` loader (strategy §2.1, §6): idempotent, all-or-nothing per unit.

Units of work: O-A (source, source_file, region) · O-B (one indicator file: indicator, dimensions, members,
observations) · O-C (license_status_map and all nine facility layers). A unit that fails validation or a
database constraint writes nothing and is reported as quarantined; the other units still load.
Reconciliation mismatches are reported and never block ingestion.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from app.models import official as m

from . import parse as P

LOCK_KEY = 0x50524F46  # advisory lock "PROF": one official loader at a time
CHUNK = 5000
MEMBER_COLS = ("canonical_key", "member_role", "region_id", "scheme_code", "age_min_months", "age_max_months",
               "correction_state", "label_corrected_en", "correction_basis")
_OBS_COMPARE = ("source_row_ordinal", "period_year", "period_type", "obs_date_raw", *m.MEMBER_COLUMNS, "value",
                "value_marker_raw", "row_role", "quality_flag")
_FAC_SKIP = {"facility_id", "transform_version"}


def _diff(existing: dict, wanted: dict, cols=None) -> dict:
    cols = cols or wanted.keys()
    return {c: (existing[c], wanted[c]) for c in cols if existing[c] != wanted[c]}


def _chunks(rows: list, n: int = CHUNK):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


class Counter:
    """Per-table planned / inserted / skipped counts for the load report."""

    def __init__(self):
        self.t: dict[str, dict[str, int]] = {}

    def add(self, table: str, planned=0, inserted=0, skipped=0):
        c = self.t.setdefault(table, {"planned": 0, "inserted": 0, "skipped": 0})
        c["planned"] += planned
        c["inserted"] += inserted
        c["skipped"] += skipped


# --------------------------------------------------------------------------------------------------
# plan (P1-P3): everything is read, verified and validated in memory first
# --------------------------------------------------------------------------------------------------
class Plan:
    def __init__(self, root: Path):
        self.root = root
        self.quarantine: list[dict] = []
        self.findings: list[str] = []
        self.verified = P.verify_raw_files(root)
        self.manifest, self.manifest_sha256 = P.load_manifest(root)
        self.sources = P.source_rows(self.manifest)
        self.files, self.unmapped = P.source_file_rows(root, self.verified, self.manifest)
        if self.unmapped:
            self.findings.append(f"unmapped_file (checksum verified, not registered; OU-14): {self.unmapped}")
        no_file = {s["source_id"] for s in self.sources
                   if s["acquisition_state"] in ("dataset_obtained", "document_obtained")} - {
            f["source_id"] for f in self.files}
        if no_file:
            raise P.FatalError(f"obtained sources without a registered file: {sorted(no_file)}")
        if any(f["retrieved_at"] is None for f in self.files):
            n = sum(f["retrieved_at"] is None for f in self.files)
            self.findings.append(f"retrieved_at is NULL (not recorded) on {n} of {len(self.files)} files (OU-13)")

        meta = P.metadata_rel_paths(self.verified)
        self.units: list[P.IndicatorUnit] = []
        for rel in sorted(r for r in self.verified if r.startswith("data/raw/statad_api/indicator_detail/")):
            try:
                self.units.append(P.parse_indicator_file(root, rel, meta))
            except P.UnitError as exc:
                self.quarantine.append({"unit": rel, "sha256": self.verified[rel]["sha256"], "reason": str(exc)})
        for u in self.units:
            self.findings.extend(u.warnings)
        unbounded = sorted({k[1] for u in self.units for k, s in u.members.items() if k[0] == "age_group"
                            and s["member_role"] == "leaf" and s["correction_state"] == "none"
                            and s["age_min_months"] is None})
        if unbounded:  # kept verbatim as strings; the mapping defines no bounds for them (e.g. spaced "15 - 19")
            self.findings.append(f"age_group labels without month bounds (no mapping rule): {unbounded}")

        self.regions = P.region_rows(self.units)
        sdi_rels = {Path(r).stem: r for r in self.verified if r.startswith("data/raw/abudhabi_sdi/")
                    and r.endswith(".geojson")}
        self.facilities: P.FacilityUnit | None = None
        try:
            self.facilities = P.parse_facilities(
                root, {r["sdi_label"]: r["region_id"] for r in self.regions}, sdi_rels)
        except P.UnitError as exc:
            self.quarantine.append({"unit": "facility register (all 9 layers)", "reason": str(exc)})
        if self.facilities and self.facilities.region_labels != {r[3] for r in P.REGIONS}:
            raise P.FatalError(f"SDI REGION values {sorted(self.facilities.region_labels)} differ from the "
                               "three expected labels")
        self.expected_checks = self._expected()

    def counts(self) -> dict[str, int]:
        obs = [o for u in self.units for o in u.observations]
        members = {k for u in self.units for k in u.members}
        c = {
            "source": len(self.sources), "source_file": len(self.files), "region": len(self.regions),
            "indicator": len(self.units), "indicator_dimension": sum(len(u.dimensions) for u in self.units),
            "dimension_member": len(members), "observation": len(obs),
            "observation_leaf": sum(o["row_role"] == "leaf" for o in obs),
            "observation_aggregate": sum(o["row_role"] == "aggregate" for o in obs),
            "observation_flagged": sum(o["quality_flag"] is not None for o in obs),
        }
        if self.facilities:
            f = self.facilities.rows
            c.update(facility=len(f), facility_identified=sum(r["identity_status"] == "identified" for r in f),
                     facility_unidentified=sum(r["identity_status"] == "unidentified" for r in f),
                     license_status_map=len(self.facilities.license_statuses))
        return c

    def _expected(self) -> list[dict]:
        actual = self.counts()
        out = [{"name": k, "expected": exp, "actual": actual.get(k), "blocking": blocking,
                "ok": actual.get(k) == exp} for k, (exp, blocking) in P.EXPECTED.items()]
        if self.facilities:
            out += [{"name": f"geo_quality.{k}", "expected": v, "actual": self.facilities.geo_counts.get(k),
                     "blocking": True, "ok": self.facilities.geo_counts.get(k) == v}
                    for k, v in P.EXPECTED_GEO.items()]
        return out

    def blocking_failures(self) -> list[dict]:
        return [c for c in self.expected_checks if c["blocking"] and not c["ok"]]


# --------------------------------------------------------------------------------------------------
# O-A: source, source_file, region
# --------------------------------------------------------------------------------------------------
def _load_sources(conn, plan: Plan, ctr: Counter) -> dict[str, int]:
    existing = {r.source_id: dict(r._mapping) for r in conn.execute(select(m.Source))}
    for row in plan.sources:
        ctr.add("source", planned=1)
        old = existing.get(row["source_id"])
        if old is None:
            conn.execute(insert(m.Source), row)
            ctr.add("source", inserted=1)
        elif old["manifest_version"] == row["manifest_version"]:
            if d := _diff(old, row):
                raise P.FatalError(f"{row['source_id']}: manifest edited without a version bump: {d}")
            ctr.add("source", skipped=1)
        else:
            conn.execute(m.Source.__table__.update().where(m.Source.source_id == row["source_id"]).values(**row))
            ctr.add("source", inserted=1)
    existing_files = {r.relative_path: dict(r._mapping) for r in conn.execute(select(m.SourceFile))}
    ids: dict[str, int] = {}
    attrs = ("source_id", "file_role", "byte_size", "contains_data", "fit_for_use", "retrieved_at",
             "source_effective_note")
    for row in plan.files:
        ctr.add("source_file", planned=1)
        old = existing_files.get(row["relative_path"])
        if old is None:
            ids[row["relative_path"]] = conn.execute(
                insert(m.SourceFile).returning(m.SourceFile.source_file_id), row).scalar_one()
            ctr.add("source_file", inserted=1)
            continue
        if old["sha256"] != row["sha256"]:
            raise P.FatalError(f"{row['relative_path']}: hash changed for a registered path (raw is immutable; "
                               "a new vintage needs a new path)")
        if d := _diff(old, row, attrs):
            raise P.FatalError(f"{row['relative_path']}: registered attributes changed: {d}")
        ids[row["relative_path"]] = old["source_file_id"]
        ctr.add("source_file", skipped=1)
    return ids


def _load_regions(conn, plan: Plan, ctr: Counter) -> None:
    existing = {r.region_code: dict(r._mapping) for r in conn.execute(select(m.Region))}
    for row in plan.regions:
        ctr.add("region", planned=1)
        old = existing.get(row["region_code"])
        if old is None:
            conn.execute(insert(m.Region), row)
            ctr.add("region", inserted=1)
        elif d := _diff(old, row):
            raise P.FatalError(f"region {row['region_code']}: labels changed: {d}")
        else:
            ctr.add("region", skipped=1)


# --------------------------------------------------------------------------------------------------
# O-B: one indicator file
# --------------------------------------------------------------------------------------------------
def _member_cache(conn) -> dict[tuple, dict]:
    return {(r.dimension_type, r.raw_label_en, r.raw_label_ar): dict(r._mapping)
            for r in conn.execute(select(m.DimensionMember))}


def _load_indicator(conn, plan: Plan, u: P.IndicatorUnit, file_ids: dict[str, int], ctr: Counter) -> None:
    file_id = file_ids[u.rel_path]
    # A second vintage cannot be ordered while retrieved_at is NULL (OFF §3): refuse rather than guess.
    other = conn.execute(text("SELECT DISTINCT source_file_id FROM official.observation WHERE indicator_id = :i "
                              "AND source_file_id <> :f"), {"i": u.indicator_id, "f": file_id}).all()
    if other:
        raise P.UnitError(f"indicator {u.indicator_id} already has observations from another source file "
                          f"{[r[0] for r in other]}; a second vintage is refused")
    row = dict(u.indicator, metadata_source_file_id=file_ids.get(u.metadata_rel_path) if u.metadata_rel_path else None)
    old = conn.execute(select(m.Indicator).where(m.Indicator.indicator_id == u.indicator_id)).first()
    ctr.add("indicator", planned=1)
    if old is None:
        conn.execute(insert(m.Indicator), row)
        ctr.add("indicator", inserted=1)
    elif d := _diff(dict(old._mapping), row):
        raise P.UnitError(f"indicator {u.indicator_id}: definition differs from the stored one: {d}")
    else:
        ctr.add("indicator", skipped=1)

    have = {r.dimension_type: dict(r._mapping) for r in conn.execute(
        select(m.IndicatorDimension).where(m.IndicatorDimension.indicator_id == u.indicator_id))}
    for d_ in u.dimensions:
        ctr.add("indicator_dimension", planned=1)
        if d_["dimension_type"] not in have:
            conn.execute(insert(m.IndicatorDimension), d_)
            ctr.add("indicator_dimension", inserted=1)
        elif diff := _diff(have[d_["dimension_type"]], d_):
            raise P.UnitError(f"indicator {u.indicator_id}: dimension differs from the stored one: {diff}")
        else:
            ctr.add("indicator_dimension", skipped=1)
    if set(have) - {d_["dimension_type"] for d_ in u.dimensions}:
        raise P.UnitError(f"indicator {u.indicator_id}: stored dimensions the file no longer has")

    cache = _member_cache(conn)
    new = [spec for key, spec in u.members.items() if key not in cache]
    for key, spec in u.members.items():
        if key in cache and (d := _diff(cache[key], spec, MEMBER_COLS)):
            raise P.UnitError(f"member {key}: stored role/bounds differ from the computed ones: {d}")
    if new:
        conn.execute(insert(m.DimensionMember), new)
        cache = _member_cache(conn)
    ctr.add("dimension_member", planned=len(u.members), inserted=len(new), skipped=len(u.members) - len(new))

    wanted = []
    for o in u.observations:
        r = {c: o[c] for c in ("indicator_id", "period_year", "period_type", "obs_date_raw", "value",
                               "value_marker_raw", "row_role", "source_row_ordinal", "quality_flag")}
        r.update(source_file_id=file_id, loader_version=P.LOADER_VERSION, **{c: None for c in m.MEMBER_COLUMNS})
        for dim, key in o["members"].items():
            r[f"{dim}_member_id"] = cache[key]["member_id"]
        wanted.append(r)
    ctr.add("observation", planned=len(wanted))
    existing = conn.execute(select(*[getattr(m.Observation, c) for c in _OBS_COMPARE]).where(
        m.Observation.source_file_id == file_id).order_by(m.Observation.source_row_ordinal)).all()
    if existing:  # file-level idempotency: identical -> skip; anything else -> fail; never a partial insert
        got = [tuple(r) for r in existing]
        want = [tuple(w[c] for c in _OBS_COMPARE) for w in wanted]
        if got != want:
            raise P.UnitError(f"{u.rel_path}: {len(got)} stored rows differ from the {len(want)} in the file")
        ctr.add("observation", skipped=len(wanted))
        return
    for chunk in _chunks(wanted):
        conn.execute(insert(m.Observation), chunk)
    ctr.add("observation", inserted=len(wanted))


# --------------------------------------------------------------------------------------------------
# O-C: license_status_map + facilities
# --------------------------------------------------------------------------------------------------
def _load_facilities(conn, plan: Plan, file_ids: dict[str, int], ctr: Counter) -> None:
    fu = plan.facilities
    statuses = [{"raw_value": s, "review_state": "unreviewed"} for s in fu.license_statuses]
    new_status = conn.execute(pg_insert(m.LicenseStatusMap).on_conflict_do_nothing(index_elements=["raw_value"])
                              .returning(m.LicenseStatusMap.raw_value), statuses).all() if statuses else []
    ctr.add("license_status_map", planned=len(statuses), inserted=len(new_status),
            skipped=len(statuses) - len(new_status))  # never updates a reviewed row
    rel_by_layer = {Path(f["relative_path"]).stem: f["relative_path"] for f in plan.files
                    if f["file_role"] == "facility_geojson"}
    wanted = [dict(r, source_file_id=file_ids[rel_by_layer[r["source_layer"]]], transform_version=P.TRANSFORM_VERSION)
              for r in fu.rows]
    ctr.add("facility", planned=len(wanted))
    have = {(r.source_layer, r.source_object_id): dict(r._mapping) for r in conn.execute(select(m.Facility))}
    if not have:
        for chunk in _chunks(wanted):
            conn.execute(insert(m.Facility), chunk)
        ctr.add("facility", inserted=len(wanted))
        return
    keys = {(w["source_layer"], w["source_object_id"]) for w in wanted}
    if keys != set(have):
        raise P.UnitError(f"stored register has {len(have)} features, file has {len(keys)}; a second register "
                          "vintage is refused (uniques are not vintage-aware, OU-17)")
    bad = [k for w in wanted for k in [(w["source_layer"], w["source_object_id"])]
           if _diff(have[k], w, [c for c in w if c not in _FAC_SKIP])]
    if bad:
        raise P.UnitError(f"{len(bad)} stored facilities differ from the file, e.g. {bad[:3]}")
    ctr.add("facility", skipped=len(wanted))


# --------------------------------------------------------------------------------------------------
# P7-P8: post-load checks and reconciliation report (never blocking)
# --------------------------------------------------------------------------------------------------
_MEMBER_COLUMNS = {t: f"{t}_member_id" for t in P.DIMENSION_TYPES}
POST_CHECKS = {
    # both directions of indicator_dimension <-> non-null observation member columns (strategy §7)
    "indicator_dimension_never_used_by_its_observations": " UNION ALL ".join(
        f"SELECT count(*) FROM official.indicator_dimension d WHERE d.dimension_type = '{t}' "
        f"AND EXISTS (SELECT 1 FROM official.observation o WHERE o.indicator_id = d.indicator_id) "
        f"AND NOT EXISTS (SELECT 1 FROM official.observation o WHERE o.indicator_id = d.indicator_id "
        f"AND o.{c} IS NOT NULL)" for t, c in _MEMBER_COLUMNS.items()),
    "observation_member_without_indicator_dimension": " UNION ALL ".join(
        f"SELECT count(*) FROM official.observation o WHERE o.{c} IS NOT NULL AND NOT EXISTS ("
        f"SELECT 1 FROM official.indicator_dimension d WHERE d.indicator_id = o.indicator_id "
        f"AND d.dimension_type = '{t}')" for t, c in _MEMBER_COLUMNS.items()),
    "observation_source_file_not_a_detail_file_of_its_indicator": (
        "SELECT count(*) FROM official.observation o JOIN official.source_file f "
        "ON f.source_file_id = o.source_file_id WHERE f.file_role <> 'indicator_detail' "
        "OR f.relative_path NOT LIKE '%/' || o.indicator_id::text || '\\_%'"),
    "facility_source_file_not_a_facility_geojson": (
        "SELECT count(*) FROM official.facility x JOIN official.source_file f "
        "ON f.source_file_id = x.source_file_id WHERE f.file_role <> 'facility_geojson'"),
}


def post_load_checks(conn) -> dict[str, int]:
    """Orphan / cross-reference queries; every value should be 0. Reported, and a non-zero value is a finding."""
    return {name: sum(r[0] for r in conn.execute(text(sql))) for name, sql in POST_CHECKS.items()}


RECON_SQL = """
WITH ndims AS (SELECT indicator_id, count(*) n FROM official.indicator_dimension GROUP BY 1),
s AS (SELECT v.*, i.unit_raw, n.n AS n_dims FROM official.v_indicator_year_shape v
        JOIN official.indicator i USING (indicator_id) JOIN ndims n USING (indicator_id))
SELECT {select} FROM s WHERE {where}
"""


def _q(conn, select_: str, where: str) -> list:
    return conn.execute(text(RECON_SQL.format(select=select_, where=where))).all()


def reconciliation_report(conn) -> dict:
    """Classified shape of the loaded data (strategy §8). A report, never an assertion and never a failure.

    Scope is the Phase 3 baseline's: indicators whose unit_raw is People/Number (rates and percentages are
    non-additive and were never tested). `measure_kind` is unclassified until a reviewed seed exists, so the
    scope is taken from the verbatim unit.
    """
    people = "unit_raw IN ('People','Number')"
    one, many = f"n_dims = 1 AND {people}", f"n_dims >= 2 AND {people}"

    def by(where: str, col: str, extra: str = "") -> dict:
        return {str(r[0]): r[1] for r in _q(conn, f"{col}, count(*)", f"{where} {extra} GROUP BY 1")}

    return {
        "scope": "unit_raw People/Number (as in the Phase 3 baseline)",
        "single_dimension": {"cells_by_state": by(one, "cell_state"),
                             "mismatch_classes": by(one, "mismatch_class", "AND cell_state = 'mismatch'")},
        "multi_dimension": {"slices_by_state": by(many, "cell_state"),
                            "mismatch_classes": by(many, "mismatch_class", "AND cell_state = 'mismatch'"),
                            "not_testable_by_reason": by(many, "not_testable_reason", "AND cell_state = 'not_testable'")},
        # The Phase 3 screen: one aggregate and >= 1 leaf in the slice, the fixed members of any kind.
        "phase3_baseline_screen_multi_dimension": dict(zip(
            ("tested", "reconcile", "mismatch", "mismatch_leaves_all_zero", "mismatch_leaves_below",
             "mismatch_leaves_above", "not_tested"),
            _q(conn, """count(*) FILTER (WHERE n_aggregate_members = 1 AND n_leaf_members >= 1 AND n_null_values = 0),
                        count(*) FILTER (WHERE n_aggregate_members = 1 AND n_leaf_members >= 1 AND leaf_sum = aggregate_value),
                        count(*) FILTER (WHERE n_aggregate_members = 1 AND n_leaf_members >= 1 AND leaf_sum <> aggregate_value),
                        count(*) FILTER (WHERE n_aggregate_members = 1 AND n_leaf_members >= 1 AND leaf_sum = 0 AND aggregate_value > 0),
                        count(*) FILTER (WHERE n_aggregate_members = 1 AND n_leaf_members >= 1 AND leaf_sum < aggregate_value AND leaf_sum > 0),
                        count(*) FILTER (WHERE n_aggregate_members = 1 AND n_leaf_members >= 1 AND leaf_sum > aggregate_value),
                        count(*) FILTER (WHERE NOT (n_aggregate_members = 1 AND n_leaf_members >= 1))""", many)[0])),
        "rc_unexplained_cells": [list(map(str, r)) for r in _q(
            conn, "indicator_id, period_year, dimension_type, aggregate_value, leaf_sum, difference",
            f"{people} AND mismatch_class = 'RC-UNEXPLAINED'")],
    }


# --------------------------------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------------------------------
def run(root: Path | None = None, engine: Engine | None = None, dry_run: bool = False) -> dict:
    """Execute the loader. Returns the load report (a dict). Raises `FatalError` when nothing may be written."""
    root = root or P.repo_root()
    started = datetime.now(timezone.utc)
    plan = Plan(root)
    report = {
        "loader_version": P.LOADER_VERSION, "transform_version": P.TRANSFORM_VERSION,
        "started_utc": started.isoformat(timespec="seconds"), "dry_run": dry_run,
        "manifest_version": plan.sources[0]["manifest_version"], "manifest_sha256": plan.manifest_sha256,
        "files_verified": len(plan.verified), "files_registered": len(plan.files), "files_unmapped": plan.unmapped,
        "planned_counts": plan.counts(), "expected_checks": plan.expected_checks, "findings": plan.findings,
        "quarantined": plan.quarantine, "tables": {}, "post_load_checks": None, "reconciliation": None,
    }
    if bad := plan.blocking_failures():
        report["status"] = "FATAL"
        raise P.FatalError("expected counts differ before any write: " + json.dumps(bad))
    if dry_run:
        report["status"] = "DRY-RUN" if not plan.quarantine else "DRY-RUN-WITH-QUARANTINE"
        return _finish(report)
    if engine is None:
        from app.db.session import get_engine
        engine = get_engine()
    ctr = Counter()
    with engine.connect() as lock:  # session advisory lock held for the whole run
        lock.execute(text("SELECT 1"))
        if not lock.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar():
            raise P.FatalError("another official loader run holds the advisory lock")
        try:
            if lock.execute(text("SELECT to_regclass('official.v_indicator_year_shape')")).scalar() is None:
                raise P.FatalError("the official schema/views are missing; run `alembic upgrade head` first")
            file_ids: dict[str, int] = {}
            with engine.begin() as conn:  # O-A: a failure here is fatal; nothing else has been written
                file_ids = _load_sources(conn, plan, ctr)
                _load_regions(conn, plan, ctr)
            for u in plan.units:  # O-B, one transaction per indicator file
                try:
                    with engine.begin() as conn:
                        _load_indicator(conn, plan, u, file_ids, ctr)
                except Exception as exc:  # noqa: BLE001 - quarantine, report, continue
                    plan.quarantine.append({"unit": u.rel_path, "reason": f"{type(exc).__name__}: {exc}"[:600]})
            if plan.facilities:  # O-C
                try:
                    with engine.begin() as conn:
                        _load_facilities(conn, plan, file_ids, ctr)
                except Exception as exc:  # noqa: BLE001
                    plan.quarantine.append({"unit": "facility register (all 9 layers)",
                                            "reason": f"{type(exc).__name__}: {exc}"[:600]})
            with engine.connect() as conn:
                report["post_load_checks"] = post_load_checks(conn)
                report["reconciliation"] = reconciliation_report(conn)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
    report["tables"] = ctr.t
    report["quarantined"] = plan.quarantine
    report["status"] = "INGESTED" if not plan.quarantine else "INGESTED-WITH-QUARANTINE"
    return _finish(report)


def _finish(report: dict) -> dict:
    report["finished_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    body = json.dumps(report, sort_keys=True, default=str).encode()
    report["report_sha256"] = hashlib.sha256(body).hexdigest()
    return report
