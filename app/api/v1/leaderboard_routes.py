"""
Leaderboards, Rankings & Player/Team Statistics API routes — Phase 14.
"""
import math
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import require_admin
from app.models.leaderboard import LeaderboardPeriodType, RankingScope
from app.models.user import User
from app.schemas.leaderboard import (
    PaginatedPlayerPeriodStats,
    PaginatedPlayerStatistics,
    PaginatedRankHistory,
    PaginatedTeamPeriodStats,
    PaginatedTeamStatistics,
    PlayerStatisticsRead,
    TeamStatisticsRead,
)
from app.services.leaderboard_service import LeaderboardService

router = APIRouter(tags=["Leaderboards & Rankings"])


def _pages(total: int, page_size: int) -> int:
    return math.ceil(total / page_size) if total else 0


# ----------------------------------------------------------------------
# Global player / team leaderboards
# ----------------------------------------------------------------------
@router.get("/leaderboard/players/top", response_model=PaginatedPlayerStatistics)
async def top_players(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    service = LeaderboardService(session)
    rows, total = await service.top_players(page=page, page_size=page_size)
    return PaginatedPlayerStatistics(
        items=[PlayerStatisticsRead.model_validate(r) for r in rows],
        total=total, page=page, page_size=page_size, total_pages=_pages(total, page_size),
    )


@router.get("/leaderboard/teams/top", response_model=PaginatedTeamStatistics)
async def top_teams(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    service = LeaderboardService(session)
    rows, total = await service.top_teams(page=page, page_size=page_size)
    return PaginatedTeamStatistics(
        items=[TeamStatisticsRead.model_validate(r) for r in rows],
        total=total, page=page, page_size=page_size, total_pages=_pages(total, page_size),
    )


# ----------------------------------------------------------------------
# Period leaderboards: daily / weekly / monthly / seasonal
# ----------------------------------------------------------------------
@router.get("/leaderboard/players/period/{period_type}/{period_key}", response_model=PaginatedPlayerPeriodStats)
async def player_period_leaderboard(
    period_type: LeaderboardPeriodType,
    period_key: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    from app.schemas.leaderboard import PlayerPeriodStatsRead

    service = LeaderboardService(session)
    rows, total = await service.period_leaderboard(period_type, period_key, page=page, page_size=page_size)
    return PaginatedPlayerPeriodStats(
        items=[PlayerPeriodStatsRead.model_validate(r) for r in rows],
        total=total, page=page, page_size=page_size, total_pages=_pages(total, page_size),
    )


@router.get("/leaderboard/teams/period/{period_type}/{period_key}", response_model=PaginatedTeamPeriodStats)
async def team_period_leaderboard(
    period_type: LeaderboardPeriodType,
    period_key: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    from app.schemas.leaderboard import TeamPeriodStatsRead

    service = LeaderboardService(session)
    rows, total = await service.team_period_leaderboard(period_type, period_key, page=page, page_size=page_size)
    return PaginatedTeamPeriodStats(
        items=[TeamPeriodStatsRead.model_validate(r) for r in rows],
        total=total, page=page, page_size=page_size, total_pages=_pages(total, page_size),
    )


# ----------------------------------------------------------------------
# Tournament / season rankings
# ----------------------------------------------------------------------
@router.get("/leaderboard/tournaments/{tournament_id}/rankings", response_model=PaginatedPlayerStatistics)
async def tournament_rankings(
    tournament_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    service = LeaderboardService(session)
    rows, total = await service.tournament_player_rankings(tournament_id, page=page, page_size=page_size)
    return PaginatedPlayerStatistics(
        items=[PlayerStatisticsRead.model_validate(r) for r in rows],
        total=total, page=page, page_size=page_size, total_pages=_pages(total, page_size),
    )


@router.get("/leaderboard/seasons/{season_key}/rankings", response_model=PaginatedPlayerPeriodStats)
async def season_rankings(
    season_key: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    from app.schemas.leaderboard import PlayerPeriodStatsRead

    service = LeaderboardService(session)
    rows, total = await service.period_leaderboard(
        LeaderboardPeriodType.SEASONAL, season_key, page=page, page_size=page_size
    )
    return PaginatedPlayerPeriodStats(
        items=[PlayerPeriodStatsRead.model_validate(r) for r in rows],
        total=total, page=page, page_size=page_size, total_pages=_pages(total, page_size),
    )


# ----------------------------------------------------------------------
# Search
# ----------------------------------------------------------------------
@router.get("/leaderboard/players/search", response_model=PaginatedPlayerStatistics)
async def search_players(
    q: str = Query(..., min_length=1, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    service = LeaderboardService(session)
    rows, total = await service.search_players(q, page=page, page_size=page_size)
    return PaginatedPlayerStatistics(
        items=[PlayerStatisticsRead.model_validate(r) for r in rows],
        total=total, page=page, page_size=page_size, total_pages=_pages(total, page_size),
    )


@router.get("/leaderboard/teams/search", response_model=PaginatedTeamStatistics)
async def search_teams(
    q: str = Query(..., min_length=1, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    service = LeaderboardService(session)
    rows, total = await service.search_teams(q, page=page, page_size=page_size)
    return PaginatedTeamStatistics(
        items=[TeamStatisticsRead.model_validate(r) for r in rows],
        total=total, page=page, page_size=page_size, total_pages=_pages(total, page_size),
    )


# ----------------------------------------------------------------------
# Individual player / team statistics
# ----------------------------------------------------------------------
@router.get("/players/{user_id}/statistics", response_model=PlayerStatisticsRead)
async def get_player_statistics(user_id: UUID, session: AsyncSession = Depends(get_db_session)):
    service = LeaderboardService(session)
    stats = await service.get_player_statistics(user_id)
    return PlayerStatisticsRead.model_validate(stats)


@router.get("/teams/{team_id}/statistics", response_model=TeamStatisticsRead)
async def get_team_statistics(team_id: UUID, session: AsyncSession = Depends(get_db_session)):
    service = LeaderboardService(session)
    stats = await service.get_team_statistics(team_id)
    return TeamStatisticsRead.model_validate(stats)


# ----------------------------------------------------------------------
# Rank history / rank change tracking
# ----------------------------------------------------------------------
@router.get("/players/{user_id}/rank-history", response_model=PaginatedRankHistory)
async def get_player_rank_history(
    user_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    from app.schemas.leaderboard import RankHistoryRead

    service = LeaderboardService(session)
    rows = await service.get_rank_history(RankingScope.GLOBAL_PLAYER, user_id, page=page, page_size=page_size)
    items = [RankHistoryRead.model_validate(r) for r in rows]
    return PaginatedRankHistory(items=items, total=len(items), page=page, page_size=page_size, total_pages=1)


@router.get("/teams/{team_id}/rank-history", response_model=PaginatedRankHistory)
async def get_team_rank_history(
    team_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    from app.schemas.leaderboard import RankHistoryRead

    service = LeaderboardService(session)
    rows = await service.get_rank_history(RankingScope.GLOBAL_TEAM, team_id, page=page, page_size=page_size)
    items = [RankHistoryRead.model_validate(r) for r in rows]
    return PaginatedRankHistory(items=items, total=len(items), page=page, page_size=page_size, total_pages=1)


# ----------------------------------------------------------------------
# Admin: manual ranking recompute
# ----------------------------------------------------------------------
@router.post("/admin/leaderboard/recompute-ranks")
async def admin_recompute_ranks(
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = LeaderboardService(session)
    await service.recompute_global_ranks()
    return {"success": True, "message": "Global player/team ranks recomputed"}


@router.post("/admin/leaderboard/recompute-period-ranks")
async def admin_recompute_period_ranks(
    period_type: LeaderboardPeriodType,
    period_key: str,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = LeaderboardService(session)
    await service.recompute_period_ranks(period_type, period_key)
    return {"success": True, "message": f"{period_type.value} ranks recomputed for {period_key}"}
