"""add app_logs table

Adds the ``app_logs`` table backing the persistent application logging
feature. Populated by the ``DBLogHandler`` in ``logging_service`` — one
row per warning+ log event plus one summary row per HTTP request.

The table is additive and has no foreign keys, so this migration is
zero-downtime on Railway/Postgres.

Revision ID: c8d9e0f1a2b3
Revises: b7c9d1e2f3a4
Create Date: 2026-04-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c8d9e0f1a2b3'
down_revision = 'b7c9d1e2f3a4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'app_logs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column(
            'timestamp', sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column('level', sa.String(length=20), nullable=False),
        sa.Column('logger_name', sa.String(length=200), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('traceback', sa.Text(), nullable=True),
        sa.Column('request_id', sa.String(length=36), nullable=True),
        sa.Column('route', sa.String(length=200), nullable=True),
        sa.Column('method', sa.String(length=10), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_app_logs_timestamp', 'app_logs', ['timestamp'], unique=False
    )
    op.create_index(
        'ix_app_logs_level', 'app_logs', ['level'], unique=False
    )


def downgrade():
    op.drop_index('ix_app_logs_level', table_name='app_logs')
    op.drop_index('ix_app_logs_timestamp', table_name='app_logs')
    op.drop_table('app_logs')
