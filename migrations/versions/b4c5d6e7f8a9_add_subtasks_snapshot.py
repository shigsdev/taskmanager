"""Add subtasks_snapshot column to recurring_tasks

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-04-20

Backlog #26: when a recurring template spawns its next instance,
also clone the subtasks the user attached to the parent at template
creation time. The snapshot is stored as a JSON list on the
RecurringTask row so spawn doesn't have to look up the previous
cycle's archived parent (which may have been hand-edited or
deleted).

Nullable + default=[] so the migration is non-blocking on a
populated table; existing recurring rows simply get an empty list
which means "no subtasks to clone" — same behaviour as before.
"""
import sqlalchemy as sa
from alembic import op

revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "recurring_tasks",
        sa.Column("subtasks_snapshot", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_column("recurring_tasks", "subtasks_snapshot")
