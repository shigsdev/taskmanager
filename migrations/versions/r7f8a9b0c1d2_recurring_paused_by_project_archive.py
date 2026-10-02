"""add recurring_tasks.paused_by_project_archive + backfill (#353)

Archiving a project now pauses its currently-active repeating templates
and flags them, so unarchiving can resume exactly those and never a
template the user paused or deleted themselves. Spec:
docs/design/353-project-archive-pauses-templates.md.

The backfill applies the rule retroactively. Every ACTIVE template whose
project is already ARCHIVED is paused and flagged, exactly as if the
cascade had run when that project was archived. On prod this stops the
"Community of Practice" template that was still spawning, with no manual
step. A template that is already inactive is left alone and unflagged:
we can't know who paused it.

``BACKFILL_SQL`` is a module constant so tests/test_project_archive_templates.py
can run the exact string that ships. It uses only true/false literals and
a subquery, which Postgres and SQLite (>= 3.23) both accept.

Downgrade drops the column and deliberately does NOT resume anything: a
rollback shouldn't restart tasks the user has been told are paused.

Revision ID: r7f8a9b0c1d2
Revises: q6e7f8a9b0c1
Create Date: 2026-10-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "r7f8a9b0c1d2"
down_revision = "q6e7f8a9b0c1"
branch_labels = None
depends_on = None

BACKFILL_SQL = (
    "UPDATE recurring_tasks SET is_active = false, "
    "paused_by_project_archive = true "
    "WHERE is_active = true "
    "AND project_id IN (SELECT id FROM projects WHERE is_active = false)"
)


def upgrade() -> None:
    with op.batch_alter_table("recurring_tasks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "paused_by_project_archive",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    op.execute(BACKFILL_SQL)


def downgrade() -> None:
    with op.batch_alter_table("recurring_tasks", schema=None) as batch_op:
        batch_op.drop_column("paused_by_project_archive")
