"""add multi_day_of_week recurring frequency + days_of_week column

Revision ID: c6af8dfc8a16
Revises: 4e060570c44d
Create Date: 2026-04-26 09:58:39.488731

#75 (2026-04-26): adds:
  - New `multi_day_of_week` value to the `recurringfrequency` Postgres
    enum. Per #53 hardening, _build_enum_repair_statements auto-derives
    from db.Model.registry — this ALTER is the explicit migration path.
  - New `days_of_week` JSON column on recurring_tasks (list of ints 0-6).
    NULL for all existing templates and any non-MULTI_DAY_OF_WEEK row.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c6af8dfc8a16'
down_revision = '4e060570c44d'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TYPE recurringfrequency ADD VALUE IF NOT EXISTS 'MULTI_DAY_OF_WEEK'"
        )
    with op.batch_alter_table('recurring_tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('days_of_week', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('recurring_tasks', schema=None) as batch_op:
        batch_op.drop_column('days_of_week')
    # Postgres has no ALTER TYPE ... DROP VALUE; not auto-reversed.
