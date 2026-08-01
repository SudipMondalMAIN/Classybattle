"""enterprise wallet system - phase 8

Revision ID: 0009_wallet
Revises: 0008_backend_hardening
Create Date: 2026-07-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_wallet"
down_revision: Union[str, None] = "0008_backend_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    wallet_transaction_type = postgresql.ENUM(
        "credit",
        "debit",
        "hold",
        "release_hold",
        "refund",
        "bonus",
        "admin_adjustment",
        name="wallet_transaction_type",
        create_type=False,
    )
    wallet_transaction_status = postgresql.ENUM(
        "pending", "success", "failed", "cancelled", name="wallet_transaction_status", create_type=False
    )
    bind = op.get_bind()
    wallet_transaction_type.create(bind, checkfirst=True)
    wallet_transaction_status.create(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # wallets
    # ------------------------------------------------------------------
    op.create_table(
        "wallets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("available_balance", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("locked_balance", sa.Numeric(14, 2), server_default="0", nullable=False),
        sa.Column("currency", sa.String(3), server_default="INR", nullable=False),
        sa.Column("is_frozen", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_wallets_user_id"),
        sa.CheckConstraint("available_balance >= 0", name="ck_wallets_available_balance_non_negative"),
        sa.CheckConstraint("locked_balance >= 0", name="ck_wallets_locked_balance_non_negative"),
    )
    op.create_index("ix_wallets_user_id", "wallets", ["user_id"])

    # ------------------------------------------------------------------
    # wallet_transactions
    # ------------------------------------------------------------------
    op.create_table(
        "wallet_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("wallet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", wallet_transaction_type, nullable=False),
        sa.Column(
            "status",
            wallet_transaction_status,
            server_default="success",
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="INR", nullable=False),
        sa.Column("available_balance_after", sa.Numeric(14, 2), nullable=False),
        sa.Column("locked_balance_after", sa.Numeric(14, 2), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("reference_type", sa.String(100), nullable=True),
        sa.Column("reference_id", sa.String(100), nullable=True),
        sa.Column("related_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("performed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["related_transaction_id"], ["wallet_transactions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["performed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("amount >= 0", name="ck_wallet_transactions_amount_non_negative"),
        sa.UniqueConstraint(
            "reference_type", "reference_id", "type", name="uq_wallet_txn_reference_type"
        ),
    )
    op.create_index("ix_wallet_transactions_wallet_id", "wallet_transactions", ["wallet_id"])
    op.create_index("ix_wallet_transactions_user_id", "wallet_transactions", ["user_id"])
    op.create_index("ix_wallet_transactions_type", "wallet_transactions", ["type"])
    op.create_index("ix_wallet_transactions_status", "wallet_transactions", ["status"])
    op.create_index("ix_wallet_transactions_reference_type", "wallet_transactions", ["reference_type"])
    op.create_index("ix_wallet_transactions_reference_id", "wallet_transactions", ["reference_id"])
    op.create_index("ix_wallet_transactions_created_at", "wallet_transactions", ["created_at"])
    op.create_index(
        "ix_wallet_transactions_wallet_created", "wallet_transactions", ["wallet_id", "created_at"]
    )
    op.create_index(
        "ix_wallet_transactions_user_created", "wallet_transactions", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("wallet_transactions")
    op.drop_table("wallets")

    bind = op.get_bind()
    postgresql.ENUM(name="wallet_transaction_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="wallet_transaction_type").drop(bind, checkfirst=True)
