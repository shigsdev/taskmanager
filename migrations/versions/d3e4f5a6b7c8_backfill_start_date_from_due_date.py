"""backfill recurring_tasks.start_date from linked task.due_date (#147 follow-up)

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-05-02

PR92 added the start_date column but only auto-populated it for
templates created via _apply_repeat going forward — existing templates
created before PR92 still have start_date=NULL and continue firing
forever-from-the-past, including the user's "Finalize Containers
Roadmaps" template from earlier today.

This is a one-shot data backfill: for every active RecurringTask
where start_date IS NULL AND a linked Task has a non-null due_date,
copy that due_date onto rt.start_date. Templates with no linked task
or no task.due_date are left as NULL (preserving the legacy "fire
from beginning of time" behaviour for genuinely intentional cases).

Idempotent: running twice is safe — second run finds no rows where
start_date IS NULL after the first pass.

Both PostgreSQL and SQLite syntax supported via the SA-text path
(parameter binding via :placeholder works on both dialects).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # Pull the (rt_id, due_date) pairs we need to backfill in one query
    # so we can iterate without holding a server-side cursor across
    # alembic's transaction boundaries. Filter at SQL level so we
    # don't need to load every row.
    rows = bind.execute(sa.text(
        """
        SELECT rt.id AS rt_id, t.due_date AS due_date
        FROM recurring_tasks rt
        JOIN tasks t ON t.recurring_task_id = rt.id
        WHERE rt.start_date IS NULL
          AND t.due_date IS NOT NULL
        """
    )).fetchall()
    for row in rows:
        bind.execute(
            sa.text(
                "UPDATE recurring_tasks SET start_date = :due "
                "WHERE id = :rid"
            ),
            {"due": row.due_date, "rid": row.rt_id},
        )


def downgrade():
    # No safe down — we can't tell which rows had start_date NULL
    # before the upgrade vs which ones were explicitly backfilled.
    # The down side of the original column-add migration drops the
    # whole column, which subsumes this.
    pass
