"""
Repository for MaintenanceConfig — a single global row (no per-platform
split; maintenance is all-or-nothing for the whole app).
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.maintenance import MaintenanceConfig
from app.repositories.base import BaseRepository


class MaintenanceRepository(BaseRepository[MaintenanceConfig]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, MaintenanceConfig)

    async def get_singleton(self) -> Optional[MaintenanceConfig]:
        stmt = select(MaintenanceConfig).where(
            MaintenanceConfig.deleted_at.is_(None)
        ).order_by(MaintenanceConfig.created_at.asc())
        result = await self.session.execute(stmt)
        return result.scalars().first()
