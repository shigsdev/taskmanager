"""add start_date to recurring_tasks (#147 — sunrise bound)

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-02

User-reported bug 2026-05-02: created a daily-repeat task with
due_date=5/4 and end_date=5/6, expected the recurring to fire on
Mon/Tue/Wed only, but it fired today (Sat 5/2) too because the
recurring template had no start_date concept — only end_date. This
migration adds the optional sunrise bound so a template can be
configured to start firing on a specific date and ignore everything
before it.

Backwards-compatible: NULL means "fire from beginning of time"
(existing templates keep working unchanged).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('recurring_tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('start_date', sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table('recurring_tasks', schema=None) as batch_op:
        batch_op.drop_column('start_date')
