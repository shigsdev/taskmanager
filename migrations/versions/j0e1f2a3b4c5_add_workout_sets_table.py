"""add workout_sets table for per-set Strength Forge logging (#287)

Revision ID: j0e1f2a3b4c5
Revises: i9d0e1f2a3b4
Create Date: 2026-06-07 13:30:00.000000

One row per logged set within a workout session (reps + resistance), so
progressive overload is trackable. FK to workout_sessions with ON DELETE
CASCADE — deleting a session removes its sets. ``exercise_name`` is a
snapshot taken at log time. Single-user app — no per-user FK.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "j0e1f2a3b4c5"
down_revision = "i9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workout_sets",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workout_session_id",
            sa.Uuid(),
            sa.ForeignKey("workout_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("exercise_id", sa.String(length=50), nullable=False),
        sa.Column("exercise_name", sa.String(length=120), nullable=False),
        sa.Column("set_number", sa.Integer(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=True),
        sa.Column("resistance", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_workout_sets_workout_session_id",
        "workout_sets",
        ["workout_session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workout_sets_workout_session_id", table_name="workout_sets"
    )
    op.drop_table("workout_sets")
