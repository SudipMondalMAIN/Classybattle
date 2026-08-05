"""
TournamentResult repository — Match Result & Winner Management System (Phase 11).
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tournament_result import TournamentResult, TournamentResultStatus
from app.repositories.base import BaseRepository

_SORTABLE_FIELDS = {
    "created_at": TournamentResult.created_at,
    "updated_at": TournamentResult.updated_at,
    "status": TournamentResult.status,
    "submitted_at": TournamentResult.submitted_at,
    "approved_at": TournamentResult.approved_at,
}


class TournamentResultRepository(BaseRepository[TournamentResult]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TournamentResult)

    async def get_by_match_id(
        self, tournament_id: UUID, include_deleted: bool = False
    ) -> Optional[TournamentResult]:
        stmt = select(TournamentResult).where(TournamentResult.tournament_id == tournament_id)
        if not include_deleted:
            stmt = stmt.where(TournamentResult.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, id_: UUID) -> Optional[TournamentResult]:
        stmt = select(TournamentResult).where(TournamentResult.id == id_, TournamentResult.deleted_at.is_(None))
        if self.session.bind.dialect.name != "sqlite":
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        tournament_id: Optional[UUID] = None,
        status: Optional[TournamentResultStatus] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[TournamentResult], int]:
        conditions = [TournamentResult.deleted_at.is_(None)]
        if tournament_id is not None:
            conditions.append(TournamentResult.tournament_id == tournament_id)
        if status is not None:
            conditions.append(TournamentResult.status == status)

        count_stmt = select(func.count(TournamentResult.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _SORTABLE_FIELDS.get(sort_by, TournamentResult.created_at)
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(TournamentResult)
            .where(*conditions)
            .order_by(order_fn(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total
