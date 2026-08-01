"""
Notification model — stores in-app notifications and tracks delivery
status of push/email channels. Business-trigger logic comes in a later phase.
"""
import enum
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
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


class NotificationEventType(str, enum.Enum):
    """Logical event/category of a notification, used for filtering and
    for choosing copy/behaviour independently of the delivery `channel`."""

    GENERAL = "general"
    USER_REGISTRATION = "user_registration"
    TOURNAMENT_CREATED = "tournament_created"
    TOURNAMENT_UPDATED = "tournament_updated"
    TOURNAMENT_CANCELLED = "tournament_cancelled"
    REGISTRATION_SUCCESSFUL = "registration_successful"
    REGISTRATION_CANCELLED = "registration_cancelled"
    MATCH_CREATED = "match_created"
    MATCH_STARTED = "match_started"
    MATCH_COMPLETED = "match_completed"
    LIVE_MATCH_STARTED = "live_match_started"
    MATCH_RESULT_APPROVED = "match_result_approved"
    WINNER_DECLARED = "winner_declared"
    PRIZE_DISTRIBUTED = "prize_distributed"
    WALLET_CREDITED = "wallet_credited"
    WALLET_DEBITED = "wallet_debited"
    REFUND_COMPLETED = "refund_completed"
    ADMIN_BROADCAST = "admin_broadcast"
    SYSTEM_ANNOUNCEMENT = "system_announcement"


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
    event_type: Mapped[NotificationEventType] = mapped_column(
        Enum(NotificationEventType, name="notification_event_type"),
        default=NotificationEventType.GENERAL,
        nullable=False,
        index=True,
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Unique per (event, recipient) key used to guarantee automatic
    # lifecycle notifications fire at most once even under retries
    # (e.g. "wallet_credited:<transaction_id>").
    event_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True, index=True)
    meta_data: Mapped[Optional[dict]] = mapped_column(PortableJSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<Notification id={self.id} user_id={self.user_id} channel={self.channel}>"


class NotificationPreference(BaseModel):
    """Per-user opt-in/out toggles for each delivery channel."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<NotificationPreference user_id={self.user_id}>"
