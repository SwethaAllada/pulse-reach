"""Database access for the identity/engagement tables.

- `DATA_SOURCE=db`: the shared PostgreSQL engine; tables come from migration 0011.
- `DATA_SOURCE=memory`: an in-process SQLite database (per worker, lost on restart, like the
  rest of memory mode) created from the ORM models with the schema names translated away. The
  service code is identical in both modes. SQLite allows one writer, so sessions are serialized
  with a process lock; never open a second identity session while one is active in the same call.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.session import DatabaseNotConfigured, get_engine
from app.models.identity import IDENTITY_SCHEMAS, identity_metadata

_SQLITE_LOCK = threading.RLock()


def _sqlite_engine() -> Engine:
    eng = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _record):  # pragma: no cover - driver hook
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    eng = eng.execution_options(schema_translate_map={s: None for s in IDENTITY_SCHEMAS})
    identity_metadata.create_all(eng)
    return eng


@lru_cache(maxsize=1)
def get_identity_engine() -> Engine:
    if settings.data_source == "db":
        return get_engine()
    return _sqlite_engine()


def is_sqlite() -> bool:
    return get_identity_engine().dialect.name == "sqlite"


@contextmanager
def identity_session() -> Iterator[Session]:
    """One unit of work; commits on success, rolls back on error. 503 if the store is unavailable."""
    try:
        engine = get_identity_engine()
    except DatabaseNotConfigured as exc:
        raise HTTPException(status_code=503, detail="Identity store is not configured.") from exc
    lock = _SQLITE_LOCK if engine.dialect.name == "sqlite" else nullcontext()
    with lock:
        session = Session(engine, expire_on_commit=False)
        try:
            yield session
            session.commit()
        except HTTPException:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise HTTPException(status_code=503, detail="Identity store is unavailable.") from exc
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()


def reset_identity_store() -> None:
    """Memory mode / tests only: drop and recreate the in-process identity database."""
    engine = get_identity_engine()
    if engine.dialect.name != "sqlite":
        raise RuntimeError("reset_identity_store is only available for the in-memory store")
    with _SQLITE_LOCK:
        identity_metadata.drop_all(engine)
        identity_metadata.create_all(engine)
