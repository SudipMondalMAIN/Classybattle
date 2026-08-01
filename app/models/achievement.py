"""
Achievement, Badge & UserAchievement models — Phase 15C (Achievements &
Moderation).

Design mirrors the existing Notification/LeaderboardUpdateLog patterns:
- `Achievement` rows are admin-managed definitions ("Win 10 tournaments",
  "Reach top-10 global rank", ...), each pointing at one `Badge` (the
  visual reward) and carrying a `trigger_type` + `threshold` used by
  AchievementService to decide when to unlock it automatically.
- `Badge` is the reusable visual/reward artifact — multiple achievements
  may reference different badges, or share one for a "tier" (bronze /
  silver / gold) of the same badge family.
- `UserAchievement` is the append-style unlock history: one row per
  (user, achievement) the moment it is unlocked, guarded by a unique
  constraint so the same achievement can never be double-unlocked for a
  user even under concurrent/retried trigger evaluation (same
  idempotency approach as Notification.event_key).
"""
import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel
from app.database.types import PortableJSONB


class BadgeTier(str, enum.Enum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


class AchievementTriggerType(str, enum.Enum):
    """What automatic event evaluates an achievement's unlock condition."""

    TOURNAMENT_WIN = "tournament_win"
    TOURNAMENT_PARTICIPATION = "tournament_participation"
    MATCH_WIN = "match_win"
    MVP = "mvp"
    RANKING = "ranking"
    WALLET_MILESTONE = "wallet_milestone"
    PRIZE_MILESTONE = "prize_milestone"


class AchievementComparison(str, enum.Enum):
    """How `metric_value` is compared against `Achievement.threshold`.

    GTE is used for cumulative counters (wins, participations, wallet
    balance, prize earned) — unlock once the metric reaches the
    threshold. LTE is used for RANKING, where a *lower* rank number is
    better (e.g. "reach rank 10 or better" -> current_rank <= 10).
    """

    GTE = "gte"
    LTE = "lte"


class Badge(BaseModel):
    __tablename__ = "badges"

    name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    icon_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    tier: Mapped[BadgeTier] = mapped_column(
        Enum(BadgeTier, name="badge_tier"), default=BadgeTier.BRONZE, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    achievements: Mapped[list["Achievement"]] = relationship(
        back_populates="badge", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Badge id={self.id} name={self.name}>"


class Achievement(BaseModel):
    __tablename__ = "achievements"
    __table_args__ = (
        UniqueConstraint("code", name="uq_achievements_code"),
    )

    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    badge_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("badges.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trigger_type: Mapped[AchievementTriggerType] = mapped_column(
        Enum(AchievementTriggerType, name="achievement_trigger_type"), nullable=False, index=True
    )
    comparison: Mapped[AchievementComparison] = mapped_column(
        Enum(AchievementComparison, name="achievement_comparison"),
        default=AchievementComparison.GTE,
        nullable=False,
    )
    threshold: Mapped[Numeric] = mapped_column(Numeric(18, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    badge: Mapped["Badge"] = relationship(back_populates="achievements", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Achievement id={self.id} code={self.code} trigger={self.trigger_type}>"


class UserAchievement(BaseModel):
    """Append-style unlock history — one row per unlocked achievement."""

    __tablename__ = "user_achievements"
    __table_args__ = (
        UniqueConstraint("user_id", "achievement_id", name="uq_user_achievements_user_achievement"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    achievement_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unlocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metric_value: Mapped[Optional[Numeric]] = mapped_column(Numeric(18, 2), nullable=True)
    meta_data: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)

    achievement: Mapped["Achievement"] = relationship(lazy="selectin")

    def __repr__(self) -> str:
        return f"<UserAchievement user_id={self.user_id} achievement_id={self.achievement_id}>"
