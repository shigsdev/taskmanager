"""add flare_states table for Strength Forge flare tracking (#282 Phase B.2)

Revision ID: i9d0e1f2a3b4
Revises: h8c9d0e1f2a3
Create Date: 2026-06-07 01:20:00.000000

One row per tracked back-flare episode started on /strength-forge.
``phase`` is the clinical protocol stage (immediate / recovery / return);
``started_on`` is the local-date the flare began (drives the "Day N"
counter); ``ended_on`` is NULL while active. Both dates indexed for the
active-flare lookup. The service layer enforces at most one active flare.
Single-user app — no FK.
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "i9d0e1f2a3b4"
down_revision = "h8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flare_states",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("started_on", sa.Date(), nullable=False),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_flare_states_started_on", "flare_states", ["started_on"])
    op.create_index("ix_flare_states_ended_on", "flare_states", ["ended_on"])


def downgrade() -> None:
    op.drop_index("ix_flare_states_ended_on", table_name="flare_states")
    op.drop_index("ix_flare_states_started_on", table_name="flare_states")
    op.drop_table("flare_states")
