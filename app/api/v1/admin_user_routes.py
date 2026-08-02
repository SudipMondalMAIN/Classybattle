"""
Admin User Management API routes.

Lets Admin/Super Admin list and search all users (by email, phone number,
player_uid, or UUID), and inspect any user's friend list for support and
moderation purposes.
"""
import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.database.session import get_db_session
from app.dependencies.auth import require_admin
from app.models.participant import ParticipantStatus
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.user_repository import UserRepository
from app.schemas.participant import PaginatedParticipants, ParticipantListItem
from app.schemas.social import FriendListItem, PaginatedFriends
from app.schemas.user import PaginatedAdminUsers, UserRead
from app.services.social_service import FriendshipService

router = APIRouter(prefix="/admin/users", tags=["Admin User Management"])


@router.get("", response_model=PaginatedAdminUsers)
async def search_users(
    search: Optional[str] = Query(
        None, max_length=200, description="Matches email, phone number, player_uid, full name, or UUID"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
    _admin=Depends(require_admin),
):
    repo = UserRepository(session)
    rows, total = await repo.search_paginated(query=search, page=page, page_size=page_size)
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedAdminUsers(
        items=[UserRead.model_validate(u) for u in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{user_id}/friends", response_model=PaginatedFriends)
async def get_user_friends(
    user_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, max_length=200),
    session: AsyncSession = Depends(get_db_session),
    _admin=Depends(require_admin),
):
    user_repo = UserRepository(session)
    target_user = await user_repo.get_by_id(user_id)
    if target_user is None:
        raise NotFoundException("User not found")

    service = FriendshipService(session)
    rows, total = await service.list_friends(target_user, page=page, page_size=page_size, search=search)
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedFriends(
        items=[FriendListItem.model_validate(u) for u in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{user_id}/tournament-history", response_model=PaginatedParticipants)
async def get_user_tournament_history(
    user_id: UUID,
    status_filter: Optional[ParticipantStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    session: AsyncSession = Depends(get_db_session),
    _admin=Depends(require_admin),
):
    """Full tournament/match registration history for any user — lets
    admins verify a user's activity (e.g. while reviewing a report)."""
    user_repo = UserRepository(session)
    target_user = await user_repo.get_by_id(user_id)
    if target_user is None:
        raise NotFoundException("User not found")

    rows, total = await ParticipantRepository(session).list_for_user(
        user_id,
        page=page,
        page_size=page_size,
        status=status_filter,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedParticipants(
        items=[ParticipantListItem.model_validate(p) for p in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )