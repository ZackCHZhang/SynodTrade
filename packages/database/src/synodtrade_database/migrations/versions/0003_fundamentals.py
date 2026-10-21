"""fundamentals snapshots

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import synodtrade_database.column_types

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fundamentals_snapshots",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column(
            "as_of", synodtrade_database.column_types.UtcDateTime(timezone=True), nullable=False
        ),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("period_end", sa.String(length=10), nullable=True),
        sa.Column(
            "data",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            synodtrade_database.column_types.UtcDateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fundamentals_snapshots")),
    )
    with op.batch_alter_table("fundamentals_snapshots", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_fundamentals_snapshots_symbol_as_of"), ["symbol", "as_of"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("fundamentals_snapshots", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_fundamentals_snapshots_symbol_as_of"))

    op.drop_table("fundamentals_snapshots")
