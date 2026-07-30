"""
Game catalogue + user game profile API routes.
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.game import (
    GameRead,
    UserGameProfileCreate,
    UserGameProfileRead,
    UserGameProfileUpdate,
)
from app.services.game_service import GameService

router = APIRouter(prefix="/games", tags=["Games"])


@router.get("", response_model=list[GameRead])
async def list_games(session: AsyncSession = Depends(get_db_session)):
    service = GameService(session)
    games = await service.list_active_games()
    return [GameRead.model_validate(g) for g in games]


@router.post("/profiles", response_model=UserGameProfileRead, status_code=201)
async def create_game_profile(
    payload: UserGameProfileCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = GameService(session)
    profile = await service.create_game_profile(current_user.id, payload)
    return UserGameProfileRead.model_validate(profile)


@router.patch("/{game_id}/profile", response_model=UserGameProfileRead)
async def update_game_profile(
    game_id: UUID,
    payload: UserGameProfileUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = GameService(session)
    profile = await service.update_game_profile(current_user.id, game_id, payload)
    return UserGameProfileRead.model_validate(profile)


@router.get("/profiles/me", response_model=list[UserGameProfileRead])
async def list_my_game_profiles(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = GameService(session)
    profiles = await service.list_user_game_profiles(current_user.id)
    return [UserGameProfileRead.model_validate(p) for p in profiles]
