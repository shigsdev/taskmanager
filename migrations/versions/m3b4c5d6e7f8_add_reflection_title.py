"""add reflections.title (#339)

A user-supplied name for a reflection sitting. NULL means "unnamed" and
the UI falls back to a generated label; the column is deliberately
nullable with no server default so existing rows stay unnamed rather
than acquiring a misleading auto-name at migration time.

Revision ID: m3b4c5d6e7f8
Revises: l2a3b4c5d6e7
Create Date: 2026-09-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m3b4c5d6e7f8"
down_revision = "l2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reflections",
        sa.Column("title", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reflections", "title")
