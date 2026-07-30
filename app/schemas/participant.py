"""
Participant Pydantic schemas — Tournament Registration (Phase 5).
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.participant import (
    ParticipantPaymentStatus,
    ParticipantStatus,
    RegistrationType,
)


class ParticipantRegister(BaseModel):
    game_profile_id: UUID
    registration_type: RegistrationType = RegistrationType.SOLO
    team_name: Optional[str] = Field(None, min_length=2, max_length=150)


class ParticipantStatusUpdate(BaseModel):
    status: ParticipantStatus


class ParticipantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    participant_uid: str
    tournament_id: UUID
    user_id: UUID
    game_profile_id: UUID
    registration_type: RegistrationType
    team_name: Optional[str] = None
    status: ParticipantStatus
    payment_status: ParticipantPaymentStatus
    payment_reference: Optional[str] = None
    entry_fee_paid: Decimal
    joined_at: datetime
    cancelled_at: Optional[datetime] = None
    checked_in_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ParticipantListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    participant_uid: str
    tournament_id: UUID
    user_id: UUID
    registration_type: RegistrationType
    team_name: Optional[str] = None
    status: ParticipantStatus
    payment_status: ParticipantPaymentStatus
    joined_at: datetime
    checked_in_at: Optional[datetime] = None


class ParticipantOrganizerView(ParticipantListItem):
    game_profile_id: UUID
    payment_reference: Optional[str] = None
    entry_fee_paid: Decimal
    cancelled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class PaginatedParticipants(BaseModel):
    items: list[ParticipantListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class PaginatedParticipantsOrganizer(BaseModel):
    items: list[ParticipantOrganizerView]
    total: int
    page: int
    page_size: int
    total_pages: int
