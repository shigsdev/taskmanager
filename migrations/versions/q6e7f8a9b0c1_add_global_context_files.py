"""add global_context_files (#336)

Reference documents that ride along with EVERY reflection, rather than
being attached to one draft and retiring with it (#328). A run-up to a
fixed date otherwise means re-uploading the same job description and the
same 90-day plan at every sitting.

Its own table rather than a row in ``app_settings`` because that table's
``value`` column is String(500) and one extracted document can be 20,000
characters.

The uploaded file is never stored -- only the text pulled out of it, the
same posture as #328 and /scan (ADR-037).

Revision ID: q6e7f8a9b0c1
Revises: p5d6e7f8a9b0
Create Date: 2026-09-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "q6e7f8a9b0c1"
down_revision = "p5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "global_context_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("chars", sa.Integer(), nullable=False),
        sa.Column("source_chars", sa.Integer(), nullable=True),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("global_context_files")
