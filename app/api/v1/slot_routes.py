"""
Slot join API routes — the user-facing "join this match" action.
No registration step: joining debits the wallet and occupies a seat
immediately. Room ID/password become visible via the existing
GET /matches/{match_id}/room endpoint once the admin publishes them.
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user
from app.models.game_profile import UserGameProfile
from app.models.user import User
from app.repositories.game_repository import UserGameProfileRepository
from app.core.exceptions import NotFoundException
from app.schemas.match import MatchParticipantRead
from app.schemas.slot_join import MatchTeamRead, SlotJoinSoloRequest, SlotJoinTeamRequest
from app.services.slot_join_service import SlotJoinService

router = APIRouter(tags=["Slot Join"])


async def _get_owned_game_profile(
    session: AsyncSession, profile_id: UUID, user: User
) -> UserGameProfile:
    profile = await UserGameProfileRepository(session).get_by_id(profile_id)
    if profile is None or profile.user_id != user.id:
        raise NotFoundException("Game profile not found")
    return profile


@router.post("/matches/{match_id}/join/solo", response_model=MatchParticipantRead, status_code=201)
async def join_slot_solo(
    match_id: UUID,
    payload: SlotJoinSoloRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Join a Classic/Battle-Royale style slot (Free Fire Classic, BGMI
    Classic/Squad) — instant, wallet-debited, no team needed."""
    game_profile = await _get_owned_game_profile(session, payload.game_profile_id, current_user)
    service = SlotJoinService(session)
    slot = await service.join_solo(match_id, current_user, game_profile)
    return MatchParticipantRead.model_validate(slot)


@router.post("/matches/{match_id}/join/team", response_model=MatchTeamRead, status_code=201)
async def join_slot_team(
    match_id: UUID,
    payload: SlotJoinTeamRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Join a Clash-Squad style slot (1v1/2v2/3v3/4v4) — create a team
    (get an invite code to share), join a friend's team via their invite
    code, or get randomly matched with other solo joiners."""
    game_profile = await _get_owned_game_profile(session, payload.game_profile_id, current_user)
    service = SlotJoinService(session)
    match_team = await service.join_team(
        match_id,
        current_user,
        game_profile,
        mode=payload.mode,
        team_name=payload.team_name,
        invite_code=payload.invite_code,
    )
    return MatchTeamRead.model_validate(match_team)
