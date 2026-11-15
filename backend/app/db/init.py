"""Initialise the database by applying Alembic migrations (`python -m app.db.init`).

Tables and schemas are created only by migrations, never directly from here.
"""
from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[2]


def init_db(revision: str = "head") -> None:
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), revision)


if __name__ == "__main__":
    init_db()
