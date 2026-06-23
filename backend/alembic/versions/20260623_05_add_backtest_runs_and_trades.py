"""add backtest runs and trades

Revision ID: 20260623_05
Revises: 20260622_04
Create Date: 2026-06-23 14:45:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260623_05"
down_revision: str | None = "20260622_04"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("strategy_names", sa.JSON(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("initial_capital", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("fee_bps", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("slippage_bps", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("min_signal_strength", sa.Numeric(precision=6, scale=5), nullable=False),
        sa.Column("bars_processed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("trades_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("net_pnl", sa.Numeric(precision=18, scale=8), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "net_pnl_pct", sa.Numeric(precision=10, scale=6), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("win_rate", sa.Numeric(precision=10, scale=6), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "profit_factor", sa.Numeric(precision=18, scale=8), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "max_drawdown_pct",
            sa.Numeric(precision=10, scale=6),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("result_summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backtest_runs_owner_user_id", "backtest_runs", ["owner_user_id"])
    op.create_index("ix_backtest_runs_instrument_id", "backtest_runs", ["instrument_id"])
    op.create_index("ix_backtest_runs_symbol", "backtest_runs", ["symbol"])

    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.Column("entry_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("exit_price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("gross_pnl", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("fee_paid", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("net_pnl", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("return_pct", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("bars_held", sa.Integer(), nullable=False),
        sa.Column("entry_reason", sa.String(length=512), nullable=False),
        sa.Column("exit_reason", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backtest_trades_run_id", "backtest_trades", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_backtest_trades_run_id", table_name="backtest_trades")
    op.drop_table("backtest_trades")

    op.drop_index("ix_backtest_runs_symbol", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_instrument_id", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_owner_user_id", table_name="backtest_runs")
    op.drop_table("backtest_runs")
