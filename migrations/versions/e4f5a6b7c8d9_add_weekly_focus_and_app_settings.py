"""add weekly_focus + app_settings tables

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-05-09 14:00:00.000000

Feature 1 (user-requested 2026-05-08): "This Week's Focus" panel on the
main board. Three (configurable) free-form focus statements per ISO
week, each optionally linked to a Goal. ``weekly_focus`` rows are kept
forever — silent history snapshot when the user edits, so retrospectives
can scroll back. No auto-roll: the panel carries last week's text
forward until the user edits.

Also adds ``app_settings`` — a tiny generic key/value table for
single-user runtime configuration. Created here so the focus-panel slot
count (default 3, range 1-7) has somewhere to live without abusing env
vars (which can't change without a redeploy). Future settings can reuse
the table.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weekly_focus",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("week_start_date", sa.Date(), nullable=False),
        sa.Column("slot_order", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
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
        sa.ForeignKeyConstraint(
            ["goal_id"], ["goals.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_weekly_focus_week_start_date",
        "weekly_focus",
        ["week_start_date"],
    )

    op.create_table(
        "app_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index(
        "ix_app_settings_key", "app_settings", ["key"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_app_settings_key", table_name="app_settings")
    op.drop_table("app_settings")
    op.drop_index("ix_weekly_focus_week_start_date", table_name="weekly_focus")
    op.drop_table("weekly_focus")
