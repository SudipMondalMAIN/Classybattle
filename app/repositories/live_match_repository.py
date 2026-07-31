"""
Repositories for the Live Match & Real-Time Tournament System (Phase 12).
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.live_match import (
    LiveMatch,
    LiveMatchEvent,
    LiveMatchEventType,
    LiveMatchScore,
    LiveMatchStatus,
    LiveTournamentState,
)
from app.repositories.base import BaseRepository

_EVENT_SORTABLE = {
    "created_at": LiveMatchEvent.created_at,
    "sequence": LiveMatchEvent.sequence,
    "event_type": LiveMatchEvent.event_type,
}


class LiveMatchRepository(BaseRepository[LiveMatch]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, LiveMatch)

    async def get_by_match_id(
        self, match_id: UUID, *, with_lock: bool = False
    ) -> Optional[LiveMatch]:
        stmt = select(LiveMatch).where(LiveMatch.match_id == match_id)
        if with_lock:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(
        self,
        *,
        tournament_id: Optional[UUID] = None,
        game_id: Optional[UUID] = None,  # reserved for future filtering
        page: int = 1,
        page_size: int = 20,
        sort_order: str = "desc",
    ) -> tuple[Sequence[LiveMatch], int]:
        conditions = [
            LiveMatch.status.in_([LiveMatchStatus.LIVE, LiveMatchStatus.PAUSED]),
            LiveMatch.deleted_at.is_(None),
        ]
        if tournament_id is not None:
            conditions.append(LiveMatch.tournament_id == tournament_id)

        count_stmt = select(func.count(LiveMatch.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        order_fn = desc if sort_order.lower() == "desc" else asc
        stmt = (
            select(LiveMatch)
            .where(*conditions)
            .order_by(order_fn(LiveMatch.started_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total


class LiveMatchEventRepository(BaseRepository[LiveMatchEvent]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, LiveMatchEvent)

    async def next_sequence(self, match_id: UUID) -> int:
        stmt = select(func.max(LiveMatchEvent.sequence)).where(
            LiveMatchEvent.match_id == match_id
        )
        current_max = (await self.session.execute(stmt)).scalar_one()
        return (current_max or 0) + 1

    async def get_by_client_event_id(
        self, match_id: UUID, client_event_id: str
    ) -> Optional[LiveMatchEvent]:
        stmt = select(LiveMatchEvent).where(
            LiveMatchEvent.match_id == match_id,
            LiveMatchEvent.client_event_id == client_event_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_match(
        self,
        match_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        event_type: Optional[LiveMatchEventType] = None,
        round_number: Optional[int] = None,
        sort_by: str = "sequence",
        sort_order: str = "desc",
    ) -> tuple[Sequence[LiveMatchEvent], int]:
        conditions = [LiveMatchEvent.match_id == match_id]
        if event_type is not None:
            conditions.append(LiveMatchEvent.event_type == event_type)
        if round_number is not None:
            conditions.append(LiveMatchEvent.round_number == round_number)

        count_stmt = select(func.count(LiveMatchEvent.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _EVENT_SORTABLE.get(sort_by, LiveMatchEvent.sequence)
        order_fn = desc if sort_order.lower() == "desc" else asc

        stmt = (
            select(LiveMatchEvent)
            .where(*conditions)
            .order_by(order_fn(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total


class LiveMatchScoreRepository(BaseRepository[LiveMatchScore]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, LiveMatchScore)

    async def get_by_team(self, match_id: UUID, team_id: UUID) -> Optional[LiveMatchScore]:
        stmt = select(LiveMatchScore).where(
            LiveMatchScore.match_id == match_id, LiveMatchScore.team_id == team_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_participant(
        self, match_id: UUID, participant_id: UUID
    ) -> Optional[LiveMatchScore]:
        stmt = select(LiveMatchScore).where(
            LiveMatchScore.match_id == match_id,
            LiveMatchScore.participant_id == participant_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def leaderboard(
        self, match_id: UUID, *, page: int = 1, page_size: int = 50
    ) -> tuple[Sequence[LiveMatchScore], int]:
        conditions = [LiveMatchScore.match_id == match_id]
        count_stmt = select(func.count(LiveMatchScore.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            select(LiveMatchScore)
            .where(*conditions)
            .order_by(desc(LiveMatchScore.score), desc(LiveMatchScore.kills))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def list_all_for_match(self, match_id: UUID) -> Sequence[LiveMatchScore]:
        stmt = (
            select(LiveMatchScore)
            .where(LiveMatchScore.match_id == match_id)
            .order_by(desc(LiveMatchScore.score), desc(LiveMatchScore.kills))
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class LiveTournamentRepository(BaseRepository[LiveTournamentState]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, LiveTournamentState)

    async def get_by_tournament_id(
        self, tournament_id: UUID, *, with_lock: bool = False
    ) -> Optional[LiveTournamentState]:
        stmt = select(LiveTournamentState).where(
            LiveTournamentState.tournament_id == tournament_id
        )
        if with_lock:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
