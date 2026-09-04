"""
Support chat service.

Holds all state-transition logic for live support chat sessions
(waiting -> active -> closed) so both the WebSocket routes and the REST
fallback routes go through the exact same rules and the exact same
realtime broadcast. The DB is always the source of truth; the in-memory
SupportChatConnectionManager is purely for pushing updates to whoever is
currently connected.
"""
import math
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.core.support_chat_manager import manager
from app.models.support_chat import (
    SupportChatClosedBy,
    SupportChatMessage,
    SupportChatMessageType,
    SupportChatSenderType,
    SupportChatSession,
    SupportChatStatus,
)
from app.models.user import User
from app.repositories.support_chat_repository import SupportChatRepository
from app.schemas.support_chat import SupportChatMessageRead, SupportChatSessionRead
from app.storage.cloudinary_service import CloudinaryMediaService

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
_ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm", "video/3gpp", "video/x-matroska"}
_MAX_IMAGE_SIZE_BYTES = 8 * 1024 * 1024  # 8 MB
_MAX_VIDEO_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


def _session_summary(session: SupportChatSession) -> dict:
    return {
        "type": "session_update",
        "session": SupportChatSessionRead.model_validate(session).model_dump(mode="json"),
    }


def _message_payload(message: SupportChatMessage) -> dict:
    return {
        "type": "message",
        "message": SupportChatMessageRead.model_validate(message).model_dump(mode="json"),
    }


