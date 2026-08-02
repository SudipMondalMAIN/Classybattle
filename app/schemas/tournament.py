"""
Tournament Pydantic schemas.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.tournament import TeamRegistrationMode, TournamentStatus, TournamentVisibility


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
    registration_start: datetime
    registration_end: datetime
    tournament_start: datetime
    tournament_end: datetime
    visibility: TournamentVisibility = TournamentVisibility.PUBLIC
    is_featured: bool = False
    registration_mode: TeamRegistrationMode = TeamRegistrationMode.SOLO
    team_size: int = Field(default=1, gt=0, le=100)
    max_teams: Optional[int] = Field(None, gt=0)

    @model_validator(mode="after")
    def validate_windows(self) -> "TournamentCreate":
        if self.registration_end <= self.registration_start:
            raise ValueError("registration_end must be after registration_start")
        if self.tournament_end <= self.tournament_start:
            raise ValueError("tournament_end must be after tournament_start")
        if self.tournament_start < self.registration_start:
            raise ValueError("tournament_start cannot be before registration_start")
        if self.registration_mode == TeamRegistrationMode.SOLO and self.team_size != 1:
            raise ValueError("team_size must be 1 when registration_mode is 'solo'")
        if self.registration_mode != TeamRegistrationMode.SOLO and self.team_size < 2:
            raise ValueError(
                "team_size must be at least 2 for 'team_invite' or 'auto_random' modes"
            )
        return self


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
    registration_start: Optional[datetime] = None
    registration_end: Optional[datetime] = None
    tournament_start: Optional[datetime] = None
    tournament_end: Optional[datetime] = None
    visibility: Optional[TournamentVisibility] = None
    is_featured: Optional[bool] = None
    max_teams: Optional[int] = Field(None, gt=0)
    # registration_mode and team_size are intentionally NOT editable here once
    # a tournament has any teams/participants attached — see
    # TournamentService.update_tournament, which blocks changing them after
    # registration has started to avoid corrupting existing teams.


class TournamentStatusUpdate(BaseModel):
    status: TournamentStatus


class TournamentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
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
    registration_start: datetime
    registration_end: datetime
    tournament_start: datetime
    tournament_end: datetime
    status: TournamentStatus
    visibility: TournamentVisibility
    is_featured: bool
    registration_mode: TeamRegistrationMode
    team_size: int
    max_teams: Optional[int] = None
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
    tournament_start: datetime
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