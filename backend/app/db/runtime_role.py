"""Least-privilege runtime role (`python -m app.db.runtime_role`), idempotent.

Run by the one-off init job as the migration owner (`DATABASE_URL`) after `app.db.init`. Creates or
updates the login role named in `RUNTIME_DATABASE_URL` (the API service's connection string) with
data-only access: USAGE on the application schemas, SELECT/INSERT/UPDATE/DELETE on their tables and
sequences, read-only on `public` (alembic_version). No DDL, no TRUNCATE, no role/database creation.
The append-only triggers still apply because the runtime role does not own any table.
"""

from __future__ import annotations

import os
import re
import sys

from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.models.identity import IDENTITY_SCHEMAS
from app.models.population import POPULATION_SCHEMA
from app.db.session import SCHEMAS

DATA_SCHEMAS = (*SCHEMAS, *IDENTITY_SCHEMAS, POPULATION_SCHEMA)
_ROLE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def runtime_grants(owner: str, role: str, database: str) -> list[sql.Composable]:
    r, o = sql.Identifier(role), sql.Identifier(owner)
    stmts: list[sql.Composable] = [
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), r),
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(r),
        sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(r),
    ]
    for schema in DATA_SCHEMAS:
        s = sql.Identifier(schema)
        stmts += [
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(s, r),
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {} TO {}").format(s, r),
            sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(s, r),
            sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} "
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}").format(o, s, r),
            sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} "
                    "GRANT USAGE, SELECT ON SEQUENCES TO {}").format(o, s, r),
        ]
    return stmts


def ensure_runtime_role(owner_url: str, runtime_url: str) -> str:
    owner, runtime = make_url(owner_url), make_url(runtime_url)
    role, password = runtime.username or "", runtime.password or ""
    if not _ROLE_RE.match(role) or role == owner.username:
        raise SystemExit("RUNTIME_DATABASE_URL must name a dedicated role distinct from the owner.")
    if len(password) < 24:
        raise SystemExit("RUNTIME_DATABASE_URL password is missing or too short.")
    if runtime.database != owner.database:
        raise SystemExit("RUNTIME_DATABASE_URL and DATABASE_URL must use the same database.")
    engine = create_engine(owner_url)
    try:
        with engine.begin() as conn:
            raw = conn.connection.dbapi_connection
            with raw.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
                verb = "ALTER" if cur.fetchone() else "CREATE"
                cur.execute(sql.SQL(
                    "{} ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
                ).format(sql.SQL(verb), sql.Identifier(role), sql.Literal(password)))
                for stmt in runtime_grants(owner.username or "", role, owner.database or ""):
                    cur.execute(stmt)
    finally:
        engine.dispose()
    return f"{'created' if verb == 'CREATE' else 'updated'} role {role} with data-only grants on {', '.join(DATA_SCHEMAS)}"


def main() -> int:
    owner_url, runtime_url = os.environ.get("DATABASE_URL"), os.environ.get("RUNTIME_DATABASE_URL")
    if not owner_url or not runtime_url:
        print("DATABASE_URL and RUNTIME_DATABASE_URL are required.", file=sys.stderr)
        return 2
    print(ensure_runtime_role(owner_url, runtime_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
