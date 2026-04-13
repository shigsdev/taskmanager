"""add repeat support to recurring tasks and link to tasks

Revision ID: d9e0f1a2b3c4
Revises: b2c3d4e5f6a7
Create Date: 2026-04-13 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd9e0f1a2b3c4'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    # Add new enum values to recurringfrequency
    # Works on both PostgreSQL (ALTER TYPE) and SQLite (no-op, enums are strings)
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute("ALTER TYPE recurringfrequency ADD VALUE IF NOT EXISTS 'weekdays'")
        op.execute("ALTER TYPE recurringfrequency ADD VALUE IF NOT EXISTS 'monthly_date'")
        op.execute("ALTER TYPE recurringfrequency ADD VALUE IF NOT EXISTS 'monthly_nth_weekday'")

    # Add new columns to recurring_tasks
    op.add_column('recurring_tasks', sa.Column('day_of_month', sa.Integer(), nullable=True))
    op.add_column('recurring_tasks', sa.Column('week_of_month', sa.Integer(), nullable=True))
    op.add_column('recurring_tasks', sa.Column('goal_id', sa.Uuid(), nullable=True))
    op.add_column('recurring_tasks', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('recurring_tasks', sa.Column('checklist', sa.JSON(), nullable=True))
    op.add_column('recurring_tasks', sa.Column('url', sa.String(length=2000), nullable=True))
    with op.batch_alter_table('recurring_tasks') as batch_op:
        batch_op.create_foreign_key(
            'fk_recurring_tasks_goal_id', 'goals',
            ['goal_id'], ['id']
        )

    # Add recurring_task_id FK to tasks
    op.add_column('tasks', sa.Column('recurring_task_id', sa.Uuid(), nullable=True))
    op.create_index('ix_tasks_recurring_task_id', 'tasks', ['recurring_task_id'])
    with op.batch_alter_table('tasks') as batch_op:
        batch_op.create_foreign_key(
            'fk_tasks_recurring_task_id', 'recurring_tasks',
            ['recurring_task_id'], ['id']
        )


def downgrade():
    with op.batch_alter_table('tasks') as batch_op:
        batch_op.drop_constraint('fk_tasks_recurring_task_id', type_='foreignkey')
    op.drop_index('ix_tasks_recurring_task_id', table_name='tasks')
    op.drop_column('tasks', 'recurring_task_id')

    with op.batch_alter_table('recurring_tasks') as batch_op:
        batch_op.drop_constraint('fk_recurring_tasks_goal_id', type_='foreignkey')
    op.drop_column('recurring_tasks', 'url')
    op.drop_column('recurring_tasks', 'checklist')
    op.drop_column('recurring_tasks', 'notes')
    op.drop_column('recurring_tasks', 'goal_id')
    op.drop_column('recurring_tasks', 'week_of_month')
    op.drop_column('recurring_tasks', 'day_of_month')
