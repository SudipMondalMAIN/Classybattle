"""
Game Modes API routes (Phase 3).

Read APIs are public; create/update/delete are restricted to Admins.
"""
import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import require_admin
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.game_mode import (
    GameModeCreate,
    GameModeListItem,
    GameModeRead,
    GameModeUpdate,
    PaginatedGameModes,
)
from app.services.game_mode_service import GameModeService

router = APIRouter(prefix="/game-modes", tags=["Game Modes"])


@router.post("", response_model=GameModeRead, status_code=201)
async def create_game_mode(
    payload: GameModeCreate,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = GameModeService(session)
    mode = await service.create_mode(payload, current_user)
    return GameModeRead.model_validate(mode)


@router.get("", response_model=PaginatedGameModes)
async def list_game_modes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    game_id: Optional[UUID] = Query(None),
    is_active: Optional[bool] = Query(None),
    is_featured: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    sort_by: str = Query("sort_order", pattern="^(?i)(sort_order|name|created_at)$"),
    sort_order: str = Query("asc", pattern="^(?i)(asc|desc)$"),
    session: AsyncSession = Depends(get_db_session),
):
    service = GameModeService(session)
    items, total = await service.list_modes(
        page=page,
        page_size=page_size,
        game_id=game_id,
        is_active=is_active,
        is_featured=is_featured,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedGameModes(
        items=[GameModeListItem.model_validate(m) for m in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/slug/{game_id}/{slug}", response_model=GameModeRead)
async def get_game_mode_by_slug(
    game_id: UUID,
    slug: str,
    session: AsyncSession = Depends(get_db_session),
):
    service = GameModeService(session)
    mode = await service.get_by_slug(game_id, slug)
    return GameModeRead.model_validate(mode)


@router.get("/{mode_id}", response_model=GameModeRead)
async def get_game_mode(
    mode_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = GameModeService(session)
    mode = await service.get_by_id(mode_id)
    return GameModeRead.model_validate(mode)


@router.patch("/{mode_id}", response_model=GameModeRead)
async def update_game_mode(
    mode_id: UUID,
    payload: GameModeUpdate,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = GameModeService(session)
    mode = await service.update_mode(mode_id, payload, current_user)
    return GameModeRead.model_validate(mode)


@router.delete("/{mode_id}", response_model=MessageResponse)
async def delete_game_mode(
    mode_id: UUID,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = GameModeService(session)
    await service.soft_delete_mode(mode_id, current_user)
    return MessageResponse(message="Game mode deleted successfully")
