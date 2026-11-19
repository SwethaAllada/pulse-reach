"""Initialise the database (`python -m app.db.init [--seed]`).

Tables and schemas are created only by migrations, never directly from here.

With `--seed` (used by the Compose `db-init` service) it is also safe to run on every start:
- applies migrations;
- loads the official register only when `official.facility` is empty;
- seeds clinical rules + synthetic data only when no synthetic run exists, so follow-up history
  recorded in a running deployment is never wiped by a restart. Reseed explicitly with
  `python -m app.services.synthetic_generator.seed`.
"""

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[2]


def init_db(revision: str = "head") -> None:
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), revision)


def bootstrap() -> dict:
    from app.db.session import get_engine
    from app.services import official_loader
    from app.services.synthetic_generator.seed import seed_database

    init_db()
    eng = get_engine()
    report: dict = {"migrated": True, "official_loaded": False, "seeded": False}
    with eng.connect() as conn:
        facilities = conn.execute(text("SELECT count(*) FROM official.facility")).scalar_one()
    if facilities == 0:
        loaded = official_loader.run(engine=eng)
        if loaded["quarantined"]:
            raise RuntimeError(f"official data quarantined: {loaded['quarantined']}")
        report["official_loaded"] = True
    with eng.connect() as conn:
        runs = conn.execute(text("SELECT count(*) FROM synthetic.generation_run")).scalar_one()
    if runs == 0:
        seed_database(engine=eng)
        report["seeded"] = True
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="app.db.init")
    ap.add_argument("--seed", action="store_true", help="also load official data and seed if empty")
    args = ap.parse_args(argv)
    if not args.seed:
        init_db()
        return 0
    print(bootstrap())
    return 0


if __name__ == "__main__":
    sys.exit(main())
