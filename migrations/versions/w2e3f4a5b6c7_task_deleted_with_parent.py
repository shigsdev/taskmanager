"""add tasks.deleted_with_parent (#433)

Deleting a parent task now takes its open subtasks to the Recycle Bin with
it, and restoring the parent brings them back. ``deleted_with_parent``
marks the subtasks that went along, so Restore returns exactly those and
not a subtask that was deleted on its own.
Spec: docs/design/433-subtasks-close-with-parent.md.

No backfill: no existing deleted row can be told apart, so they all stay
false and remain individually restorable, as before.

Revision ID: w2e3f4a5b6c7
Revises: v1d2e3f4a5b6
Create Date: 2026-10-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "w2e3f4a5b6c7"
down_revision = "v1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(
            sa.Column(
                "deleted_with_parent",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_column("deleted_with_parent")
