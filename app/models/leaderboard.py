"""
Leaderboard, Ranking & Player/Team Statistics models — Phase 14.

Design mirrors the Wallet/WalletTransaction pattern used in Phase 8:
- PlayerStatistics / TeamStatistics are single mutable "current state"
  rows (one per user / team) holding all-time aggregate counters plus
  the currently computed rank, updated in place by LeaderboardService.
- PlayerPeriodStats / TeamPeriodStats hold the same counters scoped to
  a rolling period (daily/weekly/monthly/seasonal) identified by a
  deterministic `period_key` (e.g. "2026-08-01", "2026-W31", "2026-08",
  "2026-S1"), so Daily/Weekly/Monthly/Seasonal leaderboards can be
  served directly from a single indexed table without recomputing from
  raw match history on every request.
- RankHistory is an immutable append-only ledger of rank changes
  (mirrors the AuditLog / WalletTransaction "ledger" pattern) so rank
  history and rank-change tracking are always reconstructible.

All counters are only ever mutated inside LeaderboardService, inside
the same DB transaction as the triggering event (match approval / prize
credit), guarded by idempotency flags on the source rows
(MatchResult.prize_distribution_triggered, PrizePayout uniqueness,
LeaderboardUpdateLog below) so stats/leaderboards can never be double
counted on retries.
"""
import enum
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
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


class LeaderboardPeriodType(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    SEASONAL = "seasonal"
    ALL_TIME = "all_time"


class RankingScope(str, enum.Enum):
    GLOBAL_PLAYER = "global_player"
    GLOBAL_TEAM = "global_team"
    TOURNAMENT_PLAYER = "tournament_player"
    TOURNAMENT_TEAM = "tournament_team"


class LeaderboardSourceEvent(str, enum.Enum):
    """What triggered a statistics/leaderboard mutation — kept for audit
    trail readability alongside the generic AuditService entries."""

    MATCH_COMPLETED = "match_completed"
    WINNER_DECLARED = "winner_declared"
    PRIZE_CREDITED = "prize_credited"
    TOURNAMENT_COMPLETED = "tournament_completed"
    MANUAL_RECOMPUTE = "manual_recompute"


class PlayerStatistics(BaseModel):
    """All-time aggregate statistics + current global rank for one user."""

    __tablename__ = "player_statistics"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_player_statistics_user_id"),
        Index("ix_player_statistics_rank", "current_rank"),
        Index("ix_player_statistics_score", "ranking_score"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    matches_played: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    matches_won: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    matches_lost: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    kills: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    deaths: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    assists: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    mvp_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    tournaments_played: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    tournaments_won: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    prize_money_earned: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=0, server_default="0", nullable=False
    )
    wallet_earnings: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=0, server_default="0", nullable=False
    )

    # Denormalized, precomputed ranking score so leaderboard ORDER BY
    # never needs to recompute win-rate/K-D at query time.
    ranking_score: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), default=0, server_default="0", nullable=False, index=True
    )
    current_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    previous_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    user: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821

    @property
    def win_rate(self) -> float:
        if self.matches_played == 0:
            return 0.0
        return round((self.matches_won / self.matches_played) * 100, 2)

    @property
    def kd_ratio(self) -> float:
        if self.deaths == 0:
            return float(self.kills)
        return round(self.kills / self.deaths, 2)

    def __repr__(self) -> str:
        return f"<PlayerStatistics user_id={self.user_id} rank={self.current_rank}>"


