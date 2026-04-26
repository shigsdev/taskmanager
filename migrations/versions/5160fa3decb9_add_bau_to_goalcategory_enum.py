"""add bau to goalcategory enum

Revision ID: 5160fa3decb9
Revises: ba67c82306cf
Create Date: 2026-04-25 21:48:26.008860

Adds the BAU value to the GoalCategory enum.

Postgres: ALTER TYPE goalcategory ADD VALUE IF NOT EXISTS 'BAU'.
SQLite: no-op (enum is just a CHECK constraint that re-derives from
SQLAlchemy column type at table creation; the StrEnum addition is
picked up automatically).

Per #53 hardening: even if this migration's ALTER TYPE silently
rolls back on prod (the historical bug class), the auto-derive in
``_build_enum_repair_statements`` runs at app startup and the
``enum_coverage`` healthz check will fail-loud if the value is
missing from pg_enum. Both lines of defence cover this change.
"""
from alembic import op


revision = '5160fa3decb9'
down_revision = 'ba67c82306cf'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE goalcategory ADD VALUE IF NOT EXISTS 'BAU'")


def downgrade():
    # Postgres has no native ALTER TYPE ... DROP VALUE. Rolling back is
    # destructive — would require recreating the type, casting all rows,
    # and dropping any rows still using the value. Not auto-reversed.
    pass
