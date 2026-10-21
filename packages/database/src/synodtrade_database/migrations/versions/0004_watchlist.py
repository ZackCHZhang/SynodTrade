"""watchlist

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-05 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import synodtrade_database.column_types

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UTC_DT = synodtrade_database.column_types.UtcDateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "watchlist_entries",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("pipeline_name", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("added_at", UTC_DT, nullable=False),
        sa.Column("last_selected_at", UTC_DT, nullable=True),
        sa.Column("times_selected", sa.Integer(), nullable=False),
        sa.Column("last_score", sa.Float(), nullable=True),
        sa.Column("last_reason", sa.Text(), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("removed_at", UTC_DT, nullable=True),
        sa.Column("removed_reason", sa.Text(), nullable=True),
        sa.Column("updated_at", UTC_DT, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watchlist_entries")),
        sa.UniqueConstraint(
            "pipeline_name", "symbol", name=op.f("uq_watchlist_entries_pipeline_name_symbol")
        ),
    )
    with op.batch_alter_table("stock_selections", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "watchlist",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
                nullable=False,
                server_default="[]",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("stock_selections", schema=None) as batch_op:
        batch_op.drop_column("watchlist")
    op.drop_table("watchlist_entries")
