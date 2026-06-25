"""live signal source and backtest run insights

Revision ID: 20260625_07
Revises: 20260625_06
Create Date: 2026-06-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260625_07"
down_revision: str | None = "20260625_06"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "signals",
        sa.Column("source", sa.String(length=16), nullable=False, server_default="historical"),
    )
    op.create_index("ix_signals_source", "signals", ["source"])

    op.create_table(
        "backtest_run_insights",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("strategy_names", sa.JSON(), nullable=False),
        sa.Column("narrative_summary", sa.Text(), nullable=False),
        sa.Column("timeline", sa.JSON(), nullable=False),
        sa.Column("failure_modes", sa.JSON(), nullable=False),
        sa.Column("lessons", sa.JSON(), nullable=False),
        sa.Column("recommendations", sa.JSON(), nullable=False),
        sa.Column("prior_runs_context", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_backtest_run_insights_run_id"),
    )
    op.create_index("ix_backtest_run_insights_owner_user_id", "backtest_run_insights", ["owner_user_id"])
    op.create_index("ix_backtest_run_insights_symbol", "backtest_run_insights", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_backtest_run_insights_symbol", table_name="backtest_run_insights")
    op.drop_index("ix_backtest_run_insights_owner_user_id", table_name="backtest_run_insights")
    op.drop_table("backtest_run_insights")
    op.drop_index("ix_signals_source", table_name="signals")
    op.drop_column("signals", "source")
