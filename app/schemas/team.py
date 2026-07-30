"""
Team & Team Member Pydantic schemas — Team System (Phase 6).
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.team import TeamStatus
from app.models.team_member import TeamMemberRole


# ----------------------------------------------------------------------
# Team
# ----------------------------------------------------------------------
class TeamCreate(BaseModel):
    team_name: str = Field(..., min_length=2, max_length=150)


class TeamUpdate(BaseModel):
    team_name: Optional[str] = Field(None, min_length=2, max_length=150)


class TeamJoin(BaseModel):
    invite_code: str = Field(..., min_length=4, max_length=16)


class TeamLockUpdate(BaseModel):
    is_locked: bool


class TeamStatusUpdate(BaseModel):
    status: TeamStatus


class TransferCaptain(BaseModel):
    new_captain_user_id: UUID


class RemoveMember(BaseModel):
    user_id: UUID


class TeamMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    user_id: UUID
    participant_id: Optional[UUID] = None
    role: TeamMemberRole
    joined_at: datetime


class TeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_uid: str
    tournament_id: UUID
    team_name: str
    captain_id: Optional[UUID] = None
    invite_code: str
    team_size: int
    current_members: int
    status: TeamStatus
    is_locked: bool
    created_at: datetime
    updated_at: datetime


class TeamReadWithMembers(TeamRead):
    members: list[TeamMemberRead] = Field(default_factory=list)


class TeamListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_uid: str
    tournament_id: UUID
    team_name: str
    captain_id: Optional[UUID] = None
    team_size: int
    current_members: int
    status: TeamStatus
    is_locked: bool
    created_at: datetime


class PaginatedTeams(BaseModel):
    items: list[TeamListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# ----------------------------------------------------------------------
# Auto-random team assignment
# ----------------------------------------------------------------------
class AutoAssignRequest(BaseModel):
    """Optional overrides for the balanced auto-assignment run. When omitted
    the tournament's configured team_size is used."""

    team_size: Optional[int] = Field(None, gt=0, le=100)
    seed: Optional[int] = Field(
        None, description="Optional deterministic seed for reproducible shuffles"
    )


class AutoAssignResult(BaseModel):
    teams_created: int
    players_assigned: int
    unassigned_players: int
    teams: list[TeamReadWithMembers]
