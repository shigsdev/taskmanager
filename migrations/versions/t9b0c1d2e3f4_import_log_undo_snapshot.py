"""add import_log.undo_snapshot (#367)

Undo now records what it changes (each task's prior status, and the
goals/projects it archived) so Restore can return every row to exactly
its pre-undo state: a completed task comes back completed, and a project
or goal the user had already archived stays archived. Spec:
docs/design/367-restore-returns-rows-to-pre-undo-state.md.

No backfill: the prod recycle bin was empty when this was written
(2026-10-02), and a batch undone before this revision keeps a NULL
snapshot, which Restore handles with the old behavior.

Revision ID: t9b0c1d2e3f4
Revises: s8a9b0c1d2e3
Create Date: 2026-10-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "t9b0c1d2e3f4"
down_revision = "s8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("import_log") as batch_op:
        batch_op.add_column(
            sa.Column(
                "undo_snapshot",
                sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("import_log") as batch_op:
        batch_op.drop_column("undo_snapshot")
