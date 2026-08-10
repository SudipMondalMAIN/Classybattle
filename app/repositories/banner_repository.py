"""
Repository for Banner.
"""
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.banner import Banner
from app.repositories.base import BaseRepository


class BannerRepository(BaseRepository[Banner]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Banner)

    async def list_active(self) -> Sequence[Banner]:
        stmt = (
            select(Banner)
            .where(Banner.deleted_at.is_(None), Banner.is_active.is_(True))
            .order_by(Banner.sort_order.asc(), Banner.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_all_for_admin(self) -> Sequence[Banner]:
        stmt = (
            select(Banner)
            .where(Banner.deleted_at.is_(None))
            .order_by(Banner.sort_order.asc(), Banner.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
