"""add reflections.is_draft for resumable multi-sitting reflections (#324)

Revision ID: k1f2a3b4c5d6
Revises: j0e1f2a3b4c5
Create Date: 2026-09-22 14:05:00.000000

A draft is an unsubmitted reflection still being written. Before this,
in-progress text lived only in the browser's textarea — navigating away,
reloading, or iOS evicting the PWA silently destroyed it, and nothing
followed the user between phone and laptop.

``is_draft=True`` rows are excluded from the history list and never carry
proposed_actions (no Whisper/Claude call happens until submit). Server
default false + NOT NULL so every existing row backfills as a real
submitted reflection.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "k1f2a3b4c5d6"
down_revision = "j0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default backfills existing rows; the column stays NOT NULL.
    op.add_column(
        "reflections",
        sa.Column(
            "is_draft",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Partial-ish lookup: "is there an open draft?" runs on every page
    # load of /reflection, so index the flag.
    op.create_index(
        "ix_reflections_is_draft", "reflections", ["is_draft"],
    )


def downgrade() -> None:
    op.drop_index("ix_reflections_is_draft", table_name="reflections")
    op.drop_column("reflections", "is_draft")
