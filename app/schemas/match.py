"""
Match, Room & Check-in Pydantic schemas — Room Management & Match
Lifecycle (Phase 7).
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.match import MatchStatus, RoomStatus
from app.models.match_participant import MatchAssignmentType, MatchCheckInStatus


# ----------------------------------------------------------------------
# Match
# ----------------------------------------------------------------------
class MatchCreate(BaseModel):
    round_number: int = Field(1, gt=0)
    match_number: Optional[int] = Field(
        None, gt=0, description="Auto-assigned within the round when omitted"
    )
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    check_in_opens_at: Optional[datetime] = None
    check_in_deadline: Optional[datetime] = None
    auto_disqualify_on_no_show: bool = True
    notes: Optional[str] = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _validate_windows(self) -> "MatchCreate":
        if (
            self.scheduled_start is not None
            and self.scheduled_end is not None
            and self.scheduled_end <= self.scheduled_start
        ):
            raise ValueError("scheduled_end must be after scheduled_start")
        if (
            self.check_in_opens_at is not None
            and self.check_in_deadline is not None
            and self.check_in_deadline <= self.check_in_opens_at
        ):
            raise ValueError("check_in_deadline must be after check_in_opens_at")
        return self


class MatchUpdate(BaseModel):
    notes: Optional[str] = Field(None, max_length=2000)
    auto_disqualify_on_no_show: Optional[bool] = None


class MatchSchedule(BaseModel):
    scheduled_start: datetime
    scheduled_end: datetime
    check_in_opens_at: Optional[datetime] = None
    check_in_deadline: Optional[datetime] = None

    @model_validator(mode="after")
    def _validate_windows(self) -> "MatchSchedule":
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("scheduled_end must be after scheduled_start")
        if (
            self.check_in_opens_at is not None
            and self.check_in_deadline is not None
            and self.check_in_deadline <= self.check_in_opens_at
        ):
            raise ValueError("check_in_deadline must be after check_in_opens_at")
        return self


class MatchStatusUpdate(BaseModel):
    match_status: MatchStatus


class MatchResultUpdate(BaseModel):
    winner_team_id: Optional[UUID] = None
    notes: Optional[str] = Field(None, max_length=2000)


# ----------------------------------------------------------------------
# Room
# ----------------------------------------------------------------------
class RoomCreate(BaseModel):
    room_name: Optional[str] = Field(None, max_length=150)
    room_id: str = Field(..., min_length=1, max_length=100)
    room_password: str = Field(..., min_length=1, max_length=100)


class RoomUpdate(BaseModel):
    room_name: Optional[str] = Field(None, max_length=150)
    room_id: Optional[str] = Field(None, min_length=1, max_length=100)
    room_password: Optional[str] = Field(None, min_length=1, max_length=100)


# ----------------------------------------------------------------------
# Match team assignment
# ----------------------------------------------------------------------
class AssignTeamRequest(BaseModel):
    team_id: UUID
    slot_number: Optional[int] = Field(None, gt=0)


class AssignParticipantRequest(BaseModel):
    participant_id: UUID
    slot_number: Optional[int] = Field(None, gt=0)


class AutoAssignMatchRequest(BaseModel):
    seed: Optional[int] = None


class ReplaceSlotRequest(BaseModel):
    new_team_id: Optional[UUID] = None
    new_participant_id: Optional[UUID] = None

    @model_validator(mode="after")
    def _validate_one_target(self) -> "ReplaceSlotRequest":
        if (self.new_team_id is None) == (self.new_participant_id is None):
            raise ValueError(
                "Exactly one of new_team_id or new_participant_id must be provided"
            )
        return self


# ----------------------------------------------------------------------
# Check-in
# ----------------------------------------------------------------------
class CheckInRequest(BaseModel):
    team_id: Optional[UUID] = None
    participant_id: Optional[UUID] = None

    @model_validator(mode="after")
    def _validate_one_target(self) -> "CheckInRequest":
        if (self.team_id is None) == (self.participant_id is None):
            raise ValueError("Exactly one of team_id or participant_id must be provided")
        return self


class OrganizerCheckInOverride(BaseModel):
    slot_id: UUID
    check_in_status: MatchCheckInStatus


class NoShowOverride(BaseModel):
    slot_id: UUID
    is_disqualified: bool = True
    reason: Optional[str] = Field(None, max_length=255)


# ----------------------------------------------------------------------
# Read models
# ----------------------------------------------------------------------
class MatchParticipantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    match_id: UUID
    team_id: Optional[UUID] = None
    participant_id: Optional[UUID] = None
    slot_number: int
    assignment_type: MatchAssignmentType
    check_in_status: MatchCheckInStatus
    checked_in_at: Optional[datetime] = None
    is_organizer_override: bool
    is_disqualified: bool
    disqualified_reason: Optional[str] = None
    created_at: datetime


class MatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    match_uid: str
    tournament_id: UUID
    round_number: int
    match_number: int
    room_name: Optional[str] = None
    room_status: RoomStatus
    match_status: MatchStatus
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    check_in_opens_at: Optional[datetime] = None
    check_in_deadline: Optional[datetime] = None
    auto_disqualify_on_no_show: bool
    winner_team_id: Optional[UUID] = None
    notes: Optional[str] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    # Room credentials are intentionally excluded here — see
    # MatchRoomRead, only ever returned once the room is published.


class MatchRoomRead(BaseModel):
    """Includes room_id/room_password — only ever built by the service
    once room_status == PUBLISHED, for organizers, or for a caller who is
    an assigned participant of the match."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    match_uid: str
    room_name: Optional[str] = None
    room_id: Optional[str] = None
    room_password: Optional[str] = None
    room_status: RoomStatus
    room_published_at: Optional[datetime] = None
    match_status: MatchStatus


class MatchReadWithSlots(MatchRead):
    slots: list[MatchParticipantRead] = Field(default_factory=list)


class PaginatedMatches(BaseModel):
    items: list[MatchRead]
    total: int
    page: int
    page_size: int
    total_pages: int
