"""
PromotionalCampaign — admin-defined promotional notifications that the
scheduler (`app.core.scheduler`) sends out automatically, without an
admin having to trigger anything at send time. Reuses the same
NotificationDispatchService.dispatch_bulk() the manual admin-broadcast
feature already uses, so push/email/in-app fan-out and per-user
preference checks come for free.

Schedule types:
- ONCE:            fires a single time at `scheduled_at`, then deactivates.
- DAILY:           fires every day at `send_hour`:`send_minute` (IST).
- INTERVAL_HOURS:  fires every `interval_hours` hours, starting from
                   creation/last send, regardless of clock time.
"""
import enum
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import BaseModel
from app.database.types import str_enum


class PromotionalScheduleType(str, enum.Enum):
    ONCE = "once"
    DAILY = "daily"
    INTERVAL_HOURS = "interval_hours"


class PromotionalCampaign(BaseModel):
    __tablename__ = "promotional_campaigns"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(String(1000), nullable=False)

    schedule_type: Mapped[PromotionalScheduleType] = mapped_column(
        str_enum(PromotionalScheduleType, "promotional_schedule_type"), nullable=False
    )
    # ONCE
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # DAILY (interpreted in IST, same convention as the slot scheduler)
    send_hour: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    send_minute: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # INTERVAL_HOURS
    interval_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    send_push: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    send_email: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_recipient_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_by_admin_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
