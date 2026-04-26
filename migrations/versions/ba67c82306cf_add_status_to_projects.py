"""add status to projects

Revision ID: ba67c82306cf
Revises: 46beab15b77d
Create Date: 2026-04-25 20:16:30.587777

Adds a NOT NULL `status` column (enum: not_started/in_progress/done/on_hold)
to projects, mirroring goals.status. Existing rows get the default value
'NOT_STARTED' via server_default, then the server_default is dropped so
new rows pick up the Python-side default instead.

Per #53: enum value coverage is auto-derived from db.Model.registry, and
healthz `enum_coverage` will fail-loud if the prod ALTER TYPE silently
rolls back. No manual repair list to update.
"""
from alembic import op
import sqlalchemy as sa


revision = 'ba67c82306cf'
down_revision = '46beab15b77d'
branch_labels = None
depends_on = None


def upgrade():
    project_status = sa.Enum(
        'NOT_STARTED', 'IN_PROGRESS', 'DONE', 'ON_HOLD',
        name='projectstatus',
    )
    # On Postgres, batch_alter_table won't auto-create the new enum type
    # for an add_column. Create it explicitly first; on SQLite this is a
    # no-op (enum is just a CHECK constraint synthesized from the column).
    project_status.create(op.get_bind(), checkfirst=True)

    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'status',
                project_status,
                nullable=False,
                server_default='NOT_STARTED',
            )
        )

    # Drop the server_default so new rows use the Python-side default
    # (ProjectStatus.NOT_STARTED) consistently with goals.status.
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.alter_column('status', server_default=None)


def downgrade():
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('status')
    sa.Enum(name='projectstatus').drop(op.get_bind(), checkfirst=True)
