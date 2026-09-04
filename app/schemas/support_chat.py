"""
Support chat Pydantic schemas.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.support_chat import (
    SupportChatClosedBy,
    SupportChatMessageType,
    SupportChatSenderType,
    SupportChatStatus,
)


class SupportChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    sender_type: SupportChatSenderType
    sender_id: Optional[UUID] = None
    content: str
    message_type: SupportChatMessageType = SupportChatMessageType.TEXT
    media_url: Optional[str] = None
    created_at: datetime


class SupportChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    agent_id: Optional[UUID] = None
    status: SupportChatStatus
    closed_by: Optional[SupportChatClosedBy] = None
    closed_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None
    created_at: datetime


class SupportChatSessionWithMessages(SupportChatSessionRead):
    messages: list[SupportChatMessageRead] = Field(default_factory=list)


class PaginatedSupportChatSessions(BaseModel):
    items: list[SupportChatSessionRead]
    total: int
    page: int
    page_size: int
    total_pages: int


class SupportChatSendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
