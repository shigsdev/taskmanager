"""add ON DELETE SET NULL to 4 cross-entity link FKs (#175)

Revision ID: d4f5a6b7c8e9
Revises: f3a4b5c6d7e8
Create Date: 2026-05-21 12:00:00.000000

#175 (2026-05-20 audit): recycle_service.purge_batch nulled
Task.project_id / Task.goal_id by hand before deleting a purged row,
but four OTHER FKs pointing at purgeable rows had no such handling and
no DB-level ON DELETE rule. With Postgres' default NO ACTION, purging
a goal/project/parent-task that was still referenced raised a bare
ForeignKeyViolation -> the global error handler returned an opaque
"Database error: violates foreign key constraint" 422.

This migration drops + recreates those four FKs with
ON DELETE SET NULL (mirroring WeeklyFocus.goal_id, which was born with
it). The matching `ondelete="SET NULL"` is also set on the model
columns, so the SQLite test DB — built from the model metadata via
`db.create_all()` — picks it up directly; this migration is the
Postgres-side equivalent.

  projects.goal_id              -> goals.id        ON DELETE SET NULL
  recurring_tasks.project_id    -> projects.id     ON DELETE SET NULL
  recurring_tasks.goal_id       -> goals.id        ON DELETE SET NULL
  tasks.parent_id               -> tasks.id        ON DELETE SET NULL

SQLite is a no-op: tests build from the models (ondelete already
present), SQLite does not enforce FKs unless PRAGMA foreign_keys is on,
and batch FK-rewrites on SQLite are fragile. The bug this fixes is a
Postgres-only bug.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d4f5a6b7c8e9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


# (table, column, referenced_table) — the 4 FKs from #175.
_FKS = [
    ("projects", "goal_id", "goals"),
    ("recurring_tasks", "project_id", "projects"),
    ("recurring_tasks", "goal_id", "goals"),
    ("tasks", "parent_id", "tasks"),
]


def _existing_fk_name(bind, table: str, column: str) -> str | None:
    """Return the live constraint name of the FK on ``table.column``,
    regardless of how it was originally named (auto-named on
    table-create vs. an explicit ``fk_*`` name). ``None`` if absent."""
    inspector = sa.inspect(bind)
    for fk in inspector.get_foreign_keys(table):
        if fk.get("constrained_columns") == [column]:
            return fk.get("name")
    return None


def _rebuild_fks(*, ondelete: str | None) -> None:
    """Drop + recreate each link FK with the given ON DELETE rule."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite / others: no-op. The model metadata carries the
        # ondelete rule, so create_all-built DBs already have it; and
        # SQLite doesn't enforce FKs by default anyway.
        return
    for table, column, ref_table in _FKS:
        old_name = _existing_fk_name(bind, table, column)
        if old_name:
            op.drop_constraint(old_name, table, type_="foreignkey")
        op.create_foreign_key(
            f"fk_{table}_{column}",
            table,
            ref_table,
            [column],
            ["id"],
            ondelete=ondelete,
        )


def upgrade() -> None:
    _rebuild_fks(ondelete="SET NULL")


def downgrade() -> None:
    # Restore NO ACTION (Postgres default) — recreate the FKs without
    # an explicit ON DELETE rule.
    _rebuild_fks(ondelete=None)
