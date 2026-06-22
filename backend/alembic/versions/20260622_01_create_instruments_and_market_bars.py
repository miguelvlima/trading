"""create instruments and market_bars

Revision ID: 20260622_01
Revises:
Create Date: 2026-06-22 12:00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260622_01"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("exchange", sa.String(length=64), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", name="uq_instruments_symbol"),
    )

    op.create_table(
        "market_bars",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("high", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("low", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("close", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("volume", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_id",
            "timeframe",
            "timestamp",
            name="uq_market_bars_instrument_timeframe_timestamp",
        ),
    )

    op.create_index("ix_market_bars_instrument_id", "market_bars", ["instrument_id"])
    op.create_index("ix_market_bars_timestamp", "market_bars", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_market_bars_timestamp", table_name="market_bars")
    op.drop_index("ix_market_bars_instrument_id", table_name="market_bars")
    op.drop_table("market_bars")
    op.drop_table("instruments")
