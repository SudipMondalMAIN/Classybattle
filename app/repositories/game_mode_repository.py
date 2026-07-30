"""
GameMode repository — queries specific to the Game Modes module (Phase 3).
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game_mode import GameMode
from app.repositories.base import BaseRepository

_SORTABLE_FIELDS = {
    "name": GameMode.name,
    "created_at": GameMode.created_at,
    "sort_order": GameMode.sort_order,
}


class GameModeRepository(BaseRepository[GameMode]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, GameMode)

    async def get_by_slug(
        self, game_id: UUID, slug: str, include_deleted: bool = False
    ) -> Optional[GameMode]:
        stmt = select(GameMode).where(GameMode.game_id == game_id, GameMode.slug == slug)
        if not include_deleted:
            stmt = stmt.where(GameMode.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def slug_exists(
        self, game_id: UUID, slug: str, exclude_id: Optional[UUID] = None
    ) -> bool:
        stmt = select(GameMode.id).where(
            GameMode.game_id == game_id,
            GameMode.slug == slug,
            GameMode.deleted_at.is_(None),
        )
        if exclude_id is not None:
            stmt = stmt.where(GameMode.id != exclude_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def name_exists(
        self, game_id: UUID, name: str, exclude_id: Optional[UUID] = None
    ) -> bool:
        """Guards against duplicate mode names within the same game."""
        stmt = select(GameMode.id).where(
            GameMode.game_id == game_id,
            func.lower(GameMode.name) == name.lower(),
            GameMode.deleted_at.is_(None),
        )
        if exclude_id is not None:
            stmt = stmt.where(GameMode.id != exclude_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_paginated(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        game_id: Optional[UUID] = None,
        is_active: Optional[bool] = None,
        is_featured: Optional[bool] = None,
        search: Optional[str] = None,
        sort_by: str = "sort_order",
        sort_order: str = "asc",
        include_deleted: bool = False,
    ) -> tuple[Sequence[GameMode], int]:
        conditions = []
        if not include_deleted:
            conditions.append(GameMode.deleted_at.is_(None))
        if game_id is not None:
            conditions.append(GameMode.game_id == game_id)
        if is_active is not None:
            conditions.append(GameMode.is_active.is_(is_active))
        if is_featured is not None:
            conditions.append(GameMode.is_featured.is_(is_featured))
        if search:
            like = f"%{search.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(GameMode.name).like(like),
                    func.lower(GameMode.slug).like(like),
                )
            )

        count_stmt = select(func.count(GameMode.id)).where(*conditions)
        total = (await self.session.execute(count_stmt)).scalar_one()

        sort_column = _SORTABLE_FIELDS.get(sort_by, GameMode.sort_order)
        order_fn = asc if sort_order.lower() == "asc" else desc

        stmt = (
            select(GameMode)
            .where(*conditions)
            .order_by(order_fn(sort_column), asc(GameMode.name))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total
