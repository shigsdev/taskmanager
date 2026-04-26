"""rename projects.sort_order to priority_order and add priority enum

Revision ID: 4e060570c44d
Revises: 5160fa3decb9
Create Date: 2026-04-26 08:31:43.953899

#62: rename `sort_order` -> `priority_order` (semantic — drag-drop on
/projects sets this within a type group, lower = higher priority).
Add a new nullable `priority` column with values from a NEW
`projectpriority` enum (must / should / could / need_more_info), mirroring
GoalPriority. Existing rows keep their order, get NULL priority.

Per #53 hardening: enum coverage is auto-derived from db.Model.registry
and healthz `enum_coverage` will fail-loud if Postgres ALTER silently
rolls back. No manual repair list to update.
"""
from alembic import op
import sqlalchemy as sa


revision = '4e060570c44d'
down_revision = '5160fa3decb9'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    project_priority = sa.Enum(
        'MUST', 'SHOULD', 'COULD', 'NEED_MORE_INFO',
        name='projectpriority',
    )
    project_priority.create(bind, checkfirst=True)

    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.alter_column('sort_order', new_column_name='priority_order')
        batch_op.add_column(
            sa.Column('priority', project_priority, nullable=True)
        )


def downgrade():
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('priority')
        batch_op.alter_column('priority_order', new_column_name='sort_order')
    sa.Enum(name='projectpriority').drop(op.get_bind(), checkfirst=True)
