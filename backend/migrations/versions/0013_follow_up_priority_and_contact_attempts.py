"""Follow-up task priority and staff-documented contact attempts (Phase 5 coordination).

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-20

Additive only:

- `engagement.follow_up_task.priority` (`routine` | `high` | `urgent`, default `routine`): the
  operational coordination urgency staff set on a task. It is not a clinical risk score; care-gap
  priority remains with the deterministic evaluation engine.
- `engagement.follow_up_task_event.priority` / `.contact_channel` (nullable) and two new event types:
  `priority_changed` and `contact_attempt` (outcome in `response_code`). A contact attempt documents
  what a staff member did; PulseReach never sends anything.

Downgrade removes the columns and the two event types. Task events are append-only, so it refuses
while such events exist unless explicitly allowed (`alembic -x allow_data_loss=true downgrade 0012`).

Frozen static DDL: does not import live ORM metadata (`app/models/identity.py` mirrors it).
"""

from __future__ import annotations

from alembic import context, op
from sqlalchemy import text

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_EVENT_TYPES_0011 = (
    "'created', 'assigned', 'status_changed', 'due_date_changed', 'staff_note', 'staff_message', "
    "'patient_response', 'assistance_requested', 'appointment_requested', 'escalated', 'completed'"
)
_EVENT_TYPES_0013 = f"{_EVENT_TYPES_0011}, 'priority_changed', 'contact_attempt'"

_UPGRADE = (
    "ALTER TABLE engagement.follow_up_task ADD COLUMN priority VARCHAR(16) NOT NULL DEFAULT 'routine'",
    "ALTER TABLE engagement.follow_up_task ADD CONSTRAINT ck_follow_up_task_priority "
    "CHECK (priority IN ('routine', 'high', 'urgent'))",
    "ALTER TABLE engagement.follow_up_task_event ADD COLUMN priority VARCHAR(16)",
    "ALTER TABLE engagement.follow_up_task_event ADD COLUMN contact_channel VARCHAR(16)",
    "ALTER TABLE engagement.follow_up_task_event DROP CONSTRAINT ck_follow_up_task_event_event_type",
    "ALTER TABLE engagement.follow_up_task_event ADD CONSTRAINT ck_follow_up_task_event_event_type "
    f"CHECK (event_type IN ({_EVENT_TYPES_0013}))",
)

_DOWNGRADE = (
    "SET LOCAL pulsereach.allow_identity_reset = 'on'",
    "DELETE FROM engagement.follow_up_task_event WHERE event_type IN ('priority_changed', 'contact_attempt')",
    "ALTER TABLE engagement.follow_up_task_event DROP CONSTRAINT ck_follow_up_task_event_event_type",
    "ALTER TABLE engagement.follow_up_task_event ADD CONSTRAINT ck_follow_up_task_event_event_type "
    f"CHECK (event_type IN ({_EVENT_TYPES_0011}))",
    "ALTER TABLE engagement.follow_up_task_event DROP COLUMN contact_channel",
    "ALTER TABLE engagement.follow_up_task_event DROP COLUMN priority",
    "ALTER TABLE engagement.follow_up_task DROP CONSTRAINT ck_follow_up_task_priority",
    "ALTER TABLE engagement.follow_up_task DROP COLUMN priority",
    "SET LOCAL pulsereach.allow_identity_reset = 'off'",
)

_DATA_AT_RISK = {
    "contact attempts / priority changes": "SELECT count(*) FROM engagement.follow_up_task_event "
    "WHERE event_type IN ('priority_changed', 'contact_attempt')",
    "non-routine task priorities": "SELECT count(*) FROM engagement.follow_up_task WHERE priority <> 'routine'",
}


def _refuse_destructive_downgrade() -> None:
    if context.is_offline_mode():
        return
    if context.get_x_argument(as_dictionary=True).get("allow_data_loss", "").lower() == "true":
        return
    bind = op.get_bind()
    found = {label: n for label, sql in _DATA_AT_RISK.items() if (n := bind.execute(text(sql)).scalar_one())}
    if found:
        summary = ", ".join(f"{n} {label}" for label, n in found.items())
        raise RuntimeError(
            f"Refusing to downgrade {revision}: it would permanently delete {summary}. Back up the "
            "database first, then rerun with `-x allow_data_loss=true` if the loss is intended."
        )


def upgrade() -> None:
    for stmt in _UPGRADE:
        op.execute(stmt)


def downgrade() -> None:
    _refuse_destructive_downgrade()
    for stmt in _DOWNGRADE:
        op.execute(stmt)
