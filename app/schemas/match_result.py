"""
Match Result & Winner Management Pydantic schemas — Phase 11.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.match_result import MatchResultStatus
from app.models.match_winner import WinnerAssignmentSource


# ----------------------------------------------------------------------
# Result entries (per-slot score submitted for a match)
# ----------------------------------------------------------------------
class ResultEntry(BaseModel):
    """One slot's reported outcome. Exactly one of team_id / participant_id
    must be set, matching whichever slot type the match uses."""

    team_id: Optional[UUID] = None
    participant_id: Optional[UUID] = None
    score: float = Field(..., description="Higher is better; used for automatic ranking")
    placement: Optional[int] = Field(
        None, gt=0, description="Optional explicit placement override for this slot"
    )

    @model_validator(mode="after")
    def _exactly_one_entity(self) -> "ResultEntry":
        if (self.team_id is None) == (self.participant_id is None):
            raise ValueError("Exactly one of 'team_id' or 'participant_id' must be provided")
        return self


class MatchResultSubmit(BaseModel):
    result_data: list[ResultEntry] = Field(..., min_length=1)
    is_tie: bool = False
    notes: Optional[str] = Field(None, max_length=2000)

    @field_validator("result_data")
    @classmethod
    def _unique_entities(cls, entries: list[ResultEntry]) -> list[ResultEntry]:
        teams = [e.team_id for e in entries if e.team_id is not None]
        participants = [e.participant_id for e in entries if e.participant_id is not None]
        if len(teams) != len(set(teams)):
            raise ValueError("Duplicate team_id in result_data")
        if len(participants) != len(set(participants)):
            raise ValueError("Duplicate participant_id in result_data")
        return entries


class MatchResultUpdateRequest(BaseModel):
    result_data: Optional[list[ResultEntry]] = Field(None, min_length=1)
    is_tie: Optional[bool] = None
    notes: Optional[str] = Field(None, max_length=2000)


class MatchResultReject(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


# ----------------------------------------------------------------------
# Winner declaration (manual override)
# ----------------------------------------------------------------------
class WinnerEntry(BaseModel):
    rank: int = Field(..., gt=0)
    team_id: Optional[UUID] = None
    participant_id: Optional[UUID] = None
    is_tie: bool = False

    @model_validator(mode="after")
    def _exactly_one_entity(self) -> "WinnerEntry":
        if (self.team_id is None) == (self.participant_id is None):
            raise ValueError("Exactly one of 'team_id' or 'participant_id' must be provided")
        return self


class DeclareWinnersRequest(BaseModel):
    winners: list[WinnerEntry] = Field(..., min_length=1)

    @field_validator("winners")
    @classmethod
    def _unique_entities(cls, winners: list[WinnerEntry]) -> list[WinnerEntry]:
        teams = [w.team_id for w in winners if w.team_id is not None]
        participants = [w.participant_id for w in winners if w.participant_id is not None]
        if len(teams) != len(set(teams)):
            raise ValueError("Duplicate team_id in winners list")
        if len(participants) != len(set(participants)):
            raise ValueError("Duplicate participant_id in winners list")
        return winners


# ----------------------------------------------------------------------
# Read models
# ----------------------------------------------------------------------
class MatchResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    match_id: UUID
    tournament_id: UUID
    result_data: list[dict]
    is_tie: bool
    status: MatchResultStatus
    submitted_by: Optional[UUID] = None
    submitted_at: Optional[datetime] = None
    verified_by: Optional[UUID] = None
    verified_at: Optional[datetime] = None
    approved_by: Optional[UUID] = None
    approved_at: Optional[datetime] = None
    rejected_by: Optional[UUID] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    prize_distribution_triggered: bool
    prize_distribution_triggered_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PaginatedMatchResults(BaseModel):
    items: list[MatchResultRead]
    total: int
    page: int
    page_size: int
    total_pages: int


class MatchWinnerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    match_id: UUID
    match_result_id: UUID
    tournament_id: UUID
    team_id: Optional[UUID] = None
    participant_id: Optional[UUID] = None
    rank: int
    is_tie: bool
    assignment_source: WinnerAssignmentSource
    is_manual_override: bool
    declared_by: Optional[UUID] = None
    declared_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class PaginatedMatchWinners(BaseModel):
    items: list[MatchWinnerRead]
    total: int
    page: int
    page_size: int
    total_pages: int


# ----------------------------------------------------------------------
# History (backed by the existing audit trail)
# ----------------------------------------------------------------------
class AuditHistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    action: str
    actor_id: Optional[UUID] = None
    actor_type: str
    old_values: Optional[dict] = None
    new_values: Optional[dict] = None
    description: Optional[str] = None
    created_at: datetime
