"""
Tournament Result schemas — formerly schemas/match_result.py.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class SubmitResultRequest(BaseModel):
    result_data: list[dict]
    is_tie: bool = False


class RejectResultRequest(BaseModel):
    reason: str


class TournamentWinnerRead(BaseModel):
    id: UUID
    tournament_id: UUID
    team_id: Optional[UUID] = None
    participant_id: Optional[UUID] = None
    rank: int
    is_tie: bool
    declared_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TournamentResultRead(BaseModel):
    id: UUID
    tournament_id: UUID
    result_data: list
    is_tie: bool
    status: str
    submitted_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    prize_distribution_triggered: bool

    class Config:
        from_attributes = True
