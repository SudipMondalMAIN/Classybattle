"""
Wallet model — Phase 8 (Enterprise Wallet System).

One wallet per user. Holds two balances:
- available_balance: funds the user can spend/withdraw right now.
- locked_balance: funds held (e.g. against a pending match/tournament
  entry) that cannot be spent until released, captured, or refunded.

Balances are only ever mutated through WalletService inside a single
DB transaction alongside the corresponding immutable WalletTransaction
row, so the wallet balance is always reconstructible from/consistent
with the transaction ledger.
"""
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel


class Wallet(BaseModel):
    """A single wallet belonging to exactly one user."""

    __tablename__ = "wallets"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_wallets_user_id"),
        CheckConstraint("available_balance >= 0", name="ck_wallets_available_balance_non_negative"),
        CheckConstraint("locked_balance >= 0", name="ck_wallets_locked_balance_non_negative"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    available_balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=0, server_default="0", nullable=False
    )
    locked_balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=0, server_default="0", nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR", nullable=False)

    is_frozen: Mapped[bool] = mapped_column(default=False, server_default="false", nullable=False)

    user: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821
    transactions: Mapped[list["WalletTransaction"]] = relationship(  # noqa: F821
        back_populates="wallet",
        cascade="all, delete-orphan",
        lazy="noload",
        order_by="WalletTransaction.created_at.desc()",
    )

    @property
    def total_balance(self) -> Decimal:
        return self.available_balance + self.locked_balance

    def __repr__(self) -> str:
        return (
            f"<Wallet id={self.id} user_id={self.user_id} "
            f"available={self.available_balance} locked={self.locked_balance}>"
        )
