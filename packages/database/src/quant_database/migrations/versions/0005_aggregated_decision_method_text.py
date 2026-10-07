"""aggregated_decisions.method: varchar(32) -> text

The aggregation method string includes its options (e.g. "weighted_vote(min_confidence=0.6)"),
which does not fit in 32 characters. SQLite never enforced the length; PostgreSQL rejects it.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07 19:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("aggregated_decisions", schema=None) as batch_op:
        batch_op.alter_column(
            "method",
            existing_type=sa.String(length=32),
            type_=sa.Text(),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("aggregated_decisions", schema=None) as batch_op:
        batch_op.alter_column(
            "method",
            existing_type=sa.Text(),
            type_=sa.String(length=32),
            existing_nullable=False,
        )
