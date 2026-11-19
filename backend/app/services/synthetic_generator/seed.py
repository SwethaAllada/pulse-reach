"""Repeatable CLI command to seed clinical rules and synthetic data into PostgreSQL (T-03).

Fresh database, from `backend/` with `DATABASE_URL` set (environment or `backend/.env`):

    alembic upgrade head
    python -m app.services.official_loader
    python -m app.services.synthetic_generator.seed --seed 20261116 --total-patients 550

Steps: parse and validate the clinical YAML bundle; check that the official facility register is
loaded (synthetic facility service profiles reference real `official.facility` rows and are never
pointed at invented facilities); load `clinical.*` with the real loader
(`app.services.clinical_loader.run`, its own transaction with version/hash and authority checks);
then load `synthetic.*` and reconcile row counts in one transaction, rolled back on any mismatch.

Exit codes: 0 = seeded and reconciled · 2 = fatal (configuration, missing or invalid input,
missing prerequisite, database error or reconciliation mismatch; synthetic data not written).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import DatabaseNotConfigured, get_engine
from app.services.clinical_loader import FatalError as ClinicalFatalError
from app.services.clinical_loader import parse_clinical_bundle
from app.services.clinical_loader import run as load_clinical_bundle
from app.services.clinical_loader.parse import default_manifest_path, default_rules_dir
from app.services.synthetic_generator.generator import SyntheticDataset, generate_synthetic_dataset
from app.services.synthetic_generator.load import load_synthetic_dataset

# synthetic table -> SyntheticDataset attribute, for post-load reconciliation
_RECONCILED_TABLES = {
    "facility_service_profile": "facility_service_profiles",
    "patient": "patients",
    "guardian": "guardians",
    "consent": "consents",
    "history_availability": "history_availabilities",
    "eligibility_evaluation": "eligibility_evaluations",
    "evaluation_reason": "evaluation_reasons",
    "appointment": "appointments",
    "ifhas_screening": "ifhas_screenings",
    "well_child_visit": "well_child_visits",
    "component_result": "component_results",
    "assessment": "assessments",
    "referral": "referrals",
    "care_gap": "care_gaps",
    "care_gap_review": "care_gap_reviews",
    "outreach_event": "outreach_events",
}


class SeedError(RuntimeError):
    """A seed prerequisite or reconciliation check failed."""


def _check_official_facilities(engine: Engine, ds: SyntheticDataset) -> None:
    needed = len(ds.facility_service_profiles)
    with engine.connect() as conn:
        loaded = conn.execute(text("SELECT count(*) FROM official.facility")).scalar_one()
    if loaded < needed:
        raise SeedError(
            f"official.facility has {loaded} row(s); {needed} are needed for synthetic facility "
            "service profiles. Run `python -m app.services.official_loader` first."
        )


def _reconcile(conn: Connection, ds: SyntheticDataset, clinical_load_id: int) -> dict[str, Any]:
    run_id = ds.generation_run["run_id"]
    counts: dict[str, dict[str, int]] = {}
    mismatches: list[str] = []
    for table, attr in _RECONCILED_TABLES.items():
        expected = len(getattr(ds, attr))
        actual = conn.execute(
            text(f"SELECT count(*) FROM synthetic.{table} WHERE run_id = :run_id"),
            {"run_id": run_id},
        ).scalar_one()
        counts[table] = {"expected": expected, "loaded": actual}
        if actual != expected:
            mismatches.append(f"synthetic.{table}: expected {expected}, loaded {actual}")
    run_load_ids = conn.execute(
        text(
            "SELECT g.rule_bundle_load_id, e.rule_bundle_load_id FROM synthetic.generation_run g "
            "JOIN synthetic.evaluation_run e ON e.run_id = g.run_id WHERE g.run_id = :run_id"
        ),
        {"run_id": run_id},
    ).one()
    if set(run_load_ids) != {clinical_load_id}:
        mismatches.append(
            f"generation/evaluation run rule_bundle_load_id {tuple(run_load_ids)} != "
            f"clinical load {clinical_load_id}"
        )
    if mismatches:
        raise SeedError("reconciliation failed: " + "; ".join(mismatches))
    return counts


def seed_database(
    *,
    seed: int = 20261116,
    total_patients: int = 550,
    replace: bool = True,
    engine: Engine | None = None,
) -> dict[str, Any]:
    """Validate inputs, load `clinical.*` and `synthetic.*`, and return the reconciled report."""
    rules_dir, manifest_path = default_rules_dir(), default_manifest_path()
    bundle = parse_clinical_bundle(rules_dir=rules_dir, manifest_path=manifest_path)
    ds = generate_synthetic_dataset(seed=seed, total_patients=total_patients, bundle=bundle)
    eng = engine or get_engine()
    _check_official_facilities(eng, ds)

    clinical = load_clinical_bundle(
        eng, rules_dir=rules_dir, manifest_path=manifest_path, reuse_unchanged_load=True
    )
    if clinical.bundle_sha256 != bundle.bundle_sha256:
        raise SeedError(
            "clinical bundle changed during seeding: loaded "
            f"{clinical.bundle_sha256}, generated from {bundle.bundle_sha256}"
        )

    with eng.begin() as conn:
        synthetic = load_synthetic_dataset(conn, ds, reset_existing_run=replace)
        counts = _reconcile(conn, ds, clinical.load_id)
    return {"clinical": asdict(clinical), "synthetic": synthetic, "reconciliation": counts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed clinical rules and synthetic data into PostgreSQL.")
    parser.add_argument("--seed", type=int, default=20261116)
    parser.add_argument("--total-patients", type=int, default=550)
    parser.add_argument("--no-replace", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = seed_database(
            seed=args.seed, total_patients=args.total_patients, replace=not args.no_replace
        )
    except (ClinicalFatalError, yaml.YAMLError) as exc:
        print(f"FATAL: invalid clinical bundle: {exc}", file=sys.stderr)
        return 2
    except (DatabaseNotConfigured, SeedError) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2
    except SQLAlchemyError as exc:
        print(
            f"FATAL: database error ({type(exc).__name__}); synthetic data not written. "
            f"Has `alembic upgrade head` been run? {exc}".splitlines()[0],
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
