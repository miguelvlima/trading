"""add signals table

Revision ID: 20260622_02
Revises: 20260622_01
Create Date: 2026-06-22 13:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260622_02"
down_revision: str | None = "20260622_01"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("strength", sa.Numeric(precision=6, scale=5), nullable=False),
        sa.Column("rationale", sa.String(length=512), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("indicator_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_signals_instrument_id", "signals", ["instrument_id"])
    op.create_index("ix_signals_symbol", "signals", ["symbol"])
    op.create_index("ix_signals_strategy", "signals", ["strategy"])
    op.create_index("ix_signals_timestamp", "signals", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_signals_timestamp", table_name="signals")
    op.drop_index("ix_signals_strategy", table_name="signals")
    op.drop_index("ix_signals_symbol", table_name="signals")
    op.drop_index("ix_signals_instrument_id", table_name="signals")
    op.drop_table("signals")
