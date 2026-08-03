"""
Tournament repository — queries specific to the Tournament module.
"""
from typing import Optional, Sequence, Union
from uuid import UUID

from sqlalchemy import String, asc, cast, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tournament import Tournament, TournamentStatus, TournamentVisibility
from app.repositories.base import BaseRepository

_SORTABLE_FIELDS = {
    "created_at": Tournament.created_at,
    "tournament_start": Tournament.tournament_start,
    "registration_start": Tournament.registration_start,
    "prize_pool": Tournament.prize_pool,
    "entry_fee": Tournament.entry_fee,
    "title": Tournament.title,
    "current_players": Tournament.current_players,
}


class TournamentRepository(BaseRepository[Tournament]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Tournament)

    async def get_by_slug(self, slug: str, include_deleted: bool = False) -> Optional[Tournament]:
        stmt = select(Tournament).where(Tournament.slug == slug)
        if not include_deleted:
            stmt = stmt.where(Tournament.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_short_id(
        self, short_id: int, include_deleted: bool = False
    ) -> Optional[Tournament]:
        stmt = select(Tournament).where(Tournament.short_id == short_id)
        if not include_deleted:
            stmt = stmt.where(Tournament.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        stmt = select(Tournament.id).where(Tournament.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def title_exists(self, title: str, game_id: UUID) -> bool:
        """Guards against duplicate tournament names within the same game."""
        stmt = select(Tournament.id).where(
            func.lower(Tournament.title) == title.lower(),
            Tournament.game_id == game_id,
            Tournament.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_active_schedule_for_game_category(
        self, game_id: UUID, category
    ) -> Optional[Tournament]:
        """One SOLO schedule + one SQUAD schedule per game (Raj's simplified
        flow) — used to block accidental duplicates on create."""
        stmt = select(Tournament).where(
            Tournament.game_id == game_id,
            Tournament.category == category,
            Tournament.is_recurring_schedule.is_(True),
            Tournament.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active_recurring_schedules(self) -> Sequence[Tournament]:
        """All recurring schedule templates (e.g. 'Free Fire Classic',
        'BGMI Squad') that are currently published/open and should have
        today's slots generated."""
        stmt = select(Tournament).where(
            Tournament.is_recurring_schedule.is_(True),
            Tournament.status.in_(
                [TournamentStatus.PUBLISHED, TournamentStatus.REGISTRATION_OPEN]
            ),
            Tournament.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_paginated(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        game_id: Optional[UUID] = None,
        status: Optional[Union[TournamentStatus, list[TournamentStatus]]] = None,
        visibility: Optional[TournamentVisibility] = None,
        is_featured: Optional[bool] = None,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        include_private: bool = False,
        include_deleted: bool = False,
    ) -> tuple[Sequence[Tournament], int]:
        conditions = []
        if not include_deleted:
            conditions.append(Tournament.deleted_at.is_(None))
        if not include_private:
            conditions.append(Tournament.visibility != TournamentVisibility.PRIVATE)
        if game_id is not None:
            conditions.append(Tournament.game_id == game_id)
        if status is not None:
            if isinstance(status, list):
                conditions.append(Tournament.status.in_(status))
            else:
                conditions.append(Tournament.status == status)
        if visibility is not None:
            conditions.append(Tournament.visibility == visibility)
        if is_featured is not None:
            conditions.append(Tournament.is_featured.is_(is_featured))
        if search:
            q = search.strip()
            like = f"%{q.lower()}%"
            search_conditions = [
                func.lower(Tournament.title).like(like),
                func.lower(cast(Tournament.organizer, String)).like(like),
            ]
            if q.isdigit():
                search_conditions.append(Tournament.short_id == int(q))
            conditions.append(or_(*search_conditions))

        count_stmt = select(func.count(Tournament.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _SORTABLE_FIELDS.get(sort_by, Tournament.created_at)
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(Tournament)
            .where(*conditions)
            .order_by(order_fn(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total
