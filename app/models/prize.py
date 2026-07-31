"""
Prize Pool & Prize Distribution models — Phase 10.

- PrizePool: one active prize configuration per tournament. Holds the
  total prize amount and the rank-based distribution rules (percentage
  or fixed-amount per rank / top-N / single-winner).
- PrizePayout: one row per (prize_pool, rank) — the concrete payout owed
  to whichever participant finished at that rank. Distribution is driven
  by transitioning payouts PENDING -> PROCESSING -> PAID, crediting the
  winner's Wallet (Phase 8) via WalletService inside a single atomic DB
  transaction. Duplicate payouts are prevented at the DB level (unique
  constraints on rank and participant per pool) and further protected by
  WalletTransaction's own (reference_type, reference_id, type) uniqueness
  constraint, making distribution idempotent even under retries.
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
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel
from app.database.types import PortableJSONB


class PrizeDistributionType(str, enum.Enum):
    SINGLE_WINNER = "single_winner"
    TOP_N = "top_n"
    PERCENTAGE = "percentage"
    FIXED_AMOUNT = "fixed_amount"


class PrizePoolStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    DISTRIBUTING = "distributing"
    DISTRIBUTED = "distributed"
    CANCELLED = "cancelled"


# Explicit allowed forward transitions, mirroring the pattern used for
# TOURNAMENT_STATUS_TRANSITIONS / PARTICIPANT_STATUS_TRANSITIONS.
PRIZE_POOL_STATUS_TRANSITIONS: dict[PrizePoolStatus, set[PrizePoolStatus]] = {
    PrizePoolStatus.DRAFT: {PrizePoolStatus.PUBLISHED, PrizePoolStatus.CANCELLED},
    PrizePoolStatus.PUBLISHED: {PrizePoolStatus.DISTRIBUTING, PrizePoolStatus.CANCELLED},
    PrizePoolStatus.DISTRIBUTING: {PrizePoolStatus.DISTRIBUTED, PrizePoolStatus.PUBLISHED},
    PrizePoolStatus.DISTRIBUTED: set(),
    PrizePoolStatus.CANCELLED: set(),
}


class PrizePayoutStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PrizePool(BaseModel):
    """One prize pool configuration per tournament."""

    __tablename__ = "prize_pools"
    __table_args__ = (
        UniqueConstraint("tournament_id", name="uq_prize_pools_tournament_id"),
        CheckConstraint("total_amount >= 0", name="ck_prize_pools_total_amount_non_negative"),
    )

    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR", nullable=False)

    distribution_type: Mapped[PrizeDistributionType] = mapped_column(
        Enum(PrizeDistributionType, name="prize_distribution_type"), nullable=False
    )

    # Rank-based distribution rules, e.g.:
    #   [{"rank": 1, "percentage": "60.00"}, {"rank": 2, "percentage": "40.00"}]
    # or [{"rank": 1, "amount": "1000.00"}, {"rank": 2, "amount": "500.00"}]
    # Validated by PrizeService against distribution_type + total_amount
    # before the pool can be published.
    distribution_rules: Mapped[list] = mapped_column(PortableJSONB, nullable=False)

    status: Mapped[PrizePoolStatus] = mapped_column(
        Enum(PrizePoolStatus, name="prize_pool_status"),
        default=PrizePoolStatus.DRAFT,
        nullable=False,
        index=True,
    )

    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    distributed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    tournament: Mapped["Tournament"] = relationship(lazy="selectin")  # noqa: F821
    creator: Mapped[Optional["User"]] = relationship(lazy="selectin")  # noqa: F821
    payouts: Mapped[list["PrizePayout"]] = relationship(
        back_populates="prize_pool",
        cascade="all, delete-orphan",
        lazy="noload",
        order_by="PrizePayout.rank.asc()",
    )

    def __repr__(self) -> str:
        return (
            f"<PrizePool id={self.id} tournament_id={self.tournament_id} "
            f"total_amount={self.total_amount} status={self.status}>"
        )


class PrizePayout(BaseModel):
    """One payout owed to whichever participant finished at `rank` within
    a given PrizePool. Created (in PENDING) when winners are assigned,
    settled to PAID by crediting the winner's wallet."""

    __tablename__ = "prize_payouts"
    __table_args__ = (
        UniqueConstraint("prize_pool_id", "rank", name="uq_prize_payouts_pool_rank"),
        UniqueConstraint(
            "prize_pool_id", "participant_id", name="uq_prize_payouts_pool_participant"
        ),
        CheckConstraint("amount >= 0", name="ck_prize_payouts_amount_non_negative"),
        CheckConstraint("rank > 0", name="ck_prize_payouts_rank_positive"),
        CheckConstraint("retry_count >= 0", name="ck_prize_payouts_retry_count_non_negative"),
        Index("ix_prize_payouts_pool_status", "prize_pool_id", "status"),
    )

    prize_pool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prize_pools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("participants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR", nullable=False)

    status: Mapped[PrizePayoutStatus] = mapped_column(
        Enum(PrizePayoutStatus, name="prize_payout_status"),
        default=PrizePayoutStatus.PENDING,
        nullable=False,
        index=True,
    )

    wallet_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wallet_transactions.id", ondelete="SET NULL"), nullable=True
    )

    failure_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    performed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    prize_pool: Mapped["PrizePool"] = relationship(back_populates="payouts", lazy="selectin")
    tournament: Mapped["Tournament"] = relationship(lazy="selectin")  # noqa: F821
    participant: Mapped["Participant"] = relationship(lazy="selectin")  # noqa: F821
    user: Mapped["User"] = relationship(foreign_keys=[user_id], lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<PrizePayout id={self.id} prize_pool_id={self.prize_pool_id} "
            f"rank={self.rank} amount={self.amount} status={self.status}>"
        )
