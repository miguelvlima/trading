"""add users and strategy combinations

Revision ID: 20260622_03
Revises: 20260622_02
Create Date: 2026-06-22 18:10:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260622_03"
down_revision: str | None = "20260622_02"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.add_column("signals", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_index("ix_signals_user_id", "signals", ["user_id"])
    op.create_foreign_key(
        "fk_signals_user_id_users",
        "signals",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "strategy_combinations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("cloned_from_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("strategies", sa.JSON(), nullable=False),
        sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["cloned_from_id"], ["strategy_combinations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_strategy_combinations_owner_user_id", "strategy_combinations", ["owner_user_id"])
    op.create_index("ix_strategy_combinations_cloned_from_id", "strategy_combinations", ["cloned_from_id"])


def downgrade() -> None:
    op.drop_index("ix_strategy_combinations_cloned_from_id", table_name="strategy_combinations")
    op.drop_index("ix_strategy_combinations_owner_user_id", table_name="strategy_combinations")
    op.drop_table("strategy_combinations")

    op.drop_constraint("fk_signals_user_id_users", "signals", type_="foreignkey")
    op.drop_index("ix_signals_user_id", table_name="signals")
    op.drop_column("signals", "user_id")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
