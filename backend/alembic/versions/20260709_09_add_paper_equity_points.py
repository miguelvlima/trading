"""paper equity snapshots so the cockpit curve survives reloads

Revision ID: 20260709_09
Revises: 20260709_08
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260709_09"
down_revision: str | None = "20260709_08"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_equity_points",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("equity", sa.Numeric(18, 8), nullable=False),
        sa.Column("cash", sa.Numeric(18, 8), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["portfolio_id"], ["paper_portfolios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_paper_equity_points_portfolio_id", "paper_equity_points", ["portfolio_id"])
    op.create_index("ix_paper_equity_points_at", "paper_equity_points", ["at"])


def downgrade() -> None:
    op.drop_index("ix_paper_equity_points_at", table_name="paper_equity_points")
    op.drop_index("ix_paper_equity_points_portfolio_id", table_name="paper_equity_points")
    op.drop_table("paper_equity_points")
