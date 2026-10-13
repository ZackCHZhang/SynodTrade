"""account sync history

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-12 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import quant_database.column_types

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UTC_DT = quant_database.column_types.UtcDateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "account_syncs",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("pipeline_name", sa.String(length=64), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", UTC_DT, nullable=False),
        sa.Column("finished_at", UTC_DT, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("orders_checked", sa.Integer(), nullable=False),
        sa.Column("orders_updated", sa.Integer(), nullable=False),
        sa.Column("fills_added", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "report",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_syncs")),
    )
    with op.batch_alter_table("account_syncs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_account_syncs_account_id_started_at"),
            ["account_id", "started_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("account_syncs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_account_syncs_account_id_started_at"))
    op.drop_table("account_syncs")
