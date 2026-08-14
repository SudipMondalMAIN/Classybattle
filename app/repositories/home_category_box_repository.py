"""
Repository for HomeCategoryBox.
"""
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.home_category_box import HomeCategoryBox
from app.repositories.base import BaseRepository


class HomeCategoryBoxRepository(BaseRepository[HomeCategoryBox]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, HomeCategoryBox)

    async def list_active(self) -> Sequence[HomeCategoryBox]:
        stmt = (
            select(HomeCategoryBox)
            .where(HomeCategoryBox.deleted_at.is_(None), HomeCategoryBox.is_active.is_(True))
            .order_by(HomeCategoryBox.sort_order.asc(), HomeCategoryBox.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_all_for_admin(self) -> Sequence[HomeCategoryBox]:
        stmt = (
            select(HomeCategoryBox)
            .where(HomeCategoryBox.deleted_at.is_(None))
            .order_by(HomeCategoryBox.sort_order.asc(), HomeCategoryBox.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
