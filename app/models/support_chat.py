"""
Support chat models — live user<->admin support chat.

A SupportChatSession is the container ("ticket"); each user has at most
one open (waiting/active) session at a time — see
SupportChatRepository.get_open_session_for_user. SupportChatMessage rows
are the individual messages inside a session, including system messages
(join/end notices) so the full transcript can be replayed on reconnect.
"""
import enum
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import BaseModel
from app.database.types import str_enum


class SupportChatStatus(str, enum.Enum):
    WAITING = "waiting"
    ACTIVE = "active"
    CLOSED = "closed"


class SupportChatClosedBy(str, enum.Enum):
    USER = "user"
    AGENT = "agent"


class SupportChatSenderType(str, enum.Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class SupportChatMessageType(str, enum.Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"


class SupportChatSession(BaseModel):
    __tablename__ = "support_chat_sessions"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[SupportChatStatus] = mapped_column(
        str_enum(SupportChatStatus, "support_chat_status"),
        default=SupportChatStatus.WAITING,
        nullable=False,
        index=True,
    )
    closed_by: Mapped[Optional[SupportChatClosedBy]] = mapped_column(
        str_enum(SupportChatClosedBy, "support_chat_closed_by"), nullable=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<SupportChatSession id={self.id} user_id={self.user_id} status={self.status}>"


class SupportChatMessage(BaseModel):
    __tablename__ = "support_chat_messages"

    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("support_chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_type: Mapped[SupportChatSenderType] = mapped_column(
        str_enum(SupportChatSenderType, "support_chat_sender_type"), nullable=False
    )
    sender_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    message_type: Mapped[SupportChatMessageType] = mapped_column(
        str_enum(SupportChatMessageType, "support_chat_message_type"),
        default=SupportChatMessageType.TEXT,
        nullable=False,
    )
    # Cloudinary public URL for image/video messages. Note: Cloudinary
    # auto-deletes this asset after settings.SUPPORT_MEDIA_RETENTION_DAYS
    # (see scripts/cleanup_support_media.py) -- the URL/row is kept for
    # history but will 404 once expired.
    media_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    media_public_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    def __repr__(self) -> str:
        return f"<SupportChatMessage id={self.id} session_id={self.session_id} sender_type={self.sender_type}>"
