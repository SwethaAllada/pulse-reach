"""Database access for the `population` tables (same pattern as `identity.store`).

- `DATA_SOURCE=db`: the shared PostgreSQL engine; tables come from migration 0012.
- `DATA_SOURCE=memory`: a separate in-process SQLite database created from the ORM models (lost on
  restart, like the rest of memory mode). Its lock is independent of the identity store, so a
  population session may record identity audit events after it has been closed.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.session import DatabaseNotConfigured, get_engine
from app.models.population import POPULATION_SCHEMA, population_metadata

_SQLITE_LOCK = threading.RLock()


def _sqlite_engine() -> Engine:
    eng = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _record):  # pragma: no cover - driver hook
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    eng = eng.execution_options(schema_translate_map={POPULATION_SCHEMA: None})
    population_metadata.create_all(eng)
    return eng


@lru_cache(maxsize=1)
def get_population_engine() -> Engine:
    return get_engine() if settings.data_source == "db" else _sqlite_engine()


@contextmanager
def population_session() -> Iterator[Session]:
    """One unit of work; commits on success. IntegrityError propagates (callers map it)."""
    try:
        engine = get_population_engine()
    except DatabaseNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Population store is not configured.") from exc
    lock = _SQLITE_LOCK if engine.dialect.name == "sqlite" else nullcontext()
    with lock:
        session = Session(engine, expire_on_commit=False)
        try:
            yield session
            session.commit()
        except (HTTPException, IntegrityError):
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise HTTPException(status_code=503, detail="Population store is unavailable.") from exc
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()


def reset_population_store() -> None:
    """Memory mode / tests only: drop and recreate the in-process population database."""
    engine = get_population_engine()
    if engine.dialect.name != "sqlite":
        raise RuntimeError("reset_population_store is only available for the in-memory store")
    from app.models.population import GeoArea

    with _SQLITE_LOCK, engine.begin() as conn:
        for table in reversed(population_metadata.sorted_tables):
            if table is GeoArea.__table__:  # self-referencing: children before parents
                for levels in (("city", "local_area"), ("district",), ("state",), ("country",)):
                    conn.execute(table.delete().where(table.c.level.in_(levels)))
            conn.execute(table.delete())
