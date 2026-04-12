"""add parent_id to tasks

Revision ID: b2c3d4e5f6a7
Revises: c8d9e0f1a2b3
Create Date: 2026-04-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tasks', sa.Column('parent_id', sa.Uuid(), nullable=True))
    op.create_index('ix_tasks_parent_id', 'tasks', ['parent_id'])
    op.create_foreign_key('fk_tasks_parent_id', 'tasks', 'tasks', ['parent_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_tasks_parent_id', 'tasks', type_='foreignkey')
    op.drop_index('ix_tasks_parent_id', table_name='tasks')
    op.drop_column('tasks', 'parent_id')
