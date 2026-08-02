"""add payment_methods and withdrawal_requests

Revision ID: 0021_withdrawals
Revises: 0020_tournament_rules
Create Date: 2026-08-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_withdrawals"
down_revision: Union[str, None] = "0020_tournament_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

payment_method_type = postgresql.ENUM(
    "upi", "bank_account", name="payment_method_type", create_type=False
)
withdrawal_status = postgresql.ENUM(
    "pending", "completed", "cancelled", "rejected", name="withdrawal_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    payment_method_type.create(bind, checkfirst=True)
    withdrawal_status.create(bind, checkfirst=True)

    op.create_table(
        "payment_methods",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("method_type", payment_method_type, nullable=False),
        sa.Column("account_holder_name", sa.String(length=150), nullable=False),
        sa.Column("upi_id", sa.String(length=150), nullable=True),
        sa.Column("account_number", sa.String(length=34), nullable=True),
        sa.Column("ifsc_code", sa.String(length=11), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
    )
    op.create_index("ix_payment_methods_user_id", "payment_methods", ["user_id"])
    op.create_index("ix_payment_methods_method_type", "payment_methods", ["method_type"])

    op.create_table(
        "withdrawal_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("payment_method_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payment_methods.id", ondelete="SET NULL"), nullable=True),
        sa.Column("method_type", payment_method_type, nullable=False),
        sa.Column("method_details", postgresql.JSONB(), nullable=False),
        sa.Column("status", withdrawal_status, server_default="pending", nullable=False),
        sa.Column("hold_transaction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("wallet_transactions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("settlement_transaction_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("wallet_transactions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("processed_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_note", sa.String(length=500), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_withdrawal_requests_amount_positive"),
    )
    op.create_index("ix_withdrawal_requests_user_id", "withdrawal_requests", ["user_id"])
    op.create_index("ix_withdrawal_requests_status", "withdrawal_requests", ["status"])
    op.create_index("ix_withdrawal_requests_user_status", "withdrawal_requests", ["user_id", "status"])
    op.create_index("ix_withdrawal_requests_status_created", "withdrawal_requests", ["status", "created_at"])


def downgrade() -> None:
    op.drop_table("withdrawal_requests")
    op.drop_table("payment_methods")
    bind = op.get_bind()
    withdrawal_status.drop(bind, checkfirst=True)
    payment_method_type.drop(bind, checkfirst=True)