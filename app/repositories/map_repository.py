"""
Map repository — queries specific to the Maps module (Phase 4).
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.map import Map
from app.repositories.base import BaseRepository

_SORTABLE_FIELDS = {
    "name": Map.name,
    "created_at": Map.created_at,
    "sort_order": Map.sort_order,
}


class MapRepository(BaseRepository[Map]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Map)

    async def get_by_slug(
        self, game_id: UUID, slug: str, include_deleted: bool = False
    ) -> Optional[Map]:
        stmt = select(Map).where(Map.game_id == game_id, Map.slug == slug)
        if not include_deleted:
            stmt = stmt.where(Map.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def slug_exists(
        self,
        game_id: UUID,
        mode_id: Optional[UUID],
        slug: str,
        exclude_id: Optional[UUID] = None,
    ) -> bool:
        stmt = select(Map.id).where(
            Map.game_id == game_id,
            Map.mode_id == mode_id if mode_id is not None else Map.mode_id.is_(None),
            Map.slug == slug,
            Map.deleted_at.is_(None),
        )
        if exclude_id is not None:
            stmt = stmt.where(Map.id != exclude_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def name_exists(
        self,
        game_id: UUID,
        mode_id: Optional[UUID],
        name: str,
        exclude_id: Optional[UUID] = None,
    ) -> bool:
        """Guards against duplicate map names within the same game/mode."""
        stmt = select(Map.id).where(
            Map.game_id == game_id,
            Map.mode_id == mode_id if mode_id is not None else Map.mode_id.is_(None),
            func.lower(Map.name) == name.lower(),
            Map.deleted_at.is_(None),
        )
        if exclude_id is not None:
            stmt = stmt.where(Map.id != exclude_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_paginated(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        game_id: Optional[UUID] = None,
        mode_id: Optional[UUID] = None,
        is_active: Optional[bool] = None,
        is_featured: Optional[bool] = None,
        search: Optional[str] = None,
        sort_by: str = "sort_order",
        sort_order: str = "asc",
        include_deleted: bool = False,
    ) -> tuple[Sequence[Map], int]:
        conditions = []
        if not include_deleted:
            conditions.append(Map.deleted_at.is_(None))
        if game_id is not None:
            conditions.append(Map.game_id == game_id)
        if mode_id is not None:
            conditions.append(Map.mode_id == mode_id)
        if is_active is not None:
            conditions.append(Map.is_active.is_(is_active))
        if is_featured is not None:
            conditions.append(Map.is_featured.is_(is_featured))
        if search:
            like = f"%{search.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(Map.name).like(like),
                    func.lower(Map.slug).like(like),
                )
            )

        count_stmt = select(func.count(Map.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _SORTABLE_FIELDS.get(sort_by, Map.sort_order)
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(Map)
            .where(*conditions)
            .order_by(order_fn(sort_column), asc(Map.name))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total
