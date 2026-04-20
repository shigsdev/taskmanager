"""Repair: re-apply ALTER TYPE ADD VALUE for next_week + cancelled

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-04-19

Hotfix for migrations e1f2a3b4c5d6 (NEXT_WEEK) and f2a3b4c5d6e7
(CANCELLED). Both originally tried to run::

    ALTER TYPE <enumtype> ADD VALUE IF NOT EXISTS '<value>'

inside alembic's default transactional block. On Postgres, that
particular DDL form **cannot** run inside a transaction (regardless
of `IF NOT EXISTS`), so the statement was silently rolled back even
though alembic still bumped ``alembic_version`` because nothing
re-raised. Result: the enum types in production never gained the
new values, and any query that referenced them (``Task.tier ==
NEXT_WEEK`` or ``Task.status == CANCELLED``) raised an error from
psycopg2 → 500 from /api/tasks?status=cancelled and /api/goals
(via goal_progress).

This migration re-applies both ADD VALUE statements via
``op.get_context().autocommit_block()`` which detaches the
statement from the surrounding transaction. ``IF NOT EXISTS`` keeps
the operation idempotent on environments where the value was
somehow already added (e.g. fresh installs from db.create_all() on
SQLite).

SQLite is unaffected — enums are stored as plain strings, so the
ALTER TYPE is skipped on that dialect entirely.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "a3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # Each ALTER TYPE ADD VALUE must be in its own autocommit block.
    # Postgres does not allow these inside a transaction (raises
    # "ALTER TYPE ... ADD cannot run inside a transaction block").
    # SQLAlchemy stores Python enum NAMES (uppercase), not the
    # lowercase `.value` strings — see app._ensure_postgres_enum_values
    # for the two-part post-mortem.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE tier ADD VALUE IF NOT EXISTS 'NEXT_WEEK'")
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'CANCELLED'")


def downgrade():
    # Cannot remove enum values without recreating the type and
    # migrating every column. No-op (consistent with ADR-010).
    pass
