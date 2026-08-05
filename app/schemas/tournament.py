"""
Tournament Pydantic schemas.

Match-refactor: Tournament is now the joinable/playable unit itself.
No registration_start/registration_end/tournament_start/tournament_end
windows -- join is instant while status == SCHEDULED and slots are
available. Room publish info (room_id/room_password/published_at/
auto_complete_at) lives directly on Tournament.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.tournament import (
    ScheduleCategory,
    TeamRegistrationMode,
    TournamentStatus,
    TournamentVisibility,
)


class TournamentCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    rules: Optional[str] = Field(None, max_length=5000)
    game_id: UUID
    mode_id: Optional[UUID] = None
    map_id: Optional[UUID] = None
    organizer: str = Field(..., min_length=2, max_length=150)
    entry_fee: Decimal = Field(default=Decimal("0"), ge=0)
    prize_pool: Decimal = Field(default=Decimal("0"), ge=0)
    max_players: int = Field(..., gt=0, le=100000)
    visibility: TournamentVisibility = TournamentVisibility.PUBLIC
    is_featured: bool = False
    registration_mode: TeamRegistrationMode = TeamRegistrationMode.SOLO
    team_size: int = Field(default=1, gt=0, le=100)
    max_teams: Optional[int] = Field(None, gt=0)

    # Recurring-schedule template config (optional -- only set when this
    # row is itself a daily-generating schedule template).
    is_recurring_schedule: bool = False
    daily_slot_times: Optional[list[str]] = None
    category: Optional[ScheduleCategory] = None
    squad_size: int = Field(default=4, gt=0, le=100)

    @staticmethod
    def _validate_team_size(registration_mode: TeamRegistrationMode, team_size: int) -> None:
        if registration_mode == TeamRegistrationMode.SOLO and team_size != 1:
            raise ValueError("team_size must be 1 when registration_mode is 'solo'")
        if registration_mode != TeamRegistrationMode.SOLO and team_size < 2:
            raise ValueError(
                "team_size must be at least 2 for 'team_invite' or 'auto_random' modes"
            )

    def model_post_init(self, __context) -> None:
        self._validate_team_size(self.registration_mode, self.team_size)


class TournamentUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    rules: Optional[str] = Field(None, max_length=5000)
    mode_id: Optional[UUID] = None
    map_id: Optional[UUID] = None
    organizer: Optional[str] = Field(None, min_length=2, max_length=150)
    entry_fee: Optional[Decimal] = Field(None, ge=0)
    prize_pool: Optional[Decimal] = Field(None, ge=0)
    max_players: Optional[int] = Field(None, gt=0, le=100000)
    visibility: Optional[TournamentVisibility] = None
    is_featured: Optional[bool] = None
    max_teams: Optional[int] = Field(None, gt=0)
    daily_slot_times: Optional[list[str]] = None
    # registration_mode and team_size are intentionally NOT editable here once
    # a tournament has any teams/participants attached -- see
    # TournamentService.update_tournament, which blocks changing them after
    # players have joined, to avoid corrupting existing teams.


class TournamentStatusUpdate(BaseModel):
    status: TournamentStatus


class TournamentPublishRoom(BaseModel):
    room_id: str = Field(..., min_length=1, max_length=100)
    room_password: str = Field(..., min_length=1, max_length=100)


class TournamentRoomRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    room_id: Optional[str] = None
    room_password: Optional[str] = None
    published_at: Optional[datetime] = None
    auto_complete_at: Optional[datetime] = None


class TournamentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    short_id: int
    tournament_uid: str
    title: str
    slug: str
    description: Optional[str] = None
    rules: Optional[str] = None
    game_id: UUID
    mode_id: Optional[UUID] = None
    map_id: Optional[UUID] = None
    banner_url: Optional[str] = None
    cover_url: Optional[str] = None
    organizer: str
    entry_fee: Decimal
    prize_pool: Decimal
    max_players: int
    current_players: int
    status: TournamentStatus
    visibility: TournamentVisibility
    is_featured: bool
    room_id: Optional[str] = None
    room_password: Optional[str] = None
    published_at: Optional[datetime] = None
    auto_complete_at: Optional[datetime] = None
    registration_mode: TeamRegistrationMode
    team_size: int
    max_teams: Optional[int] = None
    is_recurring_schedule: bool
    category: Optional[ScheduleCategory] = None
    squad_size: int
    daily_slot_times: Optional[list[str]] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


class TournamentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tournament_uid: str
    title: str
    slug: str
    game_id: UUID
    banner_url: Optional[str] = None
    entry_fee: Decimal
    prize_pool: Decimal
    max_players: int
    current_players: int
    status: TournamentStatus
    visibility: TournamentVisibility
    is_featured: bool
    registration_mode: TeamRegistrationMode
    team_size: int


class PaginatedTournaments(BaseModel):
    items: list[TournamentListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class TournamentAssetUploadResponse(BaseModel):
    url: str
