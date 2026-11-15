from functools import lru_cache

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, settings

# The three schemas of the Phase 3 design (docs/phase-3-database-design.md §1).
# Migration order matters: official -> clinical -> synthetic.
SCHEMAS = ("official", "clinical", "synthetic")

# Shared constraint naming (design §2.2) so names are stable across migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=NAMING_CONVENTION)


class DatabaseNotConfigured(RuntimeError):
    """DATABASE_URL is not set."""


def build_engine(cfg: Settings) -> Engine:
    if cfg.database_url is None:
        raise DatabaseNotConfigured("DATABASE_URL is not set")
    return create_engine(
        cfg.database_url.get_secret_value(),
        pool_size=cfg.db_pool_size,
        max_overflow=cfg.db_max_overflow,
        pool_timeout=cfg.db_pool_timeout,
        pool_recycle=cfg.db_pool_recycle,
        pool_pre_ping=True,
        connect_args={"connect_timeout": cfg.db_connect_timeout},
    )


@lru_cache
def get_engine() -> Engine:
    """Process-wide engine, created lazily so the app starts without a database."""
    return build_engine(settings)


def check_database(engine: Engine | None = None) -> None:
    """Raise if the database is unreachable. Never returns connection details."""
    with (engine or get_engine()).connect() as conn:
        conn.execute(text("SELECT 1"))


def database_status(engine: Engine | None = None) -> str:
    """'ok' | 'not_configured' | 'unavailable'"""
    try:
        check_database(engine)
    except DatabaseNotConfigured:
        return "not_configured"
    except SQLAlchemyError:
        return "unavailable"
    return "ok"
