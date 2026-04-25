"""add actions and notes to projects

Revision ID: 46beab15b77d
Revises: ff61c7fdc91c
Create Date: 2026-04-25 19:31:38.484883

"""
from alembic import op
import sqlalchemy as sa


revision = '46beab15b77d'
down_revision = 'ff61c7fdc91c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('actions', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('notes', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('notes')
        batch_op.drop_column('actions')
