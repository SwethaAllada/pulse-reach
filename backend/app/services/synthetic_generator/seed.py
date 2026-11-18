"""Repeatable CLI command to seed clinical rules and synthetic data into PostgreSQL (T-03).

Usage:
    python -m app.services.synthetic_generator.seed --seed 20261116 --total-patients 550
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from app.db.session import DatabaseNotConfigured, get_engine
from app.services.clinical_loader.load import load_clinical_bundle
from app.services.clinical_loader.parse import parse_clinical_bundle
from app.services.synthetic_generator.generator import generate_synthetic_dataset
from app.services.synthetic_generator.load import load_synthetic_dataset


def seed_database(*, seed: int = 20261116, total_patients: int = 550, replace: bool = True) -> None:
    bundle = parse_clinical_bundle()
    ds = generate_synthetic_dataset(seed=seed, total_patients=total_patients, bundle=bundle)
    engine = get_engine()
    with Session(engine) as session:
        load_clinical_bundle(session, bundle)
        load_synthetic_dataset(session, ds, replace=replace)
        session.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed clinical rules and synthetic data into PostgreSQL.")
    parser.add_argument("--seed", type=int, default=20261116)
    parser.add_argument("--total-patients", type=int, default=550)
    parser.add_argument("--no-replace", action="store_true")
    args = parser.parse_args(argv)
    try:
        seed_database(seed=args.seed, total_patients=args.total_patients, replace=not args.no_replace)
    except DatabaseNotConfigured as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"Seeded clinical bundle + {args.total_patients} synthetic patients (seed={args.seed}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
