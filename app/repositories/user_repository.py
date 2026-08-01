"""
User repository — user-specific queries.
"""
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_email(self, email: str, include_deleted: bool = False) -> Optional[User]:
        stmt = select(User).where(User.email == email.lower())
        if not include_deleted:
            stmt = stmt.where(User.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone_number: str, include_deleted: bool = False) -> Optional[User]:
        stmt = select(User).where(User.phone_number == phone_number)
        if not include_deleted:
            stmt = stmt.where(User.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_player_uid(self, player_uid: str, include_deleted: bool = False) -> Optional[User]:
        stmt = select(User).where(User.player_uid == player_uid.strip())
        if not include_deleted:
            stmt = stmt.where(User.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def exists_by_email_or_phone(self, email: str, phone_number: str) -> Optional[User]:
        stmt = select(User).where(
            or_(User.email == email.lower(), User.phone_number == phone_number),
            User.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
