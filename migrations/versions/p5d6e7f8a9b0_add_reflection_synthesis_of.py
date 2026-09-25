"""add reflections.synthesis_of (#335)

The ids a COMBINED analysis was run over. NULL for an ordinary
reflection, so every existing row reads as "not a synthesis" rather than
acquiring a misleading empty list.

A JSON list rather than a second foreign key: unlike #334's
``continued_from_id`` (one parent, whose words flow into the row) this
records that the user read N sittings together on some day. No text
flows, and there is no single parent.

Revision ID: p5d6e7f8a9b0
Revises: n4c5d6e7f8a9
Create Date: 2026-09-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "p5d6e7f8a9b0"
down_revision = "n4c5d6e7f8a9"
branch_labels = None
depends_on = None

# Mirrors models.JSONType: JSONB on PostgreSQL (indexable), plain JSON
# elsewhere. Spelled out here rather than imported so the migration stays
# valid if the model later changes.
_JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "reflections",
        sa.Column("synthesis_of", _JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reflections", "synthesis_of")
