"""
Repository layer for Leaderboards, Rankings & Statistics — Phase 14.
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.leaderboard import (
    LeaderboardPeriodType,
    LeaderboardSourceEvent,
    LeaderboardUpdateLog,
    PlayerPeriodStats,
    PlayerStatistics,
    RankHistory,
    RankingScope,
    TeamPeriodStats,
    TeamStatistics,
)
from app.models.user import User
from app.models.team import Team
from app.repositories.base import BaseRepository


def _lock(stmt, session: AsyncSession):
    if session.bind.dialect.name != "sqlite":
        stmt = stmt.with_for_update()
    return stmt


class PlayerStatisticsRepository(BaseRepository[PlayerStatistics]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PlayerStatistics)

    async def get_by_user_id(self, user_id: UUID) -> Optional[PlayerStatistics]:
        stmt = select(PlayerStatistics).where(PlayerStatistics.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_user_id_for_update(self, user_id: UUID) -> Optional[PlayerStatistics]:
        stmt = _lock(select(PlayerStatistics).where(PlayerStatistics.user_id == user_id), self.session)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(self, user_id: UUID) -> PlayerStatistics:
        row = await self.get_by_user_id(user_id)
        if row is not None:
            return row
        return await self.create(user_id=user_id)

    async def top(self, *, skip: int, limit: int) -> Sequence[PlayerStatistics]:
        stmt = (
            select(PlayerStatistics)
            .where(PlayerStatistics.deleted_at.is_(None))
            .order_by(desc(PlayerStatistics.ranking_score), asc(PlayerStatistics.user_id))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_all(self) -> int:
        stmt = select(func.count()).select_from(PlayerStatistics).where(
            PlayerStatistics.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def search_by_name(self, query: str, *, skip: int, limit: int) -> Sequence[PlayerStatistics]:
        stmt = (
            select(PlayerStatistics)
            .join(User, User.id == PlayerStatistics.user_id)
            .where(PlayerStatistics.deleted_at.is_(None), User.full_name.ilike(f"%{query}%"))
            .order_by(desc(PlayerStatistics.ranking_score))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_all_ordered(self) -> Sequence[PlayerStatistics]:
        stmt = (
            select(PlayerStatistics)
            .where(PlayerStatistics.deleted_at.is_(None))
            .order_by(desc(PlayerStatistics.ranking_score), asc(PlayerStatistics.user_id))
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class TeamStatisticsRepository(BaseRepository[TeamStatistics]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TeamStatistics)

    async def get_by_team_id(self, team_id: UUID) -> Optional[TeamStatistics]:
        stmt = select(TeamStatistics).where(TeamStatistics.team_id == team_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_team_id_for_update(self, team_id: UUID) -> Optional[TeamStatistics]:
        stmt = _lock(select(TeamStatistics).where(TeamStatistics.team_id == team_id), self.session)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(self, team_id: UUID) -> TeamStatistics:
        row = await self.get_by_team_id(team_id)
        if row is not None:
            return row
        return await self.create(team_id=team_id)

    async def top(self, *, skip: int, limit: int) -> Sequence[TeamStatistics]:
        stmt = (
            select(TeamStatistics)
            .where(TeamStatistics.deleted_at.is_(None))
            .order_by(desc(TeamStatistics.ranking_score), asc(TeamStatistics.team_id))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_all(self) -> int:
        stmt = select(func.count()).select_from(TeamStatistics).where(TeamStatistics.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def search_by_name(self, query: str, *, skip: int, limit: int) -> Sequence[TeamStatistics]:
        stmt = (
            select(TeamStatistics)
            .join(Team, Team.id == TeamStatistics.team_id)
            .where(TeamStatistics.deleted_at.is_(None), Team.name.ilike(f"%{query}%"))
            .order_by(desc(TeamStatistics.ranking_score))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_all_ordered(self) -> Sequence[TeamStatistics]:
        stmt = (
            select(TeamStatistics)
            .where(TeamStatistics.deleted_at.is_(None))
            .order_by(desc(TeamStatistics.ranking_score), asc(TeamStatistics.team_id))
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class PlayerPeriodStatsRepository(BaseRepository[PlayerPeriodStats]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PlayerPeriodStats)

    async def get(
        self, user_id: UUID, period_type: LeaderboardPeriodType, period_key: str
    ) -> Optional[PlayerPeriodStats]:
        stmt = select(PlayerPeriodStats).where(
            PlayerPeriodStats.user_id == user_id,
            PlayerPeriodStats.period_type == period_type,
            PlayerPeriodStats.period_key == period_key,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_update(
        self, user_id: UUID, period_type: LeaderboardPeriodType, period_key: str
    ) -> Optional[PlayerPeriodStats]:
        stmt = _lock(
            select(PlayerPeriodStats).where(
                PlayerPeriodStats.user_id == user_id,
                PlayerPeriodStats.period_type == period_type,
                PlayerPeriodStats.period_key == period_key,
            ),
            self.session,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(
        self, user_id: UUID, period_type: LeaderboardPeriodType, period_key: str
    ) -> PlayerPeriodStats:
        row = await self.get(user_id, period_type, period_key)
        if row is not None:
            return row
        return await self.create(user_id=user_id, period_type=period_type, period_key=period_key)

    async def top(
        self, period_type: LeaderboardPeriodType, period_key: str, *, skip: int, limit: int
    ) -> Sequence[PlayerPeriodStats]:
        stmt = (
            select(PlayerPeriodStats)
            .where(
                PlayerPeriodStats.period_type == period_type,
                PlayerPeriodStats.period_key == period_key,
                PlayerPeriodStats.deleted_at.is_(None),
            )
            .order_by(desc(PlayerPeriodStats.ranking_score), asc(PlayerPeriodStats.user_id))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self, period_type: LeaderboardPeriodType, period_key: str) -> int:
        stmt = select(func.count()).select_from(PlayerPeriodStats).where(
            PlayerPeriodStats.period_type == period_type,
            PlayerPeriodStats.period_key == period_key,
            PlayerPeriodStats.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_for_period_ordered(
        self, period_type: LeaderboardPeriodType, period_key: str
    ) -> Sequence[PlayerPeriodStats]:
        stmt = (
            select(PlayerPeriodStats)
            .where(
                PlayerPeriodStats.period_type == period_type,
                PlayerPeriodStats.period_key == period_key,
                PlayerPeriodStats.deleted_at.is_(None),
            )
            .order_by(desc(PlayerPeriodStats.ranking_score), asc(PlayerPeriodStats.user_id))
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class TeamPeriodStatsRepository(BaseRepository[TeamPeriodStats]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TeamPeriodStats)

    async def get(
        self, team_id: UUID, period_type: LeaderboardPeriodType, period_key: str
    ) -> Optional[TeamPeriodStats]:
        stmt = select(TeamPeriodStats).where(
            TeamPeriodStats.team_id == team_id,
            TeamPeriodStats.period_type == period_type,
            TeamPeriodStats.period_key == period_key,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_update(
        self, team_id: UUID, period_type: LeaderboardPeriodType, period_key: str
    ) -> Optional[TeamPeriodStats]:
        stmt = _lock(
            select(TeamPeriodStats).where(
                TeamPeriodStats.team_id == team_id,
                TeamPeriodStats.period_type == period_type,
                TeamPeriodStats.period_key == period_key,
            ),
            self.session,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(
        self, team_id: UUID, period_type: LeaderboardPeriodType, period_key: str
    ) -> TeamPeriodStats:
        row = await self.get(team_id, period_type, period_key)
        if row is not None:
            return row
        return await self.create(team_id=team_id, period_type=period_type, period_key=period_key)

    async def top(
        self, period_type: LeaderboardPeriodType, period_key: str, *, skip: int, limit: int
    ) -> Sequence[TeamPeriodStats]:
        stmt = (
            select(TeamPeriodStats)
            .where(
                TeamPeriodStats.period_type == period_type,
                TeamPeriodStats.period_key == period_key,
                TeamPeriodStats.deleted_at.is_(None),
            )
            .order_by(desc(TeamPeriodStats.ranking_score), asc(TeamPeriodStats.team_id))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count(self, period_type: LeaderboardPeriodType, period_key: str) -> int:
        stmt = select(func.count()).select_from(TeamPeriodStats).where(
            TeamPeriodStats.period_type == period_type,
            TeamPeriodStats.period_key == period_key,
            TeamPeriodStats.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())


class RankHistoryRepository(BaseRepository[RankHistory]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RankHistory)

    async def list_for_entity(
        self, scope: RankingScope, entity_id: UUID, *, skip: int = 0, limit: int = 50
    ) -> Sequence[RankHistory]:
        stmt = (
            select(RankHistory)
            .where(RankHistory.scope == scope, RankHistory.entity_id == entity_id)
            .order_by(desc(RankHistory.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class LeaderboardUpdateLogRepository(BaseRepository[LeaderboardUpdateLog]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, LeaderboardUpdateLog)

    async def exists(self, source_event: LeaderboardSourceEvent, source_id: str) -> bool:
        stmt = select(func.count()).select_from(LeaderboardUpdateLog).where(
            LeaderboardUpdateLog.source_event == source_event,
            LeaderboardUpdateLog.source_id == source_id,
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one()) > 0

    async def mark(
        self, source_event: LeaderboardSourceEvent, source_id: str, detail: Optional[str] = None
    ) -> LeaderboardUpdateLog:
        return await self.create(source_event=source_event, source_id=source_id, detail=detail)
