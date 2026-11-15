# Importing the model modules registers their tables on the shared MetaData
# (required by Alembic autogenerate / `alembic check`).
from app.models import official  # noqa: F401
from app.models.base import Base  # noqa: F401
