"""
WalletTransaction model — Phase 8 (Enterprise Wallet System).

Append-only ledger. Every balance mutation on a Wallet MUST be
accompanied by exactly one WalletTransaction row created in the same
DB transaction. Rows are never updated after creation except for the
`status` field transitioning PENDING -> (SUCCESS | FAILED | CANCELLED),
which represents settlement of a previously-held transaction (e.g. a
HOLD later becoming a captured DEBIT via RELEASE_HOLD).
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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database.base import Base
from app.database.types import PortableJSONB


class WalletTransactionType(str, enum.Enum):
    CREDIT = "credit"
    DEBIT = "debit"
    HOLD = "hold"
    RELEASE_HOLD = "release_hold"
    REFUND = "refund"
    BONUS = "bonus"
    ADMIN_ADJUSTMENT = "admin_adjustment"


class WalletTransactionStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WalletTransaction(Base):
    """Immutable ledger entry. Does NOT inherit BaseModel's soft-delete /
    updated_at mixins — ledger rows are append-only and never soft
    deleted; `status` is the only field that transitions post-creation."""

    __tablename__ = "wallet_transactions"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_wallet_transactions_amount_non_negative"),
        UniqueConstraint(
            "reference_type", "reference_id", "type", name="uq_wallet_txn_reference_type"
        ),
        Index("ix_wallet_transactions_wallet_created", "wallet_id", "created_at"),
        Index("ix_wallet_transactions_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )

    wallet_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalized for fast "my transactions" queries without a join.
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    type: Mapped[WalletTransactionType] = mapped_column(
        Enum(WalletTransactionType, name="wallet_transaction_type"), nullable=False, index=True
    )
    status: Mapped[WalletTransactionStatus] = mapped_column(
        Enum(WalletTransactionStatus, name="wallet_transaction_status"),
        default=WalletTransactionStatus.SUCCESS,
        nullable=False,
        index=True,
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR", nullable=False)

    # Balance snapshot *after* this transaction was applied — makes the
    # ledger self-auditing without replaying every prior row.
    available_balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    locked_balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    # Free-text, human readable reason (e.g. "Tournament entry fee hold").
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Polymorphic reference to whatever domain object caused this entry,
    # e.g. reference_type="tournament_entry", reference_id=<participant.id>.
    reference_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    reference_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # Links a RELEASE_HOLD/REFUND/CANCELLED entry back to the original
    # HOLD/DEBIT transaction it settles.
    related_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("wallet_transactions.id", ondelete="SET NULL"), nullable=True
    )

    # Who performed an admin adjustment (null for user/system-driven entries).
    performed_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    metadata_json: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    wallet: Mapped["Wallet"] = relationship(back_populates="transactions", lazy="selectin")  # noqa: F821
    user: Mapped["User"] = relationship(  # noqa: F821
        foreign_keys=[user_id], lazy="selectin"
    )
    performed_by: Mapped[Optional["User"]] = relationship(  # noqa: F821
        foreign_keys=[performed_by_id], lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<WalletTransaction id={self.id} wallet_id={self.wallet_id} "
            f"type={self.type} status={self.status} amount={self.amount}>"
        )
