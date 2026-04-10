"""add batch_id + recycle bin columns

Adds:
- tasks.batch_id (nullable UUID, indexed) — links a task to a bulk-import
  operation so it can be undone as a group.
- goals.batch_id (nullable UUID) — same idea for goals imported via Excel.
- import_log.batch_id (nullable UUID, indexed) — uniquely identifies the
  import and matches batch_id on created rows.
- import_log.undone_at (nullable datetime) — NULL means batch is live,
  set means batch is in the recycle bin.

All columns are additive and nullable, so this migration is zero-downtime
on Railway/Postgres (metadata-only change).

Revision ID: b7c9d1e2f3a4
Revises: a1b2c3d4e5f6
Create Date: 2026-04-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b7c9d1e2f3a4'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tasks', sa.Column('batch_id', sa.Uuid(), nullable=True))
    op.create_index('ix_tasks_batch_id', 'tasks', ['batch_id'], unique=False)

    op.add_column('goals', sa.Column('batch_id', sa.Uuid(), nullable=True))

    op.add_column('import_log', sa.Column('batch_id', sa.Uuid(), nullable=True))
    op.create_index(
        'ix_import_log_batch_id', 'import_log', ['batch_id'], unique=False
    )
    op.add_column(
        'import_log',
        sa.Column('undone_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column('import_log', 'undone_at')
    op.drop_index('ix_import_log_batch_id', table_name='import_log')
    op.drop_column('import_log', 'batch_id')

    op.drop_column('goals', 'batch_id')

    op.drop_index('ix_tasks_batch_id', table_name='tasks')
    op.drop_column('tasks', 'batch_id')
