"""
MatchWinner repository — Match Result & Winner Management System (Phase 11).
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.match_winner import MatchWinner
from app.repositories.base import BaseRepository

_SORTABLE_FIELDS = {
    "created_at": MatchWinner.created_at,
    "rank": MatchWinner.rank,
    "declared_at": MatchWinner.declared_at,
}


class MatchWinnerRepository(BaseRepository[MatchWinner]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, MatchWinner)

    async def list_for_match(self, match_id: UUID) -> Sequence[MatchWinner]:
        stmt = (
            select(MatchWinner)
            .where(MatchWinner.match_id == match_id, MatchWinner.deleted_at.is_(None))
            .order_by(MatchWinner.rank.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_match_and_rank(self, match_id: UUID, rank: int) -> Sequence[MatchWinner]:
        stmt = select(MatchWinner).where(
            MatchWinner.match_id == match_id,
            MatchWinner.rank == rank,
            MatchWinner.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_match_and_team(self, match_id: UUID, team_id: UUID) -> Optional[MatchWinner]:
        stmt = select(MatchWinner).where(
            MatchWinner.match_id == match_id,
            MatchWinner.team_id == team_id,
            MatchWinner.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_match_and_participant(
        self, match_id: UUID, participant_id: UUID
    ) -> Optional[MatchWinner]:
        stmt = select(MatchWinner).where(
            MatchWinner.match_id == match_id,
            MatchWinner.participant_id == participant_id,
            MatchWinner.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_all_for_match(self, match_id: UUID) -> None:
        winners = await self.list_for_match(match_id)
        for w in winners:
            await self.soft_delete(w)

    async def list_paginated(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        tournament_id: Optional[UUID] = None,
        match_id: Optional[UUID] = None,
        sort_by: str = "rank",
        sort_order: str = "asc",
    ) -> tuple[Sequence[MatchWinner], int]:
        conditions = [MatchWinner.deleted_at.is_(None)]
        if tournament_id is not None:
            conditions.append(MatchWinner.tournament_id == tournament_id)
        if match_id is not None:
            conditions.append(MatchWinner.match_id == match_id)

        count_stmt = select(func.count(MatchWinner.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _SORTABLE_FIELDS.get(sort_by, MatchWinner.rank)
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(MatchWinner)
            .where(*conditions)
            .order_by(order_fn(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total
