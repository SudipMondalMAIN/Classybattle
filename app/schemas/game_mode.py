"""
Game Mode Pydantic schemas (Phase 3).
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GameModeCreate(BaseModel):
    game_id: UUID
    name: str = Field(..., min_length=2, max_length=100)
    short_name: Optional[str] = Field(None, max_length=30)
    description: Optional[str] = Field(None, max_length=2000)
    icon_url: Optional[str] = Field(None, max_length=500)
    image_url: Optional[str] = Field(None, max_length=500)
    max_team_size: int = Field(default=1, gt=0, le=100)
    min_players: int = Field(default=1, gt=0, le=100000)
    max_players: int = Field(default=1, gt=0, le=100000)
    sort_order: int = Field(default=0, ge=0)
    is_active: bool = True
    is_featured: bool = False

    @model_validator(mode="after")
    def validate_player_limits(self) -> "GameModeCreate":
        if self.max_players < self.min_players:
            raise ValueError("max_players cannot be less than min_players")
        return self


class GameModeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    short_name: Optional[str] = Field(None, max_length=30)
    description: Optional[str] = Field(None, max_length=2000)
    icon_url: Optional[str] = Field(None, max_length=500)
    image_url: Optional[str] = Field(None, max_length=500)
    max_team_size: Optional[int] = Field(None, gt=0, le=100)
    min_players: Optional[int] = Field(None, gt=0, le=100000)
    max_players: Optional[int] = Field(None, gt=0, le=100000)
    sort_order: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None
    is_featured: Optional[bool] = None


class GameModeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mode_uid: str
    game_id: UUID
    name: str
    slug: str
    short_name: Optional[str] = None
    description: Optional[str] = None
    icon_url: Optional[str] = None
    image_url: Optional[str] = None
    max_team_size: int
    min_players: int
    max_players: int
    sort_order: int
    is_active: bool
    is_featured: bool
    created_by: Optional[UUID] = None
    updated_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


class GameModeListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mode_uid: str
    game_id: UUID
    name: str
    slug: str
    short_name: Optional[str] = None
    icon_url: Optional[str] = None
    max_team_size: int
    min_players: int
    max_players: int
    sort_order: int
    is_active: bool
    is_featured: bool


class PaginatedGameModes(BaseModel):
    items: list[GameModeListItem]
    total: int
    page: int
    page_size: int
    total_pages: int
