"""add raw_segments to reflections

Revision ID: e5f6a7b8c9d0
Revises: d4f5a6b7c8e9
Create Date: 2026-05-26 13:00:00.000000

#237 (user-requested 2026-05-25): persist the raw per-segment Whisper
transcripts alongside the final edited reflection text. The #232
pause/resume flow lets the user edit the textarea between voice
segments — without this column, an edit overwrites the raw Whisper
output and the original phrasing is lost. New JSONB column stores
a list of `{text, duration_seconds, cost_usd, recorded_at}` per
segment so the user can recover their original spoken words.

Default = empty list (backfill-safe — every existing reflection row
gets `[]`). Typed reflections also get `[]` since there are no voice
segments.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d0"
down_revision = "d4f5a6b7c8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOT NULL with server_default=[] so existing rows backfill safely.
    # JSONB on Postgres / JSON on SQLite for test parity.
    op.add_column(
        "reflections",
        sa.Column(
            "raw_segments",
            sa.JSON().with_variant(
                sa.dialects.postgresql.JSONB(), "postgresql"
            ),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("reflections", "raw_segments")
