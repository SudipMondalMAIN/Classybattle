"""
DeviceTokenRepository — FCM device token registration/lookup for push.
"""
from __future__ import annotations

from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device_token import DeviceToken
from app.repositories.base import BaseRepository


class DeviceTokenRepository(BaseRepository[DeviceToken]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, DeviceToken)

    async def get_by_user_and_token(self, user_id: UUID, fcm_token: str) -> DeviceToken | None:
        stmt = select(DeviceToken).where(
            DeviceToken.user_id == user_id,
            DeviceToken.fcm_token == fcm_token,
            DeviceToken.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active_for_user(self, user_id: UUID) -> Sequence[DeviceToken]:
        stmt = select(DeviceToken).where(
            DeviceToken.user_id == user_id,
            DeviceToken.is_active.is_(True),
            DeviceToken.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def deactivate(self, user_id: UUID, fcm_token: str) -> bool:
        token = await self.get_by_user_and_token(user_id, fcm_token)
        if token is None:
            return False
        token.is_active = False
        await self.session.flush()
        return True
