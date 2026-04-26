"""add end_date column to recurring_tasks

Revision ID: d8e7c6b5a4f3
Revises: c6af8dfc8a16
Create Date: 2026-04-26 15:30:00

#101 (PR30, 2026-04-26): nullable end_date column on recurring_tasks
so a template can sunset itself. Spawn cron checks `today > end_date`
and skips. NULL = run forever (current behavior; backwards-compat).
"""
from alembic import op
import sqlalchemy as sa


revision = 'd8e7c6b5a4f3'
down_revision = 'c6af8dfc8a16'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('recurring_tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('end_date', sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table('recurring_tasks', schema=None) as batch_op:
        batch_op.drop_column('end_date')
