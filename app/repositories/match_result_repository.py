"""
MatchResult repository — Match Result & Winner Management System (Phase 11).
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.match_result import MatchResult, MatchResultStatus
from app.repositories.base import BaseRepository

_SORTABLE_FIELDS = {
    "created_at": MatchResult.created_at,
    "updated_at": MatchResult.updated_at,
    "status": MatchResult.status,
    "submitted_at": MatchResult.submitted_at,
    "approved_at": MatchResult.approved_at,
}


class MatchResultRepository(BaseRepository[MatchResult]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, MatchResult)

    async def get_by_match_id(
        self, match_id: UUID, include_deleted: bool = False
    ) -> Optional[MatchResult]:
        stmt = select(MatchResult).where(MatchResult.match_id == match_id)
        if not include_deleted:
            stmt = stmt.where(MatchResult.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, id_: UUID) -> Optional[MatchResult]:
        stmt = select(MatchResult).where(MatchResult.id == id_, MatchResult.deleted_at.is_(None))
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
        match_id: Optional[UUID] = None,
        status: Optional[MatchResultStatus] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[MatchResult], int]:
        conditions = [MatchResult.deleted_at.is_(None)]
        if tournament_id is not None:
            conditions.append(MatchResult.tournament_id == tournament_id)
        if match_id is not None:
            conditions.append(MatchResult.match_id == match_id)
        if status is not None:
            conditions.append(MatchResult.status == status)

        count_stmt = select(func.count(MatchResult.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _SORTABLE_FIELDS.get(sort_by, MatchResult.created_at)
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(MatchResult)
            .where(*conditions)
            .order_by(order_fn(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total
