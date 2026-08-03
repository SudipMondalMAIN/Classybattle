"""
Match repository — queries specific to Room Management & Match Lifecycle (Phase 7).
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.match import Match, MatchStatus
from app.repositories.base import BaseRepository

_SORTABLE_FIELDS = {
    "created_at": Match.created_at,
    "scheduled_start": Match.scheduled_start,
    "round_number": Match.round_number,
    "match_number": Match.match_number,
    "match_status": Match.match_status,
}


class MatchRepository(BaseRepository[Match]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Match)

    async def get_by_uid(self, match_uid: str, include_deleted: bool = False) -> Optional[Match]:
        stmt = select(Match).where(Match.match_uid == match_uid)
        if not include_deleted:
            stmt = stmt.where(Match.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_short_id(
        self, short_id: int, include_deleted: bool = False
    ) -> Optional[Match]:
        stmt = select(Match).where(Match.short_id == short_id)
        if not include_deleted:
            stmt = stmt.where(Match.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def exists_round_match_number(
        self,
        tournament_id: UUID,
        round_number: int,
        match_number: int,
        exclude_match_id: Optional[UUID] = None,
    ) -> bool:
        stmt = select(Match.id).where(
            Match.tournament_id == tournament_id,
            Match.round_number == round_number,
            Match.match_number == match_number,
            Match.deleted_at.is_(None),
        )
        if exclude_match_id is not None:
            stmt = stmt.where(Match.id != exclude_match_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_for_tournament(
        self,
        tournament_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        round_number: Optional[int] = None,
        match_status: Optional[MatchStatus] = None,
        sort_by: str = "round_number",
        sort_order: str = "asc",
        include_deleted: bool = False,
    ) -> tuple[Sequence[Match], int]:
        conditions = [Match.tournament_id == tournament_id]
        if not include_deleted:
            conditions.append(Match.deleted_at.is_(None))
        if round_number is not None:
            conditions.append(Match.round_number == round_number)
        if match_status is not None:
            conditions.append(Match.match_status == match_status)

        count_stmt = select(func.count(Match.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _SORTABLE_FIELDS.get(sort_by, Match.round_number)
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(Match)
            .where(*conditions)
            .order_by(order_fn(sort_column), asc(Match.match_number))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def list_for_tournament_on_date(
        self, tournament_id: UUID, target_date
    ) -> Sequence[Match]:
        """All slots (Matches) already generated for a recurring schedule
        on a given calendar date, ordered by start time."""
        stmt = (
            select(Match)
            .where(
                Match.tournament_id == tournament_id,
                func.date(Match.scheduled_start) == target_date,
                Match.deleted_at.is_(None),
            )
            .order_by(asc(Match.scheduled_start))
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def next_match_number(self, tournament_id: UUID, round_number: int) -> int:
        stmt = select(func.max(Match.match_number)).where(
            Match.tournament_id == tournament_id,
            Match.round_number == round_number,
        )
        result = await self.session.execute(stmt)
        current_max = result.scalar_one()
        return (current_max or 0) + 1
