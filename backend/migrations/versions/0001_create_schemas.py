"""Create the official, clinical and synthetic schemas.

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Order matters: official -> clinical -> synthetic (design §2.1).
SCHEMAS = ("official", "clinical", "synthetic")


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")


def downgrade() -> None:
    # Non-CASCADE on purpose: refuses to drop a schema that still holds tables.
    for schema in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {schema}")
