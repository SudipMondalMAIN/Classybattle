"""
User repository — user-specific queries.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy import func, or_, select
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

    async def search_paginated(
        self, *, query: Optional[str], page: int, page_size: int
    ) -> tuple[list[User], int]:
        """
        Admin-only search across email, phone number, player_uid, short_id,
        and id (UUID). Matches are partial/case-insensitive for text
        fields; the id filter only applies when `query` parses as a valid
        UUID, and the short_id filter only when `query` is all digits.
        """
        stmt = select(User).where(User.deleted_at.is_(None))
        count_stmt = select(func.count(User.id)).where(User.deleted_at.is_(None))

        if query:
            q = query.strip()
            like = f"%{q.lower()}%"
            conditions = [
                func.lower(User.email).like(like),
                func.lower(User.phone_number).like(like),
                func.lower(User.player_uid).like(like),
                func.lower(User.full_name).like(like),
            ]
            try:
                as_uuid = UUID(q)
                conditions.append(User.id == as_uuid)
            except ValueError:
                pass

            if q.isdigit():
                conditions.append(User.short_id == int(q))

            search_filter = or_(*conditions)
            stmt = stmt.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        stmt = stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)

        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total