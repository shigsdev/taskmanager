"""add is_archived + is_active to reflections

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-26 16:00:00.000000

User-requested 2026-05-26: "you should have the ability to archive
and delete past reflections." Adds two boolean flags:

  is_archived  — hidden from the default history view but kept in
                 the DB. Toggled back via the Show-archived UI
                 toggle. Default False.
  is_active    — soft-delete flag (mirrors the Project / Goal /
                 RecurringTask pattern in this codebase). Deleted
                 reflections vanish from the default list and the
                 Recently-deleted section becomes their restore
                 path. Default True.

Both columns default-backfill safely — existing rows get
is_archived=False + is_active=True, which matches their pre-feature
visibility (every row continues to render as before).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reflections",
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "reflections",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    # Partial index on the common query: GET /api/reflection (active
    # + not-archived). Predicate-filtered indexes are postgres-only,
    # so we wrap the create in a dialect check.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_reflections_active_unarchived "
            "ON reflections (created_at DESC) "
            "WHERE is_active = true AND is_archived = false"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_reflections_active_unarchived")
    op.drop_column("reflections", "is_active")
    op.drop_column("reflections", "is_archived")