class SupportChatService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SupportChatRepository(session)

    # ------------------------------------------------------------------
    # Session lookup / creation
    # ------------------------------------------------------------------
    async def get_or_create_open_session(self, user: User) -> SupportChatSession:
        """A user only ever has one open (waiting/active) session. Reopening
        the support page re-attaches to it instead of starting fresh; a
        brand new session is only created once the previous one is closed."""
        existing = await self.repo.get_open_session_for_user(user.id)
        if existing is not None:
            return existing

        chat_session = await self.repo.create(user_id=user.id, status=SupportChatStatus.WAITING)
        await self.session.commit()
        await self.session.refresh(chat_session)
        return chat_session

    async def get_session_or_404(self, session_id: UUID) -> SupportChatSession:
        chat_session = await self.repo.get_by_id(session_id)
        if chat_session is None:
            raise NotFoundException("Support chat session not found")
        return chat_session

    async def get_history(self, chat_session: SupportChatSession) -> list[SupportChatMessage]:
        return await self.repo.list_messages(chat_session.id)

    async def list_waiting(self):
        return await self.repo.list_waiting()

    async def list_for_admin(self, status: Optional[SupportChatStatus], page: int, page_size: int):
        items, total = await self.repo.list_for_admin(status=status, page=page, page_size=page_size)
        total_pages = math.ceil(total / page_size) if total else 0
        return items, total, total_pages

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------
    async def post_user_message(self, user: User, chat_session: SupportChatSession, content: str) -> SupportChatMessage:
        if chat_session.user_id != user.id:
            raise ForbiddenException("This isn't your support chat")
        if chat_session.status == SupportChatStatus.CLOSED:
            raise BadRequestException("This chat has ended. Send a new message to start a new one.")

        message = await self.repo.add_message(
            chat_session.id, SupportChatSenderType.USER, user.id, content
        )
        is_first_message = chat_session.status == SupportChatStatus.WAITING and chat_session.last_message_at is None
        chat_session.last_message_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(chat_session)

        await manager.broadcast_to_session(chat_session.id, _message_payload(message))

        if is_first_message:
            # First message of a brand new session -- let the user know
            # we're finding them an agent, and tell every admin browsing
            # the lobby that a new ticket needs attention.
            wait_notice = await self.repo.add_message(
                chat_session.id,
                SupportChatSenderType.SYSTEM,
                None,
                "Thanks for reaching out! We're connecting you with an agent.",
            )
            await self.session.commit()
            await manager.broadcast_to_session(chat_session.id, _message_payload(wait_notice))
            await manager.broadcast_to_lobby(_session_summary(chat_session))
        else:
            await manager.broadcast_to_lobby(_session_summary(chat_session))

        return message

    async def post_agent_message(
        self, agent: User, chat_session: SupportChatSession, content: str
    ) -> SupportChatMessage:
        if chat_session.status != SupportChatStatus.ACTIVE:
            raise BadRequestException("Join this chat before sending messages")
        if chat_session.agent_id != agent.id:
            raise ForbiddenException("Another agent is already handling this chat")

        message = await self.repo.add_message(
            chat_session.id, SupportChatSenderType.AGENT, agent.id, content
        )
        chat_session.last_message_at = datetime.now(timezone.utc)
        await self.session.commit()

        await manager.broadcast_to_session(chat_session.id, _message_payload(message))

        try:
            from app.models.notification import NotificationEventType
            from app.models.user import User as _User
            from app.notifications.dispatch_service import NotificationDispatchService

            recipient = await self.session.get(_User, chat_session.user_id)
            if recipient is not None:
                await NotificationDispatchService(self.session).dispatch(
                    user=recipient,
                    event_type=NotificationEventType.GENERAL,
                    title="New message from support",
                    body=content[:200],
                    event_key=f"support_chat_message:{message.id}",
                    meta_data={"session_id": str(chat_session.id)},
                    # Push only -- the message already appears directly in
                    # the chat thread (broadcast_to_session above), so a
                    # second copy in the general in-app notification list
                    # would just be a duplicate.
                    send_in_app=False,
                )
        except Exception:  # noqa: BLE001
            pass

        return message

    # ------------------------------------------------------------------
    # Media (image/video) messages
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_media(content_type: str, file_bytes: bytes) -> tuple[SupportChatMessageType, str]:
        """Returns (message_type, cloudinary resource_type) or raises."""
        if content_type in _ALLOWED_IMAGE_TYPES:
            if len(file_bytes) > _MAX_IMAGE_SIZE_BYTES:
                raise ValidationException("Image must be 8 MB or smaller")
            return SupportChatMessageType.IMAGE, "image"
        if content_type in _ALLOWED_VIDEO_TYPES:
            if len(file_bytes) > _MAX_VIDEO_SIZE_BYTES:
                raise ValidationException("Video must be 50 MB or smaller")
            return SupportChatMessageType.VIDEO, "video"
        raise ValidationException("Only JPEG/PNG/WEBP images or MP4/MOV/WEBM videos are allowed")

    async def post_user_media_message(
        self,
        user: User,
        chat_session: SupportChatSession,
        file_bytes: bytes,
        content_type: str,
        caption: str = "",
    ) -> SupportChatMessage:
        if chat_session.user_id != user.id:
            raise ForbiddenException("This isn't your support chat")
        if chat_session.status == SupportChatStatus.CLOSED:
            raise BadRequestException("This chat has ended. Send a new message to start a new one.")

        message_type, resource_type = self._validate_media(content_type, file_bytes)
        uploaded = await CloudinaryMediaService(str(chat_session.id)).upload(file_bytes, content_type, resource_type)

        message = await self.repo.add_message(
            chat_session.id,
            SupportChatSenderType.USER,
            user.id,
            caption,
            message_type=message_type,
            media_url=uploaded["url"],
            media_public_id=uploaded["public_id"],
        )
        is_first_message = chat_session.status == SupportChatStatus.WAITING and chat_session.last_message_at is None
        chat_session.last_message_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(chat_session)

        await manager.broadcast_to_session(chat_session.id, _message_payload(message))

        if is_first_message:
            wait_notice = await self.repo.add_message(
                chat_session.id,
                SupportChatSenderType.SYSTEM,
                None,
                "Thanks for reaching out! We're connecting you with an agent.",
            )
            await self.session.commit()
            await manager.broadcast_to_session(chat_session.id, _message_payload(wait_notice))
        await manager.broadcast_to_lobby(_session_summary(chat_session))

        return message

    async def post_agent_media_message(
        self,
        agent: User,
        chat_session: SupportChatSession,
        file_bytes: bytes,
        content_type: str,
        caption: str = "",
    ) -> SupportChatMessage:
        if chat_session.status != SupportChatStatus.ACTIVE:
            raise BadRequestException("Join this chat before sending messages")
        if chat_session.agent_id != agent.id:
            raise ForbiddenException("Another agent is already handling this chat")

        message_type, resource_type = self._validate_media(content_type, file_bytes)
        uploaded = await CloudinaryMediaService(str(chat_session.id)).upload(file_bytes, content_type, resource_type)

        message = await self.repo.add_message(
            chat_session.id,
            SupportChatSenderType.AGENT,
            agent.id,
            caption,
            message_type=message_type,
            media_url=uploaded["url"],
            media_public_id=uploaded["public_id"],
        )
        chat_session.last_message_at = datetime.now(timezone.utc)
        await self.session.commit()

        await manager.broadcast_to_session(chat_session.id, _message_payload(message))

        try:
            from app.models.notification import NotificationEventType
            from app.models.user import User as _User
            from app.notifications.dispatch_service import NotificationDispatchService

            recipient = await self.session.get(_User, chat_session.user_id)
            if recipient is not None:
                body = "Sent a photo" if message_type == SupportChatMessageType.IMAGE else "Sent a video"
                await NotificationDispatchService(self.session).dispatch(
                    user=recipient,
                    event_type=NotificationEventType.GENERAL,
                    title="New message from support",
                    body=body,
                    event_key=f"support_chat_message:{message.id}",
                    meta_data={"session_id": str(chat_session.id)},
                    send_in_app=False,
                )
        except Exception:  # noqa: BLE001
            pass

        return message

    # ------------------------------------------------------------------
    # Lifecycle: join / end
    # ------------------------------------------------------------------
    async def join_session(self, agent: User, chat_session: SupportChatSession) -> SupportChatSession:
        if chat_session.status == SupportChatStatus.CLOSED:
            raise BadRequestException("This chat has already ended")
        if chat_session.status == SupportChatStatus.ACTIVE and chat_session.agent_id != agent.id:
            raise ForbiddenException("Another agent is already handling this chat")

        chat_session.status = SupportChatStatus.ACTIVE
        chat_session.agent_id = agent.id
        await self.session.commit()
        await self.session.refresh(chat_session)

        join_notice = await self.repo.add_message(
            chat_session.id,
            SupportChatSenderType.SYSTEM,
            None,
            f"{agent.full_name or 'An agent'} joined the chat",
        )
        await self.session.commit()

        await manager.broadcast_to_session(chat_session.id, _message_payload(join_notice))
        await manager.broadcast_to_session(chat_session.id, _session_summary(chat_session))
        await manager.broadcast_to_lobby(_session_summary(chat_session))
        return chat_session

    async def end_session(
        self, actor: User, chat_session: SupportChatSession, closed_by: SupportChatClosedBy
    ) -> SupportChatSession:
        if chat_session.status == SupportChatStatus.CLOSED:
            return chat_session

        if closed_by == SupportChatClosedBy.USER and chat_session.user_id != actor.id:
            raise ForbiddenException("This isn't your support chat")
        if closed_by == SupportChatClosedBy.AGENT and chat_session.agent_id not in (None, actor.id):
            raise ForbiddenException("Another agent is handling this chat")

        chat_session.status = SupportChatStatus.CLOSED
        chat_session.closed_by = closed_by
        chat_session.closed_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(chat_session)

        end_notice = await self.repo.add_message(
            chat_session.id,
            SupportChatSenderType.SYSTEM,
            None,
            f"Chat ended by {closed_by.value}",
        )
        await self.session.commit()

        await manager.broadcast_to_session(chat_session.id, _message_payload(end_notice))
        await manager.broadcast_to_session(chat_session.id, _session_summary(chat_session))
        await manager.broadcast_to_lobby(_session_summary(chat_session))
        await manager.close_session_sockets(chat_session.id)
        return chat_session