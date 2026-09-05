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
    short_id: int
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
    short_id: int
    participant_uid: str
    tournament_id: UUID
    tournament_title: Optional[str] = None
    user_id: UUID
    registration_type: RegistrationType
    team_name: Optional[str] = None
    status: ParticipantStatus
    payment_status: ParticipantPaymentStatus
    joined_at: datetime
    checked_in_at: Optional[datetime] = None

    @classmethod
    def model_validate(cls, obj, *args, **kwargs):  # type: ignore[override]
        # `tournament` is eagerly loaded (lazy="selectin") on Participant,
        # so we can pull the title in without an extra query/join.
        tournament = getattr(obj, "tournament", None)
        if tournament is not None and not isinstance(obj, dict):
            data = {c: getattr(obj, c) for c in cls.model_fields if c != "tournament_title"}
            data["tournament_title"] = getattr(tournament, "title", None)
            return super().model_validate(data, *args, **kwargs)
        return super().model_validate(obj, *args, **kwargs)


class ParticipantOrganizerView(ParticipantListItem):
    game_profile_id: UUID
    payment_reference: Optional[str] = None
    entry_fee_paid: Decimal
    cancelled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ParticipantPublicView(BaseModel):
    """Public participant card shown inside a tournament's details page.

    Combines the participant slot with the user's public identity
    (avatar/name/player_uid), the in-game profile used for this
    tournament's game (nickname/uid, taken from
    ``UserGameProfile.data``), and — once results exist — the outcome
    (rank / winner flag / prize amount) from the matching
    ``TournamentParticipant`` slot.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    participant_uid: str
    tournament_id: UUID
    registration_type: RegistrationType
    team_name: Optional[str] = None
    status: ParticipantStatus
    joined_at: datetime

    # Public user identity
    user_id: UUID
    full_name: str
    avatar_id: Optional[str] = None
    player_uid: str

    # In-game identity for this tournament's game (from UserGameProfile.data)
    ingame_nickname: Optional[str] = None
    ingame_uid: Optional[str] = None

    # Result — populated once the tournament has a declared outcome for
    # this participant (rank / winner / prize). All None until then.
    kills: Optional[int] = None
    is_winner: bool = False
    rank: Optional[int] = None
    winning_amount: Optional[Decimal] = None


class PaginatedParticipantsPublic(BaseModel):
    items: list[ParticipantPublicView]
    total: int
    page: int
    page_size: int
    total_pages: int


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