from sqlalchemy.orm import DeclarativeBase

from app.db.session import metadata


class Base(DeclarativeBase):
    """Declarative base sharing the project MetaData (schemas + naming convention)."""

    metadata = metadata
