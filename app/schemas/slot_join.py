"""
Slot-join schemas -- joining a generated recurring-schedule Tournament
slot (solo or as a per-slot TournamentTeam).
"""
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.tournament_participant import TournamentCheckInStatus
from app.models.tournament_team import TournamentTeamStatus


class SlotJoinSoloRequest(BaseModel):
    game_profile_id: Optional[UUID] = None


class SlotJoinTeamRequest(BaseModel):
    game_profile_id: Optional[UUID] = None
    team_format: Optional[str] = None
    invite_code: Optional[str] = Field(None, min_length=1, max_length=16)
    join_random: bool = False


class TournamentParticipantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tournament_id: UUID
    participant_id: Optional[UUID] = None
    tournament_team_id: Optional[UUID] = None
    slot_number: int
    check_in_status: TournamentCheckInStatus


class TournamentTeamRead(BaseModel):
    """A join-able per-slot team, as shown to users."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tournament_id: UUID
    team_name: Optional[str] = None
    invite_code: str
    team_format: str
    team_size: int
    current_members: int
    is_random: bool
    status: TournamentTeamStatus