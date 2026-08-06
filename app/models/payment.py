"""
Payment models — Phase 17 (Payment & Financial Operations).

Two tables:

- PaymentSettings: a single admin-managed row holding the UPI receiving
  details (UPI ID, merchant name, note) and a global enable/disable
  switch for manual UPI deposits. Read on every "generate deposit QR"
  call and updated only via the admin payment-settings APIs.

- PaymentRequest: one row per user deposit attempt. Created when the
  user submits a payment screenshot + UTR number after paying the
  generated UPI QR, and transitioned by an admin (approve / reject /
  hold) via PaymentService. `provider` is included from day one (even
  though only MANUAL is usable in this phase) so a real gateway
  (Razorpay/Cashfree/PhonePe) can be plugged in later without a schema
  migration: it would simply add rows with provider != MANUAL and
  populate `provider_reference` instead of `utr_number`.
"""
import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database.base import Base, BaseModel, ShortIdMixin
from app.database.types import PortableJSONB, str_enum


class PaymentProvider(str, enum.Enum):
    """The rail a deposit was (or will be) processed through. Only MANUAL
    is active in Phase 17; the others are reserved so a future gateway
    integration can reuse this table/enum without a migration."""

    MANUAL_UPI = "manual_upi"
    RAZORPAY = "razorpay"
    CASHFREE = "cashfree"
    PHONEPE = "phonepe"


class PaymentRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ON_HOLD = "on_hold"


class PaymentRejectionReason(str, enum.Enum):
    INVALID_UTR = "invalid_utr"
    WRONG_AMOUNT = "wrong_amount"
    FAKE_SCREENSHOT = "fake_screenshot"
    DUPLICATE_UTR = "duplicate_utr"
    OTHER = "other"


class PaymentSettings(Base):
    """Singleton row (application enforces at most one). Not built on
    BaseModel's soft-delete mixin — settings are updated in place, never
    soft deleted."""

    __tablename__ = "payment_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )

    upi_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    merchant_name: Mapped[str] = mapped_column(String(255), default="ClassyBattle", nullable=False)
    payment_note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_upi_enabled: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False)

    min_deposit_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=10, server_default="10", nullable=False
    )
    max_deposit_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=100000, server_default="100000", nullable=False
    )

    updated_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    updated_by: Mapped[Optional["User"]] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<PaymentSettings id={self.id} upi_enabled={self.is_upi_enabled}>"


class PaymentRequest(ShortIdMixin, BaseModel):
    """One user deposit attempt, manually verified by an admin against a
    UPI screenshot + UTR number. Approval credits the wallet exactly once
    (enforced by the unique WalletTransaction reference on
    (reference_type='payment_deposit', reference_id=<this id>, type=CREDIT))."""

    __tablename__ = "payment_requests"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_requests_amount_positive"),
        # A given UTR may only ever be submitted once across the whole
        # table — the core defence against duplicate-UTR fraud.
        UniqueConstraint("utr_number", name="uq_payment_requests_utr_number"),
        UniqueConstraint("txn_no", name="uq_payment_requests_txn_no"),
        Index("ix_payment_requests_user_status", "user_id", "status"),
        Index("ix_payment_requests_status_submitted", "status", "submitted_at"),
    )

    # 10-digit numeric transaction reference shown to the user, distinct
    # from the internal UUID `id` and the admin-facing `short_id`.
    txn_no: Mapped[str] = mapped_column(String(10), nullable=False, index=True)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    provider: Mapped[PaymentProvider] = mapped_column(
        str_enum(PaymentProvider, "payment_provider"),
        default=PaymentProvider.MANUAL_UPI,
        server_default=PaymentProvider.MANUAL_UPI.value,
        nullable=False,
        index=True,
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR", nullable=False)

    # UPI details captured at submission time (snapshot — settings may
    # change later, but this row must keep showing what the user actually
    # paid to).
    upi_id_used: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    qr_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    screenshot_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    # Nullable at the column level only so future non-manual providers
    # (which use provider_reference instead) can reuse this table; the
    # service layer requires it for MANUAL_UPI.
    utr_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Reserved for a future real gateway's own transaction/order id.
    provider_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    status: Mapped[PaymentRequestStatus] = mapped_column(
        str_enum(PaymentRequestStatus, "payment_request_status"),
        default=PaymentRequestStatus.PENDING,
        server_default=PaymentRequestStatus.PENDING.value,
        nullable=False,
        index=True,
    )

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    verified_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    rejection_reason: Mapped[Optional[PaymentRejectionReason]] = mapped_column(
        str_enum(PaymentRejectionReason, "payment_rejection_reason"), nullable=True
    )
    rejection_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    admin_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Set once approval successfully credits the wallet — links back to
    # the immutable ledger row for full traceability.
    wallet_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("wallet_transactions.id", ondelete="SET NULL"), nullable=True
    )

    metadata_json: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)

    user: Mapped["User"] = relationship(foreign_keys=[user_id], lazy="selectin")  # noqa: F821
    verified_by: Mapped[Optional["User"]] = relationship(  # noqa: F821
        foreign_keys=[verified_by_id], lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<PaymentRequest id={self.id} user_id={self.user_id} "
            f"amount={self.amount} status={self.status}>"
        )
