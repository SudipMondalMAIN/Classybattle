"""
Repository for support chat sessions & messages.
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.support_chat import SupportChatMessage, SupportChatSession, SupportChatStatus
from app.repositories.base import BaseRepository

OPEN_STATUSES = (SupportChatStatus.WAITING, SupportChatStatus.ACTIVE)


class SupportChatRepository(BaseRepository[SupportChatSession]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SupportChatSession)

    async def get_open_session_for_user(self, user_id: UUID) -> Optional[SupportChatSession]:
        stmt = (
            select(SupportChatSession)
            .where(
                SupportChatSession.user_id == user_id,
                SupportChatSession.status.in_(OPEN_STATUSES),
                SupportChatSession.deleted_at.is_(None),
            )
            .order_by(SupportChatSession.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_waiting(self) -> Sequence[SupportChatSession]:
        stmt = (
            select(SupportChatSession)
            .where(SupportChatSession.status == SupportChatStatus.WAITING, SupportChatSession.deleted_at.is_(None))
            .order_by(SupportChatSession.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_for_admin(
        self, status: Optional[SupportChatStatus] = None, page: int = 1, page_size: int = 20
    ) -> tuple[Sequence[SupportChatSession], int]:
        stmt = select(SupportChatSession).where(SupportChatSession.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(SupportChatSession.status == status)

        count_stmt = select(SupportChatSession.id).where(SupportChatSession.deleted_at.is_(None))
        if status is not None:
            count_stmt = count_stmt.where(SupportChatSession.status == status)
        total = len((await self.session.execute(count_stmt)).all())

        stmt = stmt.order_by(SupportChatSession.last_message_at.desc().nulls_last()).offset(
            (page - 1) * page_size
        ).limit(page_size)
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def add_message(
        self, session_id: UUID, sender_type, sender_id: Optional[UUID], content: str
    ) -> SupportChatMessage:
        message = SupportChatMessage(
            session_id=session_id, sender_type=sender_type, sender_id=sender_id, content=content
        )
        self.session.add(message)
        await self.session.flush()
        await self.session.refresh(message)
        return message

    async def list_messages(self, session_id: UUID) -> Sequence[SupportChatMessage]:
        stmt = (
            select(SupportChatMessage)
            .where(SupportChatMessage.session_id == session_id, SupportChatMessage.deleted_at.is_(None))
            .order_by(SupportChatMessage.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
