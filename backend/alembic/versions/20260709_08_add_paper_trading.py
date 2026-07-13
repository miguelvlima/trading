"""paper trading portfolios, orders, positions, trades and engine events

Revision ID: 20260709_08
Revises: 20260625_07
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260709_08"
down_revision: str | None = "20260625_07"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_portfolios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("initial_cash", sa.Numeric(18, 8), nullable=False),
        sa.Column("cash", sa.Numeric(18, 8), nullable=False),
        sa.Column("equity", sa.Numeric(18, 8), nullable=False),
        sa.Column("risk_settings", sa.JSON(), nullable=False),
        sa.Column("engine_running", sa.Boolean(), nullable=False),
        sa.Column("kill_switch_active", sa.Boolean(), nullable=False),
        sa.Column("kill_switch_reason", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_user_id", name="uq_paper_portfolios_owner"),
    )
    op.create_index("ix_paper_portfolios_owner_user_id", "paper_portfolios", ["owner_user_id"])

    op.create_table(
        "paper_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("stop_loss_pct", sa.Numeric(10, 6), nullable=True),
        sa.Column("take_profit_pct", sa.Numeric(10, 6), nullable=True),
        sa.Column("signal_snapshot", sa.JSON(), nullable=False),
        sa.Column("risk_snapshot", sa.JSON(), nullable=False),
        sa.Column("data_liveness", sa.String(length=16), nullable=False),
        sa.Column("reject_reason", sa.String(length=512), nullable=True),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["portfolio_id"], ["paper_portfolios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_paper_orders_portfolio_id", "paper_orders", ["portfolio_id"])
    op.create_index("ix_paper_orders_symbol", "paper_orders", ["symbol"])
    op.create_index("ix_paper_orders_status", "paper_orders", ["status"])

    op.create_table(
        "paper_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("avg_entry_price", sa.Numeric(18, 8), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(18, 8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["portfolio_id"], ["paper_portfolios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("portfolio_id", "symbol", name="uq_paper_positions_portfolio_symbol"),
    )
    op.create_index("ix_paper_positions_portfolio_id", "paper_positions", ["portfolio_id"])
    op.create_index("ix_paper_positions_symbol", "paper_positions", ["symbol"])

    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("price", sa.Numeric(18, 8), nullable=False),
        sa.Column("fee_paid", sa.Numeric(18, 8), nullable=False),
        sa.Column("fill_basis", sa.String(length=16), nullable=False),
        sa.Column("quote_age_seconds", sa.Numeric(10, 3), nullable=True),
        sa.Column("data_liveness", sa.String(length=16), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(18, 8), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["paper_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["portfolio_id"], ["paper_portfolios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_paper_trades_portfolio_id", "paper_trades", ["portfolio_id"])
    op.create_index("ix_paper_trades_order_id", "paper_trades", ["order_id"])
    op.create_index("ix_paper_trades_symbol", "paper_trades", ["symbol"])

    op.create_table(
        "paper_engine_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("message", sa.String(length=512), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["portfolio_id"], ["paper_portfolios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_paper_engine_events_portfolio_id", "paper_engine_events", ["portfolio_id"])
    op.create_index("ix_paper_engine_events_event_type", "paper_engine_events", ["event_type"])
    op.create_index("ix_paper_engine_events_symbol", "paper_engine_events", ["symbol"])
    op.create_index("ix_paper_engine_events_created_at", "paper_engine_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_paper_engine_events_created_at", table_name="paper_engine_events")
    op.drop_index("ix_paper_engine_events_symbol", table_name="paper_engine_events")
    op.drop_index("ix_paper_engine_events_event_type", table_name="paper_engine_events")
    op.drop_index("ix_paper_engine_events_portfolio_id", table_name="paper_engine_events")
    op.drop_table("paper_engine_events")
    op.drop_index("ix_paper_trades_symbol", table_name="paper_trades")
    op.drop_index("ix_paper_trades_order_id", table_name="paper_trades")
    op.drop_index("ix_paper_trades_portfolio_id", table_name="paper_trades")
    op.drop_table("paper_trades")
    op.drop_index("ix_paper_positions_symbol", table_name="paper_positions")
    op.drop_index("ix_paper_positions_portfolio_id", table_name="paper_positions")
    op.drop_table("paper_positions")
    op.drop_index("ix_paper_orders_status", table_name="paper_orders")
    op.drop_index("ix_paper_orders_symbol", table_name="paper_orders")
    op.drop_index("ix_paper_orders_portfolio_id", table_name="paper_orders")
    op.drop_table("paper_orders")
    op.drop_index("ix_paper_portfolios_owner_user_id", table_name="paper_portfolios")
    op.drop_table("paper_portfolios")
