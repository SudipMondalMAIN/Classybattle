"""
Schedule (recurring match template) Pydantic schemas.
"""
from datetime import datetime, time
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.tournament import TeamFormat

_VALID_FORMATS = {f.value for f in TeamFormat}


class ScheduleCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    game_id: UUID
    mode_id: Optional[UUID] = None
    organizer: str = Field(..., min_length=2, max_length=150)
    entry_fee: Decimal = Field(default=Decimal("0"), ge=0)
    max_players_per_slot: int = Field(..., gt=0, le=1000)
    daily_start_time: time
    daily_end_time: time
    slot_interval_minutes: int = Field(..., gt=0, le=180)
    allowed_team_formats: Optional[list[str]] = Field(
        default=None,
        description="e.g. ['1v1','2v2','3v3','4v4'] for Clash Squad, null/omit for solo modes",
    )

    @field_validator("allowed_team_formats")
    @classmethod
    def _validate_formats(cls, v):
        if v is None:
            return v
        invalid = [f for f in v if f not in _VALID_FORMATS]
        if invalid:
            raise ValueError(f"Invalid team format(s): {invalid}. Valid: {sorted(_VALID_FORMATS)}")
        return v


class ScheduleUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    entry_fee: Optional[Decimal] = Field(None, ge=0)
    max_players: Optional[int] = Field(None, gt=0, le=1000)
    daily_start_time: Optional[time] = None
    daily_end_time: Optional[time] = None
    slot_interval_minutes: Optional[int] = Field(None, gt=0, le=180)
    allowed_team_formats: Optional[list[str]] = None


class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    slug: str
    game_id: UUID
    mode_id: Optional[UUID] = None
    organizer: str
    entry_fee: Decimal
    max_players: int
    daily_start_time: Optional[time] = None
    daily_end_time: Optional[time] = None
    slot_interval_minutes: Optional[int] = None
    allowed_team_formats: Optional[list[str]] = None
    last_generated_on: Optional[datetime] = None


class GenerateSlotsRequest(BaseModel):
    target_date: Optional[datetime] = Field(
        default=None, description="Date to generate slots for (defaults to today, UTC)"
    )
