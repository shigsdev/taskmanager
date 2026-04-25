"""add target_quarter to projects

Revision ID: ff61c7fdc91c
Revises: c5d6e7f8a9b0
Create Date: 2026-04-25 19:10:02.420336

"""
from alembic import op
import sqlalchemy as sa


revision = 'ff61c7fdc91c'
down_revision = 'c5d6e7f8a9b0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('target_quarter', sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('target_quarter')
