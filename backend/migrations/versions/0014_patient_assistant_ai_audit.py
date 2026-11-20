"""AI audit feature `patient_assistant` (Phase 9 patient portal assistant).

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-20

Additive only: `synthetic.ai_audit_record.feature` also accepts `patient_assistant`, the portal
assistant that restates one recommendation's portal facts for its own patient. The record stores
the same digests and metadata as the other features (never the text).

Downgrade restores the previous feature list. The audit table is append-only, so it refuses while
`patient_assistant` records exist unless explicitly allowed
(`alembic -x allow_data_loss=true downgrade 0013`), which deletes them.

Frozen static DDL: does not import live ORM metadata (`app/models/synthetic.py` mirrors it).
"""

from __future__ import annotations

from alembic import context, op
from sqlalchemy import text

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_FEATURES_0010 = "'explanation', 'outreach_draft', 'outreach_review', 'population_insight'"
_FEATURES_0014 = f"{_FEATURES_0010}, 'patient_assistant'"
_TABLE = "synthetic.ai_audit_record"


def _set_feature_check(features: str) -> None:
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT ck_ai_audit_record_feature")
    op.execute(f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_ai_audit_record_feature CHECK (feature IN ({features}))")


def upgrade() -> None:
    _set_feature_check(_FEATURES_0014)


def downgrade() -> None:
    bind = op.get_bind()
    if not context.is_offline_mode():
        n = bind.execute(text(f"SELECT count(*) FROM {_TABLE} WHERE feature = 'patient_assistant'")).scalar_one()
        allowed = context.get_x_argument(as_dictionary=True).get("allow_data_loss", "").lower() == "true"
        if n and not allowed:
            raise RuntimeError(
                f"Refusing to downgrade {revision}: it would permanently delete {n} patient assistant AI "
                "audit records. Back up the database first, then rerun with `-x allow_data_loss=true` if "
                "the loss is intended."
            )
        if n:
            op.execute("SET LOCAL pulsereach.allow_synthetic_reset = 'on'")
            op.execute(f"DELETE FROM {_TABLE} WHERE feature = 'patient_assistant'")
            op.execute("SET LOCAL pulsereach.allow_synthetic_reset = 'off'")
    _set_feature_check(_FEATURES_0010)
