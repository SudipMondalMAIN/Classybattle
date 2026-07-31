"""
Live Match & Real-Time Tournament Pydantic schemas — Phase 12.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.live_match import (
    LiveMatchEventType,
    LiveMatchStatus,
    LiveTournamentStatus,
)


# ----------------------------------------------------------------------
# Live Match
# ----------------------------------------------------------------------
class LiveMatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    match_id: UUID
    tournament_id: UUID
    status: LiveMatchStatus
    current_round: int
    round_timer_seconds: Optional[int]
    round_started_at: Optional[datetime]
    started_at: Optional[datetime]
    paused_at: Optional[datetime]
    total_paused_seconds: int
    ended_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class LiveMatchStatusRead(LiveMatchRead):
    """Adds computed real-time timer fields on top of the raw row."""

    elapsed_seconds: int
    is_live: bool


class RoundTimerUpdate(BaseModel):
    round_number: int = Field(..., gt=0)
    round_timer_seconds: Optional[int] = Field(None, ge=0)


class TeamScoreUpdate(BaseModel):
    team_id: UUID
    kills: Optional[int] = Field(None, ge=0)
    score: Optional[int] = Field(None, ge=0)
    score_delta: Optional[int] = Field(None, description="Applied additively if set")
    extra_stats: Optional[dict] = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "TeamScoreUpdate":
        if self.kills is None and self.score is None and self.score_delta is None:
            raise ValueError("At least one of kills, score or score_delta must be provided")
        return self


class PlayerScoreUpdate(BaseModel):
    participant_id: UUID
    kills: Optional[int] = Field(None, ge=0)
    score: Optional[int] = Field(None, ge=0)
    score_delta: Optional[int] = None
    extra_stats: Optional[dict] = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "PlayerScoreUpdate":
        if self.kills is None and self.score is None and self.score_delta is None:
            raise ValueError("At least one of kills, score or score_delta must be provided")
        return self


class LiveMatchScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    match_id: UUID
    team_id: Optional[UUID]
    participant_id: Optional[UUID]
    kills: int
    score: int
    rank: Optional[int]
    extra_stats: Optional[dict]
    last_updated_at: Optional[datetime]


class LiveLeaderboardRead(BaseModel):
    match_id: UUID
    entries: list[LiveMatchScoreRead]


class LiveMatchStatsRead(BaseModel):
    match_id: UUID
    status: LiveMatchStatus
    elapsed_seconds: int
    current_round: int
    total_kills: int
    total_events: int
    participants_or_teams_tracked: int
    top_scorer: Optional[LiveMatchScoreRead]


# ----------------------------------------------------------------------
# Events / Timeline / Activity feed
# ----------------------------------------------------------------------
class LogEventRequest(BaseModel):
    event_type: LiveMatchEventType
    round_number: Optional[int] = Field(None, gt=0)
    team_id: Optional[UUID] = None
    participant_id: Optional[UUID] = None
    message: Optional[str] = Field(None, max_length=500)
    event_metadata: Optional[dict] = None
    client_event_id: Optional[str] = Field(
        None, max_length=100, description="Client-generated token to prevent duplicate logging"
    )


class LiveMatchEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    match_id: UUID
    sequence: int
    event_type: LiveMatchEventType
    round_number: Optional[int]
    team_id: Optional[UUID]
    participant_id: Optional[UUID]
    message: Optional[str]
    event_metadata: Optional[dict]
    created_at: datetime


class PaginatedLiveMatchEvents(BaseModel):
    items: list[LiveMatchEventRead]
    total: int
    page: int
    page_size: int
    total_pages: int


class PaginatedLiveMatches(BaseModel):
    items: list[LiveMatchStatusRead]
    total: int
    page: int
    page_size: int
    total_pages: int


# ----------------------------------------------------------------------
# Live Tournament
# ----------------------------------------------------------------------
class LiveTournamentStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tournament_id: UUID
    status: LiveTournamentStatus
    current_round: int
    total_rounds: Optional[int]
    total_matches: int
    live_matches: int
    completed_matches: int
    last_progressed_at: Optional[datetime]


class LiveTournamentProgressRead(LiveTournamentStateRead):
    current_round_matches_total: int
    current_round_matches_completed: int
    progress_percent: float
