"""
Notification Pydantic schemas.
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.notification import NotificationChannel, NotificationStatus


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    body: str
    channel: NotificationChannel
    status: NotificationStatus
    is_read: bool
    created_at: datetime


class DeviceTokenRegisterRequest(BaseModel):
    fcm_token: str
    platform: str = "android"
