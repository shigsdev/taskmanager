"""Add NEXT_WEEK value to tier enum

Revision ID: e1f2a3b4c5d6
Revises: d9e0f1a2b3c4
Create Date: 2026-04-19

Backlog #23: adds a "Next Week" tier between This Week and Backlog
for forward-looking task planning. Pairs with day-of-week grouping
on the This Week / Next Week views (pure frontend change).

Migration is idempotent on Postgres via IF NOT EXISTS. On SQLite
(used by the test suite), enums are stored as plain strings so the
ALTER TYPE is skipped entirely — schema re-creation via
``db.create_all()`` picks up the new enum member automatically.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "e1f2a3b4c5d6"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # ALTER TYPE ... ADD VALUE cannot run inside a transaction block
        # on Postgres (any version), so we use alembic's autocommit_block
        # to detach it from the migration transaction. ADD VALUE
        # IF NOT EXISTS makes the migration idempotent on re-run.
        # See migration a3b4c5d6e7f8 for the post-mortem of the original
        # version of this migration which silently dropped the ALTER.
        with op.get_context().autocommit_block():
            op.execute(
                # SQLAlchemy stores Python enum NAMES (uppercase) in PG,
                # not the .value strings. Adding lowercase 'next_week'
                # would be a no-op as far as the ORM is concerned.
                "ALTER TYPE tier ADD VALUE IF NOT EXISTS 'NEXT_WEEK'",
            )


def downgrade():
    # Postgres doesn't support DROP VALUE from an enum cleanly (you'd
    # have to create a new type, migrate every column, and drop the
    # old one). For a single-user personal app, reverting this means
    # any row with tier='next_week' must first be migrated off —
    # that's a manual operational step if it's ever needed.
    # Leaving this as no-op to prevent accidental schema drift.
    pass
