"""
NotificationPreferenceRepository — per-user channel opt-in/out storage.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationPreference
from app.repositories.base import BaseRepository


class NotificationPreferenceRepository(BaseRepository[NotificationPreference]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, NotificationPreference)

    async def get_by_user_id(self, user_id: UUID) -> NotificationPreference | None:
        stmt = select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(self, user_id: UUID) -> NotificationPreference:
        pref = await self.get_by_user_id(user_id)
        if pref is not None:
            return pref
        return await self.create(user_id=user_id)
