"""add workout_sessions table for Strength Forge tracking (#282 Phase B.1)

Revision ID: h8c9d0e1f2a3
Revises: g7b8c9d0e1f2
Create Date: 2026-06-04 20:30:00.000000

One row per completed workout logged on /strength-forge. ``plan_type``
is a short string (band-a / band-b / mil-1 / mil-2 / mil-3);
``session_date`` is the local-date the workout was done. Both indexed
for the "this week" + per-plan summary queries. Single-user app — no FK.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "h8c9d0e1f2a3"
down_revision = "g7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workout_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("plan_type", sa.String(length=20), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_workout_sessions_plan_type", "workout_sessions", ["plan_type"])
    op.create_index("ix_workout_sessions_session_date", "workout_sessions", ["session_date"])


def downgrade() -> None:
    op.drop_index("ix_workout_sessions_session_date", table_name="workout_sessions")
    op.drop_index("ix_workout_sessions_plan_type", table_name="workout_sessions")
    op.drop_table("workout_sessions")
