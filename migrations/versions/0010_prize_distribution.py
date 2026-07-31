"""prize pool & prize distribution system - phase 10

Revision ID: 0010_prize_distribution
Revises: 0009_wallet
Create Date: 2026-07-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_prize_distribution"
down_revision: Union[str, None] = "0009_wallet"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    prize_distribution_type = postgresql.ENUM(
        "single_winner", "top_n", "percentage", "fixed_amount", name="prize_distribution_type"
    )
    prize_pool_status = postgresql.ENUM(
        "draft", "published", "distributing", "distributed", "cancelled", name="prize_pool_status"
    )
    prize_payout_status = postgresql.ENUM(
        "pending", "processing", "paid", "failed", "cancelled", name="prize_payout_status"
    )
    bind = op.get_bind()
    prize_distribution_type.create(bind, checkfirst=True)
    prize_pool_status.create(bind, checkfirst=True)
    prize_payout_status.create(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # prize_pools
    # ------------------------------------------------------------------
    op.create_table(
        "prize_pools",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="INR", nullable=False),
        sa.Column("distribution_type", prize_distribution_type, nullable=False),
        sa.Column("distribution_rules", postgresql.JSONB(), nullable=False),
        sa.Column("status", prize_pool_status, server_default="draft", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("distributed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tournament_id", name="uq_prize_pools_tournament_id"),
        sa.CheckConstraint("total_amount >= 0", name="ck_prize_pools_total_amount_non_negative"),
    )
    op.create_index("ix_prize_pools_tournament_id", "prize_pools", ["tournament_id"])
    op.create_index("ix_prize_pools_status", "prize_pools", ["status"])

    # ------------------------------------------------------------------
    # prize_payouts
    # ------------------------------------------------------------------
    op.create_table(
        "prize_payouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prize_pool_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tournament_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("participant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="INR", nullable=False),
        sa.Column("status", prize_payout_status, server_default="pending", nullable=False),
        sa.Column("wallet_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("performed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["prize_pool_id"], ["prize_pools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["wallet_transaction_id"], ["wallet_transactions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["performed_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("prize_pool_id", "rank", name="uq_prize_payouts_pool_rank"),
        sa.UniqueConstraint(
            "prize_pool_id", "participant_id", name="uq_prize_payouts_pool_participant"
        ),
        sa.CheckConstraint("amount >= 0", name="ck_prize_payouts_amount_non_negative"),
        sa.CheckConstraint("rank > 0", name="ck_prize_payouts_rank_positive"),
        sa.CheckConstraint("retry_count >= 0", name="ck_prize_payouts_retry_count_non_negative"),
    )
    op.create_index("ix_prize_payouts_prize_pool_id", "prize_payouts", ["prize_pool_id"])
    op.create_index("ix_prize_payouts_tournament_id", "prize_payouts", ["tournament_id"])
    op.create_index("ix_prize_payouts_participant_id", "prize_payouts", ["participant_id"])
    op.create_index("ix_prize_payouts_user_id", "prize_payouts", ["user_id"])
    op.create_index("ix_prize_payouts_status", "prize_payouts", ["status"])
    op.create_index("ix_prize_payouts_pool_status", "prize_payouts", ["prize_pool_id", "status"])


def downgrade() -> None:
    op.drop_table("prize_payouts")
    op.drop_table("prize_pools")

    bind = op.get_bind()
    postgresql.ENUM(name="prize_payout_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="prize_pool_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="prize_distribution_type").drop(bind, checkfirst=True)