class TeamStatistics(BaseModel):
    """All-time aggregate statistics + current global rank for one team."""

    __tablename__ = "team_statistics"
    __table_args__ = (
        UniqueConstraint("team_id", name="uq_team_statistics_team_id"),
        Index("ix_team_statistics_rank", "current_rank"),
        Index("ix_team_statistics_score", "ranking_score"),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )

    matches_played: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    matches_won: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    matches_lost: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    tournaments_played: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    tournaments_won: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    prize_money_earned: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=0, server_default="0", nullable=False
    )

    # Sum of placements across matches / matches_played, tracked via a
    # running total so the average can be updated in O(1) per match.
    placement_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    ranking_score: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), default=0, server_default="0", nullable=False, index=True
    )
    current_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    previous_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    team: Mapped["Team"] = relationship(lazy="selectin")  # noqa: F821

    @property
    def win_rate(self) -> float:
        if self.matches_played == 0:
            return 0.0
        return round((self.matches_won / self.matches_played) * 100, 2)

    @property
    def average_placement(self) -> float:
        if self.matches_played == 0:
            return 0.0
        return round(self.placement_total / self.matches_played, 2)

    def __repr__(self) -> str:
        return f"<TeamStatistics team_id={self.team_id} rank={self.current_rank}>"


class PlayerPeriodStats(BaseModel):
    """Rolling-period statistics for one user (Daily/Weekly/Monthly/
    Seasonal leaderboards). One row per (user_id, period_type, period_key).
    """

    __tablename__ = "player_period_stats"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "period_type", "period_key", name="uq_player_period_stats_user_period"
        ),
        Index("ix_player_period_stats_lookup", "period_type", "period_key", "ranking_score"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_type: Mapped[LeaderboardPeriodType] = mapped_column(
        String(20), nullable=False, index=True
    )
    period_key: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    matches_played: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    matches_won: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    kills: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    deaths: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    assists: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    mvp_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    prize_money_earned: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=0, server_default="0", nullable=False
    )
    ranking_score: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), default=0, server_default="0", nullable=False
    )
    current_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    user: Mapped["User"] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<PlayerPeriodStats user_id={self.user_id} "
            f"period={self.period_type}:{self.period_key}>"
        )


class TeamPeriodStats(BaseModel):
    """Rolling-period statistics for one team."""

    __tablename__ = "team_period_stats"
    __table_args__ = (
        UniqueConstraint(
            "team_id", "period_type", "period_key", name="uq_team_period_stats_team_period"
        ),
        Index("ix_team_period_stats_lookup", "period_type", "period_key", "ranking_score"),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_type: Mapped[LeaderboardPeriodType] = mapped_column(
        String(20), nullable=False, index=True
    )
    period_key: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    matches_played: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    matches_won: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    prize_money_earned: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=0, server_default="0", nullable=False
    )
    ranking_score: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), default=0, server_default="0", nullable=False
    )
    current_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    team: Mapped["Team"] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<TeamPeriodStats team_id={self.team_id} "
            f"period={self.period_type}:{self.period_key}>"
        )


class RankHistory(BaseModel):
    """Immutable append-only record of a rank change for a player or team,
    within a given scope (global or tournament-specific)."""

    __tablename__ = "rank_history"
    __table_args__ = (
        Index("ix_rank_history_entity", "scope", "entity_id", "created_at"),
        CheckConstraint(
            "(user_id IS NOT NULL) OR (team_id IS NOT NULL)",
            name="ck_rank_history_user_or_team",
        ),
    )

    scope: Mapped[RankingScope] = mapped_column(String(30), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    team_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True
    )
    tournament_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=True, index=True
    )

    old_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    new_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ranking_score: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, server_default="0", nullable=False)
    source_event: Mapped[LeaderboardSourceEvent] = mapped_column(String(30), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<RankHistory scope={self.scope} entity_id={self.entity_id} "
            f"{self.old_rank}->{self.new_rank}>"
        )


class LeaderboardUpdateLog(BaseModel):
    """Idempotency guard: records that a given source event (e.g. one
    MatchResult approval) has already been folded into statistics, so a
    retried trigger can never double-count matches/kills/prize money.
    Mirrors the IdempotencyKey pattern already used for API-level
    idempotency, scoped here to internal domain events."""

    __tablename__ = "leaderboard_update_log"
    __table_args__ = (
        UniqueConstraint(
            "source_event", "source_id", name="uq_leaderboard_update_log_source"
        ),
    )

    source_event: Mapped[LeaderboardSourceEvent] = mapped_column(String(30), nullable=False)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return f"<LeaderboardUpdateLog {self.source_event}:{self.source_id}>"
