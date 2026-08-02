"""
WithdrawalRequest model — Wallet Withdrawal System.

A user requests a withdrawal against a saved PaymentMethod. On submission
the amount is HOLD-ed in the wallet (moved available -> locked) so it
can't be spent elsewhere while the request is pending. An admin then pays
the user manually via the snapshotted method details and marks the
request COMPLETED (captures the hold — funds leave the wallet for good),
or CANCELLED/REJECTED (releases the hold — funds return to available).
"""
import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel, ShortIdMixin
from app.database.types import PortableJSONB, str_enum
from app.models.payment_method import PaymentMethodType


class WithdrawalStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class WithdrawalRequest(ShortIdMixin, BaseModel):
    __tablename__ = "withdrawal_requests"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_withdrawal_requests_amount_positive"),
        Index("ix_withdrawal_requests_user_status", "user_id", "status"),
        Index("ix_withdrawal_requests_status_created", "status", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR", nullable=False)

    payment_method_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("payment_methods.id", ondelete="SET NULL"), nullable=True
    )
    # Snapshot of the payment method at request time — the method the
    # user picked can be edited/deleted later, but this must keep showing
    # exactly what the admin is meant to pay out to.
    method_type: Mapped[PaymentMethodType] = mapped_column(
        str_enum(PaymentMethodType, "payment_method_type"), nullable=False
    )
    method_details: Mapped[dict] = mapped_column(PortableJSONB, nullable=False)

    status: Mapped[WithdrawalStatus] = mapped_column(
        str_enum(WithdrawalStatus, "withdrawal_status"),
        default=WithdrawalStatus.PENDING,
        server_default=WithdrawalStatus.PENDING.value,
        nullable=False,
        index=True,
    )

    # Links to the wallet HOLD transaction created at submission, and the
    # RELEASE_HOLD transaction that settles it (capture or refund).
    hold_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("wallet_transactions.id", ondelete="SET NULL"), nullable=True
    )
    settlement_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("wallet_transactions.id", ondelete="SET NULL"), nullable=True
    )

    processed_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    admin_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    user: Mapped["User"] = relationship(foreign_keys=[user_id], lazy="selectin")  # noqa: F821
    processed_by: Mapped[Optional["User"]] = relationship(  # noqa: F821
        foreign_keys=[processed_by_id], lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<WithdrawalRequest id={self.id} user_id={self.user_id} "
            f"amount={self.amount} status={self.status}>"
        )