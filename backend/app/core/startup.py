"""Fail-fast startup validation (BE-22).

The API refuses to start when the clinical rules it would evaluate against are missing or
invalid, instead of failing on the first request. In `DATA_SOURCE=db` it also requires the
database to hold a clinical load of the same bundle and a seeded run, so a deployment never
serves evaluations produced under different rules than the ones it explains.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text

from app.core.config import Settings

logger = logging.getLogger("pulsereach.startup")


class StartupValidationError(RuntimeError):
    """Required clinical rules or seeded data are unavailable; the API must not start."""


@dataclass(frozen=True)
class StartupReport:
    bundle_sha256: str
    rules: int
    authoritative_rules: int
    data_source: str
    db_rule_load_id: int | None = None


def validate_startup(cfg: Settings) -> StartupReport:
    from app.repositories.read_repo import get_cached_bundle

    try:
        bundle = get_cached_bundle()
    except Exception as exc:  # parse errors, missing files, manifest mismatch
        get_cached_bundle.cache_clear()
        raise StartupValidationError(
            f"Clinical rule bundle could not be loaded ({type(exc).__name__}: {exc}). "
            "Check RULES_DIR / DATA_DIR."
        ) from exc
    if not bundle.rules:
        raise StartupValidationError("Clinical rule bundle contains no rules.")
    report = StartupReport(
        bundle_sha256=bundle.bundle_sha256,
        rules=len(bundle.rules),
        authoritative_rules=sum(1 for r in bundle.rules if r["is_authoritative"]),
        data_source=cfg.data_source,
    )
    if cfg.data_source != "db":
        return report

    from app.db.session import DatabaseNotConfigured, build_engine

    engine = None
    try:
        engine = build_engine(cfg)
        with engine.connect() as conn:
            latest = conn.execute(
                text("SELECT load_id, bundle_sha256 FROM clinical.rule_load ORDER BY load_id DESC LIMIT 1")
            ).first()
            seeded = conn.execute(text("SELECT count(*) FROM synthetic.generation_run")).scalar_one()
    except DatabaseNotConfigured as exc:
        raise StartupValidationError("DATA_SOURCE=db but DATABASE_URL is not configured.") from exc
    except Exception as exc:
        raise StartupValidationError(
            f"DATA_SOURCE=db but the database is unreachable or not migrated ({type(exc).__name__}). "
            "Run `alembic upgrade head` and the seed command."
        ) from exc
    finally:
        if engine is not None:
            engine.dispose()
    if latest is None:
        raise StartupValidationError("clinical.rule_load is empty: run the seed command first.")
    if latest.bundle_sha256 != bundle.bundle_sha256:
        raise StartupValidationError(
            f"Database clinical load {latest.load_id} ({latest.bundle_sha256[:12]}) does not match the "
            f"deployed rule bundle ({bundle.bundle_sha256[:12]}): reseed before starting."
        )
    if not seeded:
        raise StartupValidationError("No seeded synthetic run in the database: run the seed command.")
    return StartupReport(**{**report.__dict__, "db_rule_load_id": int(latest.load_id)})
