"""
NotificationDispatchService — Phase 13 (Enterprise Notification & Communication System).

Single reusable entry point every other service calls to notify users.
Design goals:
  * Never break business logic — every public method swallows and logs
    its own exceptions instead of propagating them.
  * Idempotent automatic events — pass `event_key` (a stable string
    derived from the triggering entity, e.g. "wallet_credited:<txn_id>")
    and a duplicate call becomes a no-op via the unique DB constraint on
    Notification.event_key.
  * Respects per-user NotificationPreference toggles for push/email/in-app.
  * Fans out to In-App (always persisted), Push (FCM via push_service)
    and Email (Brevo via email_service) channels.
"""
from __future__ import annotations

from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.emails.email_service import email_service
from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationEventType,
    NotificationStatus,
)
from app.models.user import User
from app.notifications.push_service import push_service
from app.repositories.device_token_repository import DeviceTokenRepository
from app.repositories.notification_preference_repository import (
    NotificationPreferenceRepository,
)
from app.repositories.notification_repository import NotificationRepository

logger = get_logger(__name__)


class NotificationDispatchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.notif_repo = NotificationRepository(session)
        self.pref_repo = NotificationPreferenceRepository(session)
        self.device_repo = DeviceTokenRepository(session)

    async def dispatch(
        self,
        *,
        user: User,
        event_type: NotificationEventType,
        title: str,
        body: str,
        event_key: Optional[str] = None,
        meta_data: Optional[dict] = None,
        send_push: bool = True,
        send_email: bool = False,
    ) -> Optional[Notification]:
        """Create an in-app notification (and best-effort push/email) for
        one user. Returns the persisted Notification, or None if nothing
        was sent (duplicate event, muted preference, or an internal
        failure — failures are logged, never raised)."""
        try:
            if event_key:
                existing = await self.notif_repo.get_by_event_key(event_key)
                if existing is not None:
                    return existing

            prefs = await self.pref_repo.get_or_create(user.id)

            notification: Optional[Notification] = None
            if prefs.in_app_enabled:
                try:
                    notification = await self.notif_repo.create(
                        user_id=user.id,
                        title=title,
                        body=body,
                        channel=NotificationChannel.IN_APP,
                        status=NotificationStatus.SENT,
                        event_type=event_type,
                        event_key=event_key,
                        meta_data=meta_data,
                    )
                except IntegrityError:
                    # Concurrent duplicate dispatch for the same event_key —
                    # the unique constraint already guaranteed single delivery.
                    await self.session.rollback()
                    existing = await self.notif_repo.get_by_event_key(event_key) if event_key else None
                    await self.session.commit()
                    return existing

            if send_push and prefs.push_enabled:
                await self._send_push_best_effort(
                    user.id,
                    title,
                    body,
                    event_type,
                    notification_id=notification.id if notification else None,
                    meta_data=meta_data,
                )

            if send_email and prefs.email_enabled and getattr(user, "email", None):
                await self._send_email_best_effort(user.email, title, body)

            await self.session.commit()
            return notification
        except Exception as exc:  # noqa: BLE001 - notifications must never break callers
            logger.error("notification_dispatch_failed", user_id=str(user.id), error=str(exc))
            try:
                await self.session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return None

    async def dispatch_bulk(
        self,
        *,
        users: Iterable[User],
        event_type: NotificationEventType,
        title: str,
        body: str,
        event_key_prefix: Optional[str] = None,
        meta_data: Optional[dict] = None,
        send_push: bool = True,
        send_email: bool = False,
    ) -> int:
        """Best-effort fan-out to many users (e.g. every active
        participant of a tournament, or an admin broadcast). One user's
        failure never blocks the rest. Returns the count of notifications
        successfully created."""
        sent = 0
        for user in users:
            event_key = f"{event_key_prefix}:{user.id}" if event_key_prefix else None
            result = await self.dispatch(
                user=user,
                event_type=event_type,
                title=title,
                body=body,
                event_key=event_key,
                meta_data=meta_data,
                send_push=send_push,
                send_email=send_email,
            )
            if result is not None:
                sent += 1
        return sent

    # ------------------------------------------------------------------
    # Best-effort channel fan-out helpers
    # ------------------------------------------------------------------
    async def _send_push_best_effort(
        self,
        user_id: UUID,
        title: str,
        body: str,
        event_type: NotificationEventType,
        notification_id: Optional[UUID] = None,
        meta_data: Optional[dict] = None,
    ) -> None:
        try:
            tokens = await self.device_repo.list_active_for_user(user_id)
            # FCM data payloads must be Dict[str, str] -- flatten meta_data
            # (tournament_id, transaction_id, etc.) so the app can navigate
            # to the right screen when the user taps the notification.
            data: dict[str, str] = {"event_type": event_type.value}
            if notification_id is not None:
                data["notification_id"] = str(notification_id)
            if meta_data:
                for key, value in meta_data.items():
                    if value is not None:
                        data[str(key)] = str(value)
            for token in tokens:
                await push_service.send_push(token.fcm_token, title, body, data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("notification_push_failed", user_id=str(user_id), error=str(exc))

    async def _send_email_best_effort(self, to_email: str, title: str, body: str) -> None:
        try:
            await email_service.send_notification_email(to_email=to_email, subject=title, body=body)
        except Exception as exc:  # noqa: BLE001
            logger.warning("notification_email_failed", to=to_email, error=str(exc))