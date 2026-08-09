"""
Slot join API routes -- the user-facing "join this tournament slot" action.
No registration step: joining debits the wallet and occupies a seat
immediately. Room ID/password become visible via
GET /tournaments/{tournament_id}/room once the admin publishes them.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user, require_can_play
from app.models.game_profile import UserGameProfile
from app.models.user import User
from app.repositories.game_repository import UserGameProfileRepository
from app.repositories.tournament_repository import TournamentRepository
from app.schemas.slot_join import (
    SlotJoinSoloRequest,
    SlotJoinTeamRequest,
    TournamentParticipantRead,
    TournamentTeamRead,
)
from app.services.slot_join_service import SlotJoinService

router = APIRouter(tags=["Slot Join"])


async def _resolve_game_profile(
    session: AsyncSession, tournament_id: UUID, profile_id: Optional[UUID], user: User
) -> UserGameProfile:
    """If the frontend passed a profile_id, use it (must belong to the
    user). Otherwise auto-look-up an already-saved profile for this
    slot's game -- so a returning player is never asked to re-enter
    their nickname/UID."""
    profile_repo = UserGameProfileRepository(session)
    if profile_id is not None:
        profile = await profile_repo.get_by_id(profile_id)
        if profile is None or profile.user_id != user.id:
            raise NotFoundException("Game profile not found")
        return profile

    tournament = await TournamentRepository(session).get_by_id(tournament_id)
    if tournament is None:
        raise NotFoundException("Tournament slot not found")

    profile = await profile_repo.get_by_user_and_game(user.id, tournament.game_id)
    if profile is None:
        raise ValidationException(
            "GAME_PROFILE_REQUIRED: Save your in-game nickname + UID for this game first "
            "(POST /games/profiles), then join again."
        )
    return profile


@router.post(
    "/tournaments/{tournament_id}/join/solo",
    response_model=TournamentParticipantRead,
    status_code=201,
)
async def join_slot_solo(
    tournament_id: UUID,
    payload: SlotJoinSoloRequest,
    current_user: User = Depends(require_can_play),
    session: AsyncSession = Depends(get_db_session),
):
    """Join a Classic/Battle-Royale style slot (Free Fire Classic, BGMI
    Classic/Squad) -- instant, wallet-debited, no team needed."""
    game_profile = await _resolve_game_profile(
        session, tournament_id, payload.game_profile_id, current_user
    )
    service = SlotJoinService(session)
    slot = await service.join_solo(tournament_id, current_user, game_profile)
    return TournamentParticipantRead.model_validate(slot)


@router.post(
    "/tournaments/{tournament_id}/join/team",
    response_model=TournamentTeamRead,
    status_code=201,
)
async def join_slot_team(
    tournament_id: UUID,
    payload: SlotJoinTeamRequest,
    current_user: User = Depends(require_can_play),
    session: AsyncSession = Depends(get_db_session),
):
    """Join a Clash-Squad style slot (1v1/2v2/3v3/4v4) -- create a team
    (get an invite code to share), join a friend's team via their invite
    code, or get randomly matched with other solo joiners."""
    game_profile = await _resolve_game_profile(
        session, tournament_id, payload.game_profile_id, current_user
    )
    service = SlotJoinService(session)
    tournament_team = await service.join_team(
        tournament_id,
        current_user,
        game_profile,
        team_format=payload.team_format,
        invite_code=payload.invite_code,
        join_random=payload.join_random,
    )
    return TournamentTeamRead.model_validate(tournament_team)