"""
Repositories for Achievement/Badge/UserAchievement — Phase 15C.
"""
from __future__ import annotations

from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.achievement import Achievement, AchievementTriggerType, Badge, UserAchievement
from app.repositories.base import BaseRepository


class BadgeRepository(BaseRepository[Badge]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Badge)

    async def list_active(self) -> Sequence[Badge]:
        stmt = select(Badge).where(Badge.deleted_at.is_(None), Badge.is_active.is_(True))
        result = await self.session.execute(stmt)
        return result.scalars().all()


class AchievementRepository(BaseRepository[Achievement]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Achievement)

    async def get_by_code(self, code: str) -> Optional[Achievement]:
        stmt = select(Achievement).where(Achievement.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active_by_trigger(self, trigger_type: AchievementTriggerType) -> Sequence[Achievement]:
        stmt = select(Achievement).where(
            Achievement.deleted_at.is_(None),
            Achievement.is_active.is_(True),
            Achievement.trigger_type == trigger_type,
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_active(self) -> Sequence[Achievement]:
        stmt = select(Achievement).where(Achievement.deleted_at.is_(None), Achievement.is_active.is_(True))
        result = await self.session.execute(stmt)
        return result.scalars().all()


class UserAchievementRepository(BaseRepository[UserAchievement]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, UserAchievement)

    async def get_for_user_and_achievement(
        self, user_id: UUID, achievement_id: UUID
    ) -> Optional[UserAchievement]:
        stmt = select(UserAchievement).where(
            UserAchievement.user_id == user_id,
            UserAchievement.achievement_id == achievement_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: UUID) -> Sequence[UserAchievement]:
        stmt = (
            select(UserAchievement)
            .where(UserAchievement.user_id == user_id, UserAchievement.deleted_at.is_(None))
            .order_by(UserAchievement.unlocked_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def unlocked_achievement_ids_for_user(self, user_id: UUID) -> set:
        stmt = select(UserAchievement.achievement_id).where(UserAchievement.user_id == user_id)
        result = await self.session.execute(stmt)
        return set(result.scalars().all())
