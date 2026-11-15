from alembic import context

import app.models  # noqa: F401  (registers the tables on the shared MetaData)
from app.core.config import settings
from app.db.session import SCHEMAS, DatabaseNotConfigured, build_engine, metadata

config = context.config
target_metadata = metadata

# One revision history for all three schemas. The version table lives in `public`,
# outside the three application schemas (design D7).
VERSION_TABLE_SCHEMA = "public"


def include_object(obj, name, type_, reflected, compare_to):
    # Autogenerate only sees official / clinical / synthetic.
    if type_ == "table":
        return obj.schema in SCHEMAS
    return True


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in SCHEMAS
    return True


_opts = dict(
    target_metadata=target_metadata,
    include_schemas=True,
    include_object=include_object,
    include_name=include_name,
    version_table_schema=VERSION_TABLE_SCHEMA,
)


def run_migrations_offline() -> None:
    if settings.database_url is None:
        raise DatabaseNotConfigured("DATABASE_URL is not set")
    context.configure(
        url=settings.database_url.get_secret_value(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_opts,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = build_engine(settings)
    with engine.connect() as connection:
        context.configure(connection=connection, **_opts)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
