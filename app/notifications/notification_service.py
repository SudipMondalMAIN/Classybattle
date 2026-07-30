"""
In-app notification persistence service. Infrastructure only for Phase 1 —
no business events trigger notifications yet.
"""
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationChannel, NotificationStatus
from app.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Notification)


class NotificationService:
    """Reusable service to create and manage in-app notifications."""

    def __init__(self, session: AsyncSession) -> None:
        self.repo = NotificationRepository(session)

    async def create_in_app_notification(
        self, user_id: UUID, title: str, body: str, meta_data: dict | None = None
    ) -> Notification:
        return await self.repo.create(
            user_id=user_id,
            title=title,
            body=body,
            channel=NotificationChannel.IN_APP,
            status=NotificationStatus.SENT,
            meta_data=meta_data,
        )
