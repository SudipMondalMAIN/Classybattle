"""
Notification Pydantic schemas — Phase 13 (Enterprise Notification & Communication System).
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.notification import NotificationChannel, NotificationEventType, NotificationStatus


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    title: str
    body: str
    channel: NotificationChannel
    status: NotificationStatus
    event_type: NotificationEventType
    is_read: bool
    read_at: Optional[datetime] = None
    meta_data: Optional[dict] = None
    created_at: datetime


class PaginatedNotifications(BaseModel):
    items: list[NotificationRead]
    total: int
    page: int
    page_size: int
    total_pages: int


class UnreadCountResponse(BaseModel):
    unread_count: int


class MarkReadResponse(BaseModel):
    success: bool = True
    marked: int = 1


class BulkDeleteRequest(BaseModel):
    notification_ids: list[UUID] = Field(..., min_length=1, max_length=200)


class BulkDeleteResponse(BaseModel):
    success: bool = True
    deleted: int


class NotificationPreferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    in_app_enabled: bool
    push_enabled: bool
    email_enabled: bool


class NotificationPreferenceUpdate(BaseModel):
    in_app_enabled: Optional[bool] = None
    push_enabled: Optional[bool] = None
    email_enabled: Optional[bool] = None


class DeviceTokenRegisterRequest(BaseModel):
    fcm_token: str = Field(..., min_length=10, max_length=500)
    platform: str = "android"


class DeviceTokenDeregisterRequest(BaseModel):
    fcm_token: str = Field(..., min_length=10, max_length=500)


# ----------------------------------------------------------------------
# Admin
# ----------------------------------------------------------------------
class AdminBroadcastRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1, max_length=1000)
    target_user_ids: Optional[list[UUID]] = Field(
        default=None, description="Specific recipients; omit to broadcast to all active users"
    )
    send_push: bool = True
    send_email: bool = False


class AdminBroadcastResponse(BaseModel):
    success: bool = True
    recipients: int
