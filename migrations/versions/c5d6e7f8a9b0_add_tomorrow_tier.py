"""Add TOMORROW value to tier enum

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-04-20

Backlog #27: adds a "Tomorrow" tier between Today and This Week.
Auto-rolls into Today at the user's local midnight via an
APScheduler job (see ``app.py`` ``_start_tomorrow_roll_scheduler``).

Follows the ADR-010 / ``_ensure_postgres_enum_values`` precedent —
``ALTER TYPE ... ADD VALUE`` must run outside alembic's transaction
on Postgres, and the value string must be the **UPPERCASE** Python
enum member name (what SQLAlchemy queries with), not the lowercase
``.value`` string.
"""
from alembic import op

revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # autocommit_block is required because ALTER TYPE ADD VALUE
        # cannot run inside a transaction. UPPERCASE member name is
        # required because SQLAlchemy stores Python enum NAMES in PG,
        # not the lowercase `.value` strings. Both learnings from the
        # #23/#25 post-mortem documented in migration a3b4c5d6e7f8.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE tier ADD VALUE IF NOT EXISTS 'TOMORROW'")


def downgrade():
    # Postgres cannot remove enum values without recreating the type
    # and migrating every column. No-op — consistent with ADR-010.
    pass
