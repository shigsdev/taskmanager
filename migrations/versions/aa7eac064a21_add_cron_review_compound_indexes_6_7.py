"""add cron + review compound indexes (#6 + #7)

Revision ID: aa7eac064a21
Revises: fe97b028f4d0
Create Date: 2026-04-30 15:12:54.904169

PR68 perf #6 + #7. Two compound indexes for hot query paths:

- ``ix_tasks_due_date_status`` covers the cron paths
  (promote_due_today, realign_tiers, compute_previews_in_range
  collision check) — they all filter ``WHERE due_date = X AND status =
  'ACTIVE'``. Pre-empts the long-tail seq-scan as the task table grows.

- ``ix_tasks_status_last_reviewed`` covers ``review_service.stale_tasks``
  — ``WHERE status = 'ACTIVE' AND (last_reviewed IS NULL OR last_reviewed
  <= cutoff)``. The OR-with-NULL defeats the plain status index for
  partial-index optimization; this compound covers both branches.

Autogen produced false-positive enum/varchar alter_columns and a
pile of indexes that already exist in prod (artifacts of running
autogen against local SQLite). Pruned to JUST the new index pair.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'aa7eac064a21'
down_revision = 'fe97b028f4d0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.create_index(
            'ix_tasks_due_date_status', ['due_date', 'status'], unique=False
        )
        batch_op.create_index(
            'ix_tasks_status_last_reviewed', ['status', 'last_reviewed'],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_index('ix_tasks_status_last_reviewed')
        batch_op.drop_index('ix_tasks_due_date_status')
