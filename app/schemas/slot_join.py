"""
Slot join Pydantic schemas — the user-facing "pick a time slot and
join" flow (no registration, wallet debit at join time).
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.match import MatchStatus, RoomStatus
from app.services.slot_join_service import SlotJoinMode


class SlotJoinSoloRequest(BaseModel):
    game_profile_id: UUID


class SlotJoinTeamRequest(BaseModel):
    game_profile_id: UUID
    mode: SlotJoinMode
    team_name: Optional[str] = Field(None, min_length=2, max_length=150)
    invite_code: Optional[str] = Field(None, min_length=4, max_length=16)


class SlotRead(BaseModel):
    """A join-able Match slot, as shown to users browsing today's schedule."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tournament_id: UUID
    match_number: int
    team_format: Optional[str] = None
    entry_fee: Optional[float] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    match_status: MatchStatus
    room_status: RoomStatus


class MatchTeamRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    match_id: UUID
    team_name: Optional[str] = None
    captain_id: Optional[UUID] = None
    invite_code: str
    team_format: str
    team_size: int
    current_members: int
    is_random: bool
    status: str
