"""add recurring_tasks.deleted_at (#363)

Delete and Pause both wrote ``is_active=False``, so a paused template and
a deleted one were the same row. ``/recurring`` could not show paused
templates without bringing back every deleted one too. ``deleted_at`` now
marks a delete; paused = inactive with ``deleted_at`` NULL.
Spec: docs/design/363-paused-templates-visible.md.

No backfill, by user decision (2026-10-11): the existing inactive rows
can't be told apart, so they all stay NULL and read as Paused, and the
user deletes the ones they don't want.

Revision ID: v1d2e3f4a5b6
Revises: u0c1d2e3f4a5
Create Date: 2026-10-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v1d2e3f4a5b6"
down_revision = "u0c1d2e3f4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("recurring_tasks") as batch_op:
        batch_op.add_column(
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("recurring_tasks") as batch_op:
        batch_op.drop_column("deleted_at")
