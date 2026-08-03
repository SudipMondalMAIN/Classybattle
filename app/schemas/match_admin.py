"""
Admin match-details page schemas — Raj's flow: Admin opens one match,
sees everyone who joined (with their in-game nickname + UID), enters
kills, declares winner(s), and pays out the winning amount directly
from this page.
"""
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MatchAdminPlayerRead(BaseModel):
    """One joined player — solo joiner, or one member of a squad team."""

    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    full_name: str
    phone_number: str
    game_nickname: Optional[str] = None
    game_uid: Optional[str] = None

    # Which slot they occupy — useful for squad matches (group teammates
    # together in the UI).
    team_name: Optional[str] = None
    team_id: Optional[UUID] = None

    kills: int = 0
    is_winner: bool = False
    winning_amount: Optional[Decimal] = None
    winning_paid_at: Optional[datetime] = None

    joined_at: datetime


class MatchAdminDetailRead(BaseModel):
    id: UUID
    short_id: int
    match_uid: str
    game_id: UUID
    game_name: str
    category: Optional[str] = None
    team_format: Optional[str] = None
    scheduled_start: Optional[datetime] = None
    match_status: str
    room_id: Optional[str] = None
    room_password: Optional[str] = None
    entry_fee: Optional[Decimal] = None
    prize_pool: Optional[Decimal] = None
    total_joined: int
    max_players: int
    players: list[MatchAdminPlayerRead]


class DeclareResultRequest(BaseModel):
    kills: Optional[int] = Field(None, ge=0)
    is_winner: Optional[bool] = None


class PayWinnerRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    note: Optional[str] = Field(None, max_length=255)
