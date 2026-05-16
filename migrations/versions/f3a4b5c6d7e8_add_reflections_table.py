"""add reflections table

Revision ID: f3a4b5c6d7e8
Revises: e4f5a6b7c8d9
Create Date: 2026-05-16 10:00:00.000000

Weekly Reflection feature (user-requested 2026-05-16). The user records
or types a weekly reflection; Claude proposes create/update/delete
changes to projects/goals/tasks; the user reviews + confirms. Every
reflection transcript is persisted forever for future reference /
retrospectives. Audio is processed in memory only — never stored.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f3a4b5c6d7e8"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reflections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("iso_week", sa.String(10), nullable=False),
        sa.Column(
            "input_mode",
            sa.Enum("voice", "typed", name="reflectioninputmode"),
            nullable=False,
        ),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("audio_duration_seconds", sa.Float(), nullable=True),
        sa.Column("audio_cost_usd", sa.Float(), nullable=True),
        sa.Column("ai_cost_usd", sa.Float(), nullable=True),
        sa.Column(
            "proposed_actions",
            sa.JSON().with_variant(
                sa.dialects.postgresql.JSONB(), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "applied_actions",
            sa.JSON().with_variant(
                sa.dialects.postgresql.JSONB(), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reflections_iso_week", "reflections", ["iso_week"]
    )


def downgrade() -> None:
    op.drop_index("ix_reflections_iso_week", table_name="reflections")
    op.drop_table("reflections")
    sa.Enum(name="reflectioninputmode").drop(op.get_bind(), checkfirst=True)
