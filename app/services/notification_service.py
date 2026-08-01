"""
NotificationService — user/admin facing operations on top of the
persisted notification store (list, read/unread, delete, preferences,
device tokens, admin broadcast). Business event fan-out itself lives in
`app.notifications.dispatch_service.NotificationDispatchService`, which
this service reuses for the admin broadcast feature.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.notification import Notification, NotificationEventType
from app.models.user import User
from app.notifications.dispatch_service import NotificationDispatchService
from app.repositories.device_token_repository import DeviceTokenRepository
from app.repositories.notification_preference_repository import (
    NotificationPreferenceRepository,
)
from app.repositories.notification_repository import NotificationRepository
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService
from app.models.audit_log import AuditAction, AuditActorType


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = NotificationRepository(session)
        self.pref_repo = NotificationPreferenceRepository(session)
        self.device_repo = DeviceTokenRepository(session)
        self.user_repo = UserRepository(session)
        self.dispatch_service = NotificationDispatchService(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------
    # Listing / read state
    # ------------------------------------------------------------------
    async def list_for_user(
        self,
        user: User,
        *,
        page: int,
        page_size: int,
        is_read: Optional[bool],
        event_type: Optional[NotificationEventType],
        sort_by: str,
        sort_order: str,
    ) -> tuple[Sequence[Notification], int, int]:
        items, total = await self.repo.list_for_user(
            user.id,
            page=page,
            page_size=page_size,
            is_read=is_read,
            event_type=event_type,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total_pages = math.ceil(total / page_size) if total else 0
        return items, total, total_pages

    async def get_unread_count(self, user: User) -> int:
        return await self.repo.count_unread(user.id)

    async def _get_owned(self, user: User, notification_id: UUID) -> Notification:
        notification = await self.repo.get_by_id(notification_id)
        if notification is None or notification.user_id != user.id:
            raise NotFoundException("Notification not found")
        return notification

    async def mark_read(self, user: User, notification_id: UUID) -> Notification:
        notification = await self._get_owned(user, notification_id)
        notification = await self.repo.mark_read(notification)
        await self.session.commit()
        return notification

    async def mark_all_read(self, user: User) -> int:
        count = await self.repo.mark_all_read(user.id)
        await self.session.commit()
        return count

    async def delete(self, user: User, notification_id: UUID) -> None:
        notification = await self._get_owned(user, notification_id)
        await self.repo.soft_delete(notification)
        await self.session.commit()

    async def bulk_delete(self, user: User, notification_ids: list[UUID]) -> int:
        count = await self.repo.bulk_soft_delete(user.id, notification_ids)
        await self.session.commit()
        return count

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------
    async def get_preferences(self, user: User):
        pref = await self.pref_repo.get_or_create(user.id)
        await self.session.commit()
        return pref

    async def update_preferences(self, user: User, payload) -> "NotificationPreference":  # noqa: F821
        pref = await self.pref_repo.get_or_create(user.id)
        update_data = payload.model_dump(exclude_unset=True, exclude_none=True)
        if update_data:
            pref = await self.pref_repo.update(pref, **update_data)
        await self.session.commit()
        return pref

    # ------------------------------------------------------------------
    # Device tokens (push)
    # ------------------------------------------------------------------
    async def register_device_token(self, user: User, fcm_token: str, platform: str):
        existing = await self.device_repo.get_by_user_and_token(user.id, fcm_token)
        if existing is not None:
            existing = await self.device_repo.update(existing, platform=platform, is_active=True)
            await self.session.commit()
            return existing
        token = await self.device_repo.create(
            user_id=user.id, fcm_token=fcm_token, platform=platform, is_active=True
        )
        await self.session.commit()
        return token

    async def deregister_device_token(self, user: User, fcm_token: str) -> bool:
        removed = await self.device_repo.deactivate(user.id, fcm_token)
        await self.session.commit()
        return removed

    # ------------------------------------------------------------------
    # Admin
    # ------------------------------------------------------------------
    async def list_for_admin(
        self,
        *,
        page: int,
        page_size: int,
        user_id: Optional[UUID],
        event_type: Optional[NotificationEventType],
        sort_by: str,
        sort_order: str,
    ) -> tuple[Sequence[Notification], int, int]:
        items, total = await self.repo.list_for_admin(
            page=page,
            page_size=page_size,
            user_id=user_id,
            event_type=event_type,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        total_pages = math.ceil(total / page_size) if total else 0
        return items, total, total_pages

    async def admin_broadcast(
        self,
        *,
        admin: User,
        title: str,
        body: str,
        target_user_ids: Optional[list[UUID]],
        send_push: bool,
        send_email: bool,
        broadcast_id: UUID,
    ) -> int:
        if target_user_ids:
            users = []
            for uid in target_user_ids:
                u = await self.user_repo.get_by_id(uid)
                if u is not None:
                    users.append(u)
        else:
            users = await self.user_repo.list_all(skip=0, limit=100000)

        sent = await self.dispatch_service.dispatch_bulk(
            users=users,
            event_type=NotificationEventType.ADMIN_BROADCAST,
            title=title,
            body=body,
            event_key_prefix=f"admin_broadcast:{broadcast_id}",
            send_push=send_push,
            send_email=send_email,
        )

        await self.audit.record(
            entity="notification_broadcast",
            action=AuditAction.CREATE,
            entity_id=broadcast_id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            new_values={"title": title, "recipients": sent},
            description=f"Admin broadcast '{title}' sent to {sent} users",
        )
        await self.session.commit()
        return sent
