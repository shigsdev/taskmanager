"""add cron_audit table for scheduler self-heal (#167)

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-28 21:00:00.000000

Backs the scheduler self-heal path: each of the four nightly
midnight cron jobs (``tomorrow_roll``, ``promote_due_today``,
``realign_tiers_with_due_dates``, ``recurring_spawn``) gets a single
audit row tracking when it last fired. On container boot after an
outage, the replay loop reads this table — any job whose last fire
predates today's scheduled fire (and where now() is past that fire)
gets run inline so the operator never has to remember
``scripts/run_missed_crons.py`` after Railway recovery.

Schema deliberately mirrors the ``Manual cron run report`` output
from ``scripts/run_missed_crons.py`` (job_id, last_fire_at,
last_status, last_rowcount, last_elapsed_ms) so both paths log the
same shape.

Single-row-per-job. ``job_id`` is the PK — well-known string from
``cron_jobs.JOB_ORDER`` so it's stable across deploys.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "g7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cron_audit",
        sa.Column("job_id", sa.String(length=100), primary_key=True, nullable=False),
        sa.Column(
            "last_fire_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_status", sa.String(length=20), nullable=False),
        sa.Column("last_rowcount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "last_elapsed_ms",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_table("cron_audit")
