"""add planner_ignore to tasks (weekly-planner ignore flag)

Revision ID: b1c2d3e4f5a6
Revises: aa7eac064a21
Create Date: 2026-05-02

Adds Task.planner_ignore Boolean column. The weekly-planner LLM pass
skips tasks where this is True; the user toggles it from the planner
review modal via "Ignore" per row. Reset to False on any task update
so the flag is "stop suggesting until I touch it again", not permanent.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1c2d3e4f5a6'
down_revision = 'aa7eac064a21'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'planner_ignore',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade():
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_column('planner_ignore')
