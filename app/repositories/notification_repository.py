"""
NotificationRepository — persistence + query layer for in-app notifications.
Phase 13 (Enterprise Notification & Communication System).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import asc, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationEventType
from app.repositories.base import BaseRepository

_SORTABLE_FIELDS = {"created_at", "is_read", "event_type"}


class NotificationRepository(BaseRepository[Notification]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Notification)

    async def get_by_event_key(self, event_key: str) -> Optional[Notification]:
        stmt = select(Notification).where(Notification.event_key == event_key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        is_read: Optional[bool] = None,
        event_type: Optional[NotificationEventType] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[Notification], int]:
        sort_field = sort_by if sort_by in _SORTABLE_FIELDS else "created_at"
        order_fn = asc if sort_order.lower() == "asc" else desc

        base_stmt = select(Notification).where(
            Notification.user_id == user_id, Notification.deleted_at.is_(None)
        )
        if is_read is not None:
            base_stmt = base_stmt.where(Notification.is_read == is_read)
        if event_type is not None:
            base_stmt = base_stmt.where(Notification.event_type == event_type)

        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            base_stmt.order_by(order_fn(getattr(Notification, sort_field)))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def count_unread(self, user_id: UUID) -> int:
        stmt = select(func.count()).where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
            Notification.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def mark_read(self, notification: Notification) -> Notification:
        if notification.is_read:
            return notification
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.session.refresh(notification)
        return notification

    async def mark_all_read(self, user_id: UUID) -> int:
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
                Notification.deleted_at.is_(None),
            )
            .values(is_read=True, read_at=datetime.now(timezone.utc))
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount or 0

    async def bulk_soft_delete(self, user_id: UUID, notification_ids: Sequence[UUID]) -> int:
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.id.in_(notification_ids),
                Notification.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(timezone.utc))
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount or 0

    async def list_for_admin(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        user_id: Optional[UUID] = None,
        event_type: Optional[NotificationEventType] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[Notification], int]:
        sort_field = sort_by if sort_by in _SORTABLE_FIELDS else "created_at"
        order_fn = asc if sort_order.lower() == "asc" else desc

        base_stmt = select(Notification)
        if user_id is not None:
            base_stmt = base_stmt.where(Notification.user_id == user_id)
        if event_type is not None:
            base_stmt = base_stmt.where(Notification.event_type == event_type)

        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = (
            base_stmt.order_by(order_fn(getattr(Notification, sort_field)))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total
