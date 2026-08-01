"""manual payment verification system - phase 17

Revision ID: 0018_payments
Revises: 0017_analytics_anticheat
Create Date: 2026-08-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_payments"
down_revision: Union[str, None] = "0017_analytics_anticheat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    payment_provider = postgresql.ENUM(
        "manual_upi", "razorpay", "cashfree", "phonepe", name="payment_provider", create_type=False
    )
    payment_request_status = postgresql.ENUM(
        "pending", "approved", "rejected", "cancelled", "on_hold", name="payment_request_status", create_type=False
    )
    payment_rejection_reason = postgresql.ENUM(
        "invalid_utr",
        "wrong_amount",
        "fake_screenshot",
        "duplicate_utr",
        "other",
        name="payment_rejection_reason",
        create_type=False,
    )
    payment_provider.create(bind, checkfirst=True)
    payment_request_status.create(bind, checkfirst=True)
    payment_rejection_reason.create(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # payment_settings (singleton row, admin-managed)
    # ------------------------------------------------------------------
    op.create_table(
        "payment_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("upi_id", sa.String(255), nullable=True),
        sa.Column("merchant_name", sa.String(255), server_default="ClassyBattle", nullable=False),
        sa.Column("payment_note", sa.String(255), nullable=True),
        sa.Column("is_upi_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("min_deposit_amount", sa.Numeric(14, 2), server_default="10", nullable=False),
        sa.Column("max_deposit_amount", sa.Numeric(14, 2), server_default="100000", nullable=False),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
    )

    # ------------------------------------------------------------------
    # payment_requests
    # ------------------------------------------------------------------
    op.create_table(
        "payment_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "provider", payment_provider, server_default="manual_upi", nullable=False
        ),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="INR", nullable=False),
        sa.Column("upi_id_used", sa.String(255), nullable=True),
        sa.Column("qr_payload", sa.Text(), nullable=True),
        sa.Column("screenshot_url", sa.String(1000), nullable=False),
        sa.Column("utr_number", sa.String(64), nullable=True),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column(
            "status", payment_request_status, server_default="pending", nullable=False
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("verified_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", payment_rejection_reason, nullable=True),
        sa.Column("rejection_note", sa.String(500), nullable=True),
        sa.Column("admin_note", sa.String(500), nullable=True),
        sa.Column("wallet_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["verified_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["wallet_transaction_id"], ["wallet_transactions.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint("amount > 0", name="ck_payment_requests_amount_positive"),
        sa.UniqueConstraint("utr_number", name="uq_payment_requests_utr_number"),
    )
    op.create_index("ix_payment_requests_user_id", "payment_requests", ["user_id"])
    op.create_index("ix_payment_requests_provider", "payment_requests", ["provider"])
    op.create_index("ix_payment_requests_status", "payment_requests", ["status"])
    op.create_index(
        "ix_payment_requests_provider_reference", "payment_requests", ["provider_reference"]
    )
    op.create_index("ix_payment_requests_user_status", "payment_requests", ["user_id", "status"])
    op.create_index(
        "ix_payment_requests_status_submitted", "payment_requests", ["status", "submitted_at"]
    )


def downgrade() -> None:
    op.drop_table("payment_requests")
    op.drop_table("payment_settings")

    bind = op.get_bind()
    postgresql.ENUM(name="payment_rejection_reason").drop(bind, checkfirst=True)
    postgresql.ENUM(name="payment_request_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="payment_provider").drop(bind, checkfirst=True)