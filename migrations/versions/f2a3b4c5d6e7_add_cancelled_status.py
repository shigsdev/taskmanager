"""Add CANCELLED value to taskstatus enum + cancellation_reason column

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-04-19

Backlog #25: adds a "cancelled" status distinct from "archived"
(completed) so the user can mark tasks they consciously dropped
without inflating completion stats. The optional cancellation_reason
column stores the user's free-text "why" — kept separate from `notes`
so cancellation metadata doesn't contaminate the regular notes field.

Idempotent on Postgres via IF NOT EXISTS for the enum value. On
SQLite the ALTER TYPE is skipped (enums are stored as strings) and
the new column is added unconditionally — it's nullable so existing
rows are unaffected.
"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # SQLAlchemy names the enum after the class: "taskstatus".
        op.execute(
            "ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'cancelled'",
        )

    # Add the cancellation_reason column on every dialect. Nullable so
    # the migration is non-blocking on a populated table.
    op.add_column(
        "tasks",
        sa.Column("cancellation_reason", sa.String(length=500), nullable=True),
    )


def downgrade():
    # Drop the column. Reverting the enum value is operationally unsafe
    # on Postgres (would require recreating the type and migrating every
    # column referencing it), so we leave the enum entry in place and
    # only remove the column. This is consistent with ADR-010's stance
    # on enum value removal.
    op.drop_column("tasks", "cancellation_reason")
