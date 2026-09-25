"""add reflections.continued_from_id (#334)

Continuing a past reflection FORKS: a new draft is seeded from the saved
sitting's text, voice segments and attachments, and this column points
back at the original -- which is never touched. The alternative (re-open
and append to the saved row) would have quietly rewritten the record of
what the user thought on a given day, breaking the "every reflection is
kept forever" promise made on the /reflection page and in the Help page.

Nullable with no server default, so every existing row reads as "not a
continuation" rather than acquiring a misleading lineage.

The self-referential FK is created only on backends that can ALTER TABLE
ADD CONSTRAINT. SQLite cannot, and `batch_alter_table` would have to
recreate a table carrying Enum CHECK constraints and JSON columns to get
it -- far more risk than the constraint is worth on a local dev file.
Tests and prod both get the real constraint (tests via `create_all()`
from the model, prod via this branch); only a migrated `instance/dev.db`
goes without it.

Revision ID: n4c5d6e7f8a9
Revises: m3b4c5d6e7f8
Create Date: 2026-09-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "n4c5d6e7f8a9"
down_revision = "m3b4c5d6e7f8"
branch_labels = None
depends_on = None

_FK_NAME = "fk_reflections_continued_from_id"


def upgrade() -> None:
    op.add_column(
        "reflections",
        sa.Column("continued_from_id", sa.Uuid(), nullable=True),
    )
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            _FK_NAME,
            "reflections",
            "reflections",
            ["continued_from_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint(_FK_NAME, "reflections", type_="foreignkey")
    op.drop_column("reflections", "continued_from_id")
