"""
Moderation Pydantic schemas — Phase 15C.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.moderation import (
    AppealStatus,
    ModerationActionStatus,
    ModerationActionType,
    ReportReason,
    ReportStatus,
    ReportTargetType,
)


class ReportCreate(BaseModel):
    target_type: ReportTargetType
    target_id: UUID
    reason: ReportReason
    description: Optional[str] = Field(None, max_length=2000)
    evidence_urls: Optional[list[str]] = None


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    short_id: int
    reporter_id: UUID
    target_type: ReportTargetType
    target_id: UUID
    reason: ReportReason
    description: Optional[str] = None
    status: ReportStatus
    reviewed_by_id: Optional[UUID] = None
    reviewed_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    created_at: datetime


class PaginatedReports(BaseModel):
    items: list[ReportRead]
    total: int
    page: int
    page_size: int


class ReportReviewRequest(BaseModel):
    status: ReportStatus
    resolution_notes: Optional[str] = Field(None, max_length=2000)


class ModerationActionCreate(BaseModel):
    user_id: UUID
    action_type: ModerationActionType
    reason: str = Field(..., min_length=1, max_length=1000)
    report_id: Optional[UUID] = None
    duration_hours: Optional[int] = Field(None, gt=0)


class ModerationActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    short_id: int
    user_id: UUID
    action_type: ModerationActionType
    status: ModerationActionStatus
    reason: str
    report_id: Optional[UUID] = None
    issued_by_id: Optional[UUID] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime


class PaginatedModerationActions(BaseModel):
    items: list[ModerationActionRead]
    total: int
    page: int
    page_size: int


class ModerationActionRevokeRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=1000)


class AppealCreate(BaseModel):
    moderation_action_id: UUID
    message: str = Field(..., min_length=1, max_length=2000)


class AppealRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    moderation_action_id: UUID
    user_id: UUID
    message: str
    status: AppealStatus
    reviewed_by_id: Optional[UUID] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    created_at: datetime


class PaginatedAppeals(BaseModel):
    items: list[AppealRead]
    total: int
    page: int
    page_size: int


class AppealReviewRequest(BaseModel):
    approve: bool
    review_notes: Optional[str] = Field(None, max_length=2000)
