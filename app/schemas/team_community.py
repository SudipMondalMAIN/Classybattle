"""
Team Community System Pydantic schemas — Phase 15B.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.team_community import (
    TeamActivityType,
    TeamInvitationStatus,
    TeamJoinRequestStatus,
)


# ----------------------------------------------------------------------
# Invitations
# ----------------------------------------------------------------------
class TeamInvitationCreate(BaseModel):
    invitee_id: UUID
    message: Optional[str] = Field(None, max_length=500)


class TeamInvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    tournament_id: UUID
    inviter_id: UUID
    invitee_id: UUID
    status: TeamInvitationStatus
    message: Optional[str] = None
    created_at: datetime
    responded_at: Optional[datetime] = None


class PaginatedTeamInvitations(BaseModel):
    items: list[TeamInvitationRead]
    total: int
    page: int
    page_size: int
    total_pages: int


# ----------------------------------------------------------------------
# Join Requests
# ----------------------------------------------------------------------
class TeamJoinRequestCreate(BaseModel):
    message: Optional[str] = Field(None, max_length=500)


class TeamJoinRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    tournament_id: UUID
    user_id: UUID
    status: TeamJoinRequestStatus
    message: Optional[str] = None
    reviewed_by_id: Optional[UUID] = None
    created_at: datetime
    responded_at: Optional[datetime] = None


class PaginatedTeamJoinRequests(BaseModel):
    items: list[TeamJoinRequestRead]
    total: int
    page: int
    page_size: int
    total_pages: int


# ----------------------------------------------------------------------
# Announcements
# ----------------------------------------------------------------------
class TeamAnnouncementCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    content: str = Field(..., min_length=1, max_length=2000)
    is_pinned: bool = False


class TeamAnnouncementUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=200)
    content: Optional[str] = Field(None, min_length=1, max_length=2000)
    is_pinned: Optional[bool] = None


class TeamAnnouncementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    author_id: Optional[UUID] = None
    title: str
    content: str
    is_pinned: bool
    created_at: datetime
    updated_at: datetime


class PaginatedTeamAnnouncements(BaseModel):
    items: list[TeamAnnouncementRead]
    total: int
    page: int
    page_size: int
    total_pages: int


# ----------------------------------------------------------------------
# Activity Feed / Member History / Event History
# ----------------------------------------------------------------------
class TeamActivityFeedEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    actor_id: Optional[UUID] = None
    activity_type: TeamActivityType
    title: str
    meta_data: Optional[dict] = None
    created_at: datetime


class PaginatedTeamActivityFeed(BaseModel):
    items: list[TeamActivityFeedEntryRead]
    total: int
    page: int
    page_size: int
    total_pages: int
