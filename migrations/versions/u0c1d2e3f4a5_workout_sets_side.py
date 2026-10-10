"""add workout_sets.side (#410)

Per-side Strength Forge exercises (Pallof Press, Dead Bug, hamstring curl,
single-leg moves, …) now log a Left and a Right row per set instead of one
combined number. ``side`` is 'L' / 'R'; NULL means a bilateral move.
Spec: docs/design/410-per-side-logging.md.

No backfill: rows logged before this revision were one combined number per
set and stay side-less — there is no way to split them.

Revision ID: u0c1d2e3f4a5
Revises: t9b0c1d2e3f4
Create Date: 2026-10-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "u0c1d2e3f4a5"
down_revision = "t9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workout_sets") as batch_op:
        batch_op.add_column(sa.Column("side", sa.String(length=1), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workout_sets") as batch_op:
        batch_op.drop_column("side")
