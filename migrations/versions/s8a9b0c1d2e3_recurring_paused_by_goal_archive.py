"""add recurring_tasks.paused_by_goal_archive + backfill (#368)

Archiving a goal now pauses its currently-active repeating templates and
marks them, exactly as #353 did for projects. A template can sit on an
archived project AND an archived goal, so each parent gets its own
marker and a template restarts only when neither is left. Spec:
docs/design/368-goal-archive-pauses-templates.md.

The backfill applies the rule retroactively, in two statements:

1. Every ACTIVE template whose goal is already ARCHIVED is paused and
   marked, as if the cascade had run when that goal was archived.
2. Every template already paused by its project's archive whose goal is
   archived gains the goal marker too, so unarchiving the project alone
   can't wake it.

A template that is already inactive with no marker is left alone: we
can't know who paused it. Expected prod effect at the time of writing:
0 rows (read-only check 2026-10-02 found no template on an archived goal).

``BACKFILL_SQL`` is a module constant so tests/test_goal_archive_templates.py
runs the exact SQL that ships. Only true/false literals and a subquery,
which Postgres and SQLite (>= 3.23) both accept.

Downgrade drops the column and deliberately resumes nothing: a rollback
shouldn't restart tasks the user has been told are paused.

Revision ID: s8a9b0c1d2e3
Revises: r7f8a9b0c1d2
Create Date: 2026-10-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "s8a9b0c1d2e3"
down_revision = "r7f8a9b0c1d2"
branch_labels = None
depends_on = None

BACKFILL_SQL = (
    "UPDATE recurring_tasks SET is_active = false, "
    "paused_by_goal_archive = true "
    "WHERE is_active = true "
    "AND goal_id IN (SELECT id FROM goals WHERE is_active = false)",
    "UPDATE recurring_tasks SET paused_by_goal_archive = true "
    "WHERE paused_by_project_archive = true "
    "AND goal_id IN (SELECT id FROM goals WHERE is_active = false)",
)


def upgrade() -> None:
    with op.batch_alter_table("recurring_tasks") as batch_op:
        batch_op.add_column(
            sa.Column(
                "paused_by_goal_archive",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    for stmt in BACKFILL_SQL:
        op.execute(stmt)


def downgrade() -> None:
    with op.batch_alter_table("recurring_tasks") as batch_op:
        batch_op.drop_column("paused_by_goal_archive")
