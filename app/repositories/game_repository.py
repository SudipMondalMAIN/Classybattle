"""
Game and UserGameProfile repositories.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import Game
from app.models.game_profile import UserGameProfile
from app.repositories.base import BaseRepository


class GameRepository(BaseRepository[Game]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Game)

    async def get_by_slug(self, slug: str) -> Optional[Game]:
        stmt = select(Game).where(Game.slug == slug, Game.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Game]:
        stmt = select(Game).where(Game.is_active.is_(True), Game.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class UserGameProfileRepository(BaseRepository[UserGameProfile]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, UserGameProfile)

    async def get_by_user_and_game(self, user_id: UUID, game_id: UUID) -> Optional[UserGameProfile]:
        stmt = select(UserGameProfile).where(
            UserGameProfile.user_id == user_id,
            UserGameProfile.game_id == game_id,
            UserGameProfile.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: UUID) -> list[UserGameProfile]:
        stmt = select(UserGameProfile).where(
            UserGameProfile.user_id == user_id,
            UserGameProfile.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
