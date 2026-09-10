from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.promotional_campaign import PromotionalScheduleType


class PromotionalCampaignCreate(BaseModel):
    title: str = Field(..., max_length=255)
    body: str = Field(..., max_length=1000)
    schedule_type: PromotionalScheduleType

    # ONCE
    scheduled_at: Optional[datetime] = None
    # DAILY (IST wall-clock)
    send_hour: Optional[int] = Field(None, ge=0, le=23)
    send_minute: Optional[int] = Field(None, ge=0, le=59)
    # INTERVAL_HOURS
    interval_hours: Optional[int] = Field(None, ge=1)

    send_push: bool = True
    send_email: bool = False

    @model_validator(mode="after")
    def _check_schedule_fields(self) -> "PromotionalCampaignCreate":
        if self.schedule_type == PromotionalScheduleType.ONCE and self.scheduled_at is None:
            raise ValueError("scheduled_at is required when schedule_type is 'once'")
        if self.schedule_type == PromotionalScheduleType.DAILY and (
            self.send_hour is None or self.send_minute is None
        ):
            raise ValueError("send_hour and send_minute are required when schedule_type is 'daily'")
        if self.schedule_type == PromotionalScheduleType.INTERVAL_HOURS and self.interval_hours is None:
            raise ValueError("interval_hours is required when schedule_type is 'interval_hours'")
        return self


class PromotionalCampaignRead(BaseModel):
    id: UUID
    title: str
    body: str
    schedule_type: PromotionalScheduleType
    scheduled_at: Optional[datetime] = None
    send_hour: Optional[int] = None
    send_minute: Optional[int] = None
    interval_hours: Optional[int] = None
    send_push: bool
    send_email: bool
    is_active: bool
    last_sent_at: Optional[datetime] = None
    last_recipient_count: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PromotionalCampaignSetActiveRequest(BaseModel):
    is_active: bool
