"""
Notification model — stores in-app notifications and tracks delivery
status of push/email channels. Business-trigger logic comes in a later phase.
"""
import enum
from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, Enum, ForeignKey, String
from app.database.types import PortableJSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import BaseModel


class NotificationChannel(str, enum.Enum):
    PUSH = "push"
    EMAIL = "email"
    IN_APP = "in_app"


class NotificationStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class Notification(BaseModel):
    __tablename__ = "notifications"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(String(1000), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel"), nullable=False
    )
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notification_status"),
        default=NotificationStatus.PENDING,
        nullable=False,
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    meta_data: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<Notification id={self.id} user_id={self.user_id} channel={self.channel}>"
