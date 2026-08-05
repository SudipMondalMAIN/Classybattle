"""
TournamentWinner repository — Match Result & Winner Management System (Phase 11).
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tournament_winner import TournamentWinner
from app.repositories.base import BaseRepository

_SORTABLE_FIELDS = {
    "created_at": TournamentWinner.created_at,
    "rank": TournamentWinner.rank,
    "declared_at": TournamentWinner.declared_at,
}


class TournamentWinnerRepository(BaseRepository[TournamentWinner]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TournamentWinner)

    async def list_for_tournament(self, tournament_id: UUID) -> Sequence[TournamentWinner]:
        stmt = (
            select(TournamentWinner)
            .where(TournamentWinner.tournament_id == tournament_id, TournamentWinner.deleted_at.is_(None))
            .order_by(TournamentWinner.rank.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_match_and_rank(self, tournament_id: UUID, rank: int) -> Sequence[TournamentWinner]:
        stmt = select(TournamentWinner).where(
            TournamentWinner.tournament_id == tournament_id,
            TournamentWinner.rank == rank,
            TournamentWinner.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_match_and_team(self, tournament_id: UUID, team_id: UUID) -> Optional[TournamentWinner]:
        stmt = select(TournamentWinner).where(
            TournamentWinner.tournament_id == tournament_id,
            TournamentWinner.team_id == team_id,
            TournamentWinner.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_match_and_participant(
        self, tournament_id: UUID, participant_id: UUID
    ) -> Optional[TournamentWinner]:
        stmt = select(TournamentWinner).where(
            TournamentWinner.tournament_id == tournament_id,
            TournamentWinner.participant_id == participant_id,
            TournamentWinner.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_all_for_match(self, tournament_id: UUID) -> None:
        winners = await self.list_for_tournament(tournament_id)
        for w in winners:
            await self.soft_delete(w)

    async def list_paginated(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        tournament_id: Optional[UUID] = None,
        sort_by: str = "rank",
        sort_order: str = "asc",
    ) -> tuple[Sequence[TournamentWinner], int]:
        conditions = [TournamentWinner.deleted_at.is_(None)]
        if tournament_id is not None:
            conditions.append(TournamentWinner.tournament_id == tournament_id)

        count_stmt = select(func.count(TournamentWinner.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _SORTABLE_FIELDS.get(sort_by, TournamentWinner.rank)
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(TournamentWinner)
            .where(*conditions)
            .order_by(order_fn(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total
