"""
Firebase Cloud Messaging (FCM) push notification service.

Phase 1 provides infrastructure/setup only: initializing the Firebase
Admin SDK and a reusable `send_push` method. Business-triggered pushes
(tournament reminders, wallet events, etc.) are wired up in later phases.
"""
import os
from typing import Optional

from app.config.settings import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_firebase_app = None


def init_firebase() -> None:
    """Initialize the Firebase Admin SDK once, if credentials are available."""
    global _firebase_app

    if _firebase_app is not None:
        return

    if not os.path.exists(settings.FIREBASE_CREDENTIALS_PATH):
        logger.warning(
            "firebase_credentials_not_found",
            path=settings.FIREBASE_CREDENTIALS_PATH,
        )
        return

    try:
        import firebase_admin
        from firebase_admin import credentials

        cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
        _firebase_app = firebase_admin.initialize_app(cred)
        logger.info("firebase_initialized", project_id=settings.FIREBASE_PROJECT_ID)
    except Exception as exc:  # noqa: BLE001
        logger.error("firebase_init_failed", error=str(exc))


class PushNotificationService:
    """Reusable service for sending push notifications through FCM."""

    async def send_push(
        self,
        fcm_token: str,
        title: str,
        body: str,
        data: Optional[dict[str, str]] = None,
    ) -> bool:
        if _firebase_app is None:
            logger.warning("push_skipped_firebase_not_configured", token=fcm_token[:12])
            return False

        try:
            import asyncio

            from firebase_admin import messaging

            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=data or {},
                token=fcm_token,
            )
            # messaging.send() is a SYNCHRONOUS, blocking network call (the
            # Firebase Admin SDK has no native async client). Calling it
            # directly here -- inside an `async def` but without offloading
            # it -- blocks the single-threaded asyncio event loop for as
            # long as the call to Firebase's servers takes. That freezes
            # EVERY other in-flight request on this process (e.g. the
            # /admin/players/{id}/pay response itself), which is why the
            # admin panel's "Saving..." spinner could sit there long after
            # the wallet credit had already committed to the DB. Running it
            # in a worker thread keeps the event loop free.
            await asyncio.to_thread(messaging.send, message)
            logger.info("push_sent", token=fcm_token[:12])
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("push_send_failed", error=str(exc))
            return False


push_service = PushNotificationService()