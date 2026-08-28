"""
Referral System models — v2.

Three tables:

- ReferralConfig: single global row, fully admin-configurable (reward
  amount, min deposit to qualify, which steps are required, apply
  window, fraud thresholds, milestone ladder). Read through
  ReferralService's cache -- never read raw by callers outside that
  service.

- Referral: one row per (referrer, referee) pair -- a referee can only
  ever apply ONE referral code, ever (uq on referee_id), so this is
  also the "has this user already used a code" check. Tracks step
  progress (deposit_met / tournament_met) independently so toggling a
  step's requirement in ReferralConfig doesn't require touching this
  row -- ReferralService decides whether a step counts as "satisfied"
  by checking the *current* config at completion-check time.

- ReferralMilestoneClaim: one row per (referrer, threshold) that has
  already been paid out, so re-evaluating a referrer's completed-count
  after every new completion never double-pays a milestone bonus.
"""
import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel
from app.database.types import PortableJSONB, str_enum

# Default milestone ladder -- admin-editable afterwards via
# ReferralConfig.milestone_rules. List of {"threshold": int, "bonus": str}.
DEFAULT_MILESTONE_RULES = [
    {"threshold": 10, "bonus": "10"},
    {"threshold": 20, "bonus": "10"},
    {"threshold": 30, "bonus": "10"},
    {"threshold": 40, "bonus": "10"},
    {"threshold": 50, "bonus": "30"},
    {"threshold": 100, "bonus": "50"},
]


class ReferralStatus(str, enum.Enum):
    # Applied, still waiting on deposit/tournament steps.
    PENDING = "pending"
    # Steps complete, but a fraud check (IP/device) flagged it -- needs
    # admin approval before the reward is credited.
    ON_HOLD = "on_hold"
    # Reward credited.
    COMPLETED = "completed"
    # Admin rejected an ON_HOLD referral -- terminal, never re-evaluated.
    REJECTED = "rejected"


class ReferralConfig(BaseModel):
    """Single global row. Admin panel reads/writes this through
    ReferralService, which caches it (see app/core/cache.py) so the hot
    paths -- every deposit settle & every tournament join -- don't hit
    Postgres for config on every request."""

    __tablename__ = "referral_config"

    reward_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("10"), server_default="10", nullable=False
    )
    min_deposit_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("20"), server_default="20", nullable=False
    )

    # Step toggles. Disabled = that step is skipped entirely (referee
    # doesn't need to complete it, reward still pays once the remaining
    # enabled steps are done). Enabled = must actually be completed.
    require_deposit_step: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    require_paid_tournament_step: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    # Referee has this many days from their OWN signup (User.created_at)
    # to apply a referral code. After that the apply screen/endpoint
    # stops accepting a code for that user.
    apply_window_days: Mapped[int] = mapped_column(
        Integer, default=30, server_default="30", nullable=False
    )

    fraud_check_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    # Max number of *eligible* (non-rejected) referred accounts allowed
    # from the same signup/apply IP before new ones get flagged ON_HOLD.
    max_accounts_per_ip: Mapped[int] = mapped_column(
        Integer, default=5, server_default="5", nullable=False
    )

    # [{"threshold": 10, "bonus": "10"}, ...] -- sorted ascending by
    # threshold. Admin-editable list of milestone-bonus tiers; every
    # threshold at or below a referrer's completed-referral count that
    # hasn't been claimed yet (see ReferralMilestoneClaim) gets paid.
    milestone_rules: Mapped[list] = mapped_column(
        PortableJSONB, default=list, server_default="[]", nullable=False
    )

    def __repr__(self) -> str:
        return f"<ReferralConfig reward={self.reward_amount} min_deposit={self.min_deposit_amount}>"


class Referral(BaseModel):
    """One row per referee -- created when a user applies someone else's
    referral code. A user can apply at most one code, ever (uq on
    referee_id)."""

    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("referee_id", name="uq_referrals_referee_id"),
        Index("ix_referrals_referrer_status", "referrer_id", "status"),
        Index("ix_referrals_ip", "ip_address"),
        Index("ix_referrals_device", "device_id"),
    )

    referrer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    referee_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code_used: Mapped[str] = mapped_column(String(16), nullable=False)

    status: Mapped[ReferralStatus] = mapped_column(
        str_enum(ReferralStatus, "referral_status"),
        default=ReferralStatus.PENDING,
        server_default=ReferralStatus.PENDING.value,
        nullable=False,
        index=True,
    )

    # Step progress -- evaluated against the step's *current*
    # requiredness in ReferralConfig at check time, not baked in here.
    deposit_met: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    deposit_met_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    tournament_met: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    tournament_met_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Captured at apply-time, used for the IP/device fraud checks.
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    device_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    risk_flagged: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    risk_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Snapshot of the reward actually paid (config's reward_amount at
    # the moment of crediting), so a later config change never rewrites
    # history.
    reward_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    reward_credited: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    credited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    wallet_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("wallet_transactions.id", ondelete="SET NULL"), nullable=True
    )

    reviewed_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    admin_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    referrer: Mapped["User"] = relationship(  # noqa: F821
        foreign_keys=[referrer_id], lazy="selectin"
    )
    referee: Mapped["User"] = relationship(  # noqa: F821
        foreign_keys=[referee_id], lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Referral id={self.id} referrer={self.referrer_id} referee={self.referee_id} status={self.status}>"


class ReferralMilestoneClaim(BaseModel):
    """One row per (referrer, threshold) milestone already paid --
    prevents double-crediting a milestone bonus when completed-count is
    re-evaluated on every new completion."""

    __tablename__ = "referral_milestone_claims"
    __table_args__ = (
        UniqueConstraint("referrer_id", "threshold", name="uq_referral_milestone_referrer_threshold"),
    )

    referrer_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    bonus_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    wallet_transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("wallet_transactions.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<ReferralMilestoneClaim referrer={self.referrer_id} threshold={self.threshold}>"
