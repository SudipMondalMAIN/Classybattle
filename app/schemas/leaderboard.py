"""
Leaderboard, Ranking & Statistics Pydantic schemas — Phase 14.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.leaderboard import LeaderboardPeriodType, RankingScope


class PlayerStatisticsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    matches_played: int
    matches_won: int
    matches_lost: int
    win_rate: float
    kills: int
    deaths: int
    kd_ratio: float
    assists: int
    mvp_count: int
    tournaments_played: int
    tournaments_won: int
    prize_money_earned: Decimal
    wallet_earnings: Decimal
    ranking_score: Decimal
    current_rank: Optional[int] = None
    previous_rank: Optional[int] = None
    updated_at: datetime


class TeamStatisticsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    matches_played: int
    matches_won: int
    matches_lost: int
    win_rate: float
    tournaments_played: int
    tournaments_won: int
    average_placement: float
    prize_money_earned: Decimal
    ranking_score: Decimal
    current_rank: Optional[int] = None
    previous_rank: Optional[int] = None
    updated_at: datetime


class PlayerPeriodStatsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    period_type: LeaderboardPeriodType
    period_key: str
    matches_played: int
    matches_won: int
    kills: int
    deaths: int
    assists: int
    mvp_count: int
    prize_money_earned: Decimal
    ranking_score: Decimal
    current_rank: Optional[int] = None


class TeamPeriodStatsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    period_type: LeaderboardPeriodType
    period_key: str
    matches_played: int
    matches_won: int
    prize_money_earned: Decimal
    ranking_score: Decimal
    current_rank: Optional[int] = None


class RankHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scope: RankingScope
    entity_id: UUID
    user_id: Optional[UUID] = None
    team_id: Optional[UUID] = None
    tournament_id: Optional[UUID] = None
    old_rank: Optional[int] = None
    new_rank: Optional[int] = None
    ranking_score: Decimal
    source_event: str
    created_at: datetime


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int


class PaginatedPlayerStatistics(PaginatedResponse):
    items: list[PlayerStatisticsRead]


class PaginatedTeamStatistics(PaginatedResponse):
    items: list[TeamStatisticsRead]


class PaginatedPlayerPeriodStats(PaginatedResponse):
    items: list[PlayerPeriodStatsRead]


class PaginatedTeamPeriodStats(PaginatedResponse):
    items: list[TeamPeriodStatsRead]


class PaginatedRankHistory(PaginatedResponse):
    items: list[RankHistoryRead]
