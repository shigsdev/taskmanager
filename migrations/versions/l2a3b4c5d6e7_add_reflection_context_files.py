"""add reflections.context_files for attached context documents (#328)

Revision ID: l2a3b4c5d6e7
Revises: k1f2a3b4c5d6
Create Date: 2026-09-23 10:00:00.000000

A reflection can now carry reference documents — a job description, a
30/60/90 plan, a photo of a whiteboard — so the analysis has more than
the user's words and a state snapshot to reason from.

The column stores the EXTRACTED TEXT of each attachment, never the file.
Uploads are decoded in memory and the bytes are dropped when the request
ends; nothing is written to server disk or to this database. Persisting
the text (rather than re-reading a file that no longer exists) is what
lets a retrospective months later still show what the week was reasoned
against, and lets a failed analysis be retried without re-uploading.

Server default '[]' + NOT NULL so every existing row backfills as a
reflection with no attachments.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "l2a3b4c5d6e7"
down_revision = "k1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Mirror models.JSONType: JSONB on Postgres (indexable, compact),
    # plain JSON everywhere else (SQLite in dev/tests).
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.add_column(
        "reflections",
        sa.Column(
            "context_files",
            json_type,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("reflections", "context_files")
