"""FastAPI database session dependencies (`app.db.deps`)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import DatabaseNotConfigured, get_engine


def get_db_session() -> Iterator[Session]:
    """Yield a SQLAlchemy Session; raise 503 if DB is unconfigured or unreachable."""
    try:
        engine = get_engine()
        with Session(engine) as session:
            session.execute(text("SELECT 1"))
            yield session
    except DatabaseNotConfigured as exc:
        raise HTTPException(
            status_code=503,
            detail="Database is required for DATA_SOURCE=db but DATABASE_URL is not configured.",
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database is required for DATA_SOURCE=db but PostgreSQL is unreachable.",
        ) from exc
