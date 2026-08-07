"""
Repository for AppVersion — one row per platform.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_version import AppPlatform, AppVersion
from app.repositories.base import BaseRepository


class AppVersionRepository(BaseRepository[AppVersion]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AppVersion)

    async def get_by_platform(self, platform: AppPlatform) -> Optional[AppVersion]:
        stmt = select(AppVersion).where(
            AppVersion.platform == platform, AppVersion.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
