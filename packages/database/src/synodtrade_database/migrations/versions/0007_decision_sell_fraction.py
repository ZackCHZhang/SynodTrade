"""decisions / aggregated_decisions: sell_fraction

A decision may choose how much of a position a sell sells; NULL keeps the fixed sell tiers.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-04 16:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import synodtrade_database.column_types

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("decisions", "aggregated_decisions")


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "sell_fraction",
                    synodtrade_database.column_types.DecimalType(precision=28, scale=10),
                    nullable=True,
                )
            )


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column("sell_fraction")
