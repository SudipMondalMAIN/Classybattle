"""
Social System API routes — Phase 15A (Player Profiles & Social System).
"""
import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnauthorizedException
from app.core.security import TokenType, decode_token
from app.database.session import get_db_session
from app.dependencies.auth import bearer_scheme, get_current_active_verified_user
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.social import (
    ActivityFeedEntryRead,
    BlockUserRequest,
    FollowRequest,
    FriendListItem,
    FriendRequestCreate,
    FriendshipRead,
    PaginatedActivityFeed,
    PaginatedFriends,
    PaginatedProfiles,
    PaginatedUsers,
    PlayerStatsSummary,
    ProfilePrivateRead,
    ProfileRead,
    ProfileSettingsUpdate,
    ProfileUpdate,
    PublicUserSummary,
)
from app.services.leaderboard_service import LeaderboardService
from app.services.social_service import ActivityFeedService, FollowService, FriendshipService, ProfileService

router = APIRouter(prefix="/social", tags=["Social System"])


async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> Optional[User]:
    """Like `get_current_user`, but returns None instead of raising when no
    (or an invalid) bearer token is supplied — used for public profile
    viewing where an anonymous request still gets a "public" view."""
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials, expected_type=TokenType.ACCESS)
    except Exception:
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    user_repo = UserRepository(session)
    try:
        user = await user_repo.get_by_id(UUID(user_id))
    except (ValueError, TypeError):
        return None
    if user is None or not user.is_active:
        return None
    return user


async def _build_profile_read(
    profile, target_user: User, relationship: str, session: AsyncSession, viewer: Optional[User], model_cls
):
    stats_summary = None
    if profile.show_stats:
        try:
            stats = await LeaderboardService(session).get_player_statistics(target_user.id)
            stats_summary = PlayerStatsSummary(
                matches_played=stats.matches_played,
                matches_won=stats.matches_won,
                win_rate=stats.win_rate,
                kd_ratio=stats.kd_ratio,
                tournaments_played=stats.tournaments_played,
                tournaments_won=stats.tournaments_won,
                current_rank=stats.current_rank,
            )
        except Exception:
            stats_summary = None

    is_following = await FollowService(session).repo.get(viewer.id, target_user.id) if viewer else None

    data = model_cls.model_validate(profile).model_dump()
    data["user"] = PublicUserSummary.model_validate(target_user)
    data["stats"] = stats_summary
    data["relationship_status"] = relationship
    data["is_following"] = is_following is not None
    return model_cls(**data)


# ----------------------------------------------------------------------
# Player Profile
# ----------------------------------------------------------------------
@router.get("/profiles/me", response_model=ProfilePrivateRead)
async def get_my_profile(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ProfileService(session)
    profile = await service.get_or_create(current_user)
    return await _build_profile_read(
        profile, current_user, "self", session, current_user, ProfilePrivateRead
    )


@router.patch("/profiles/me", response_model=ProfilePrivateRead)
async def update_my_profile(
    payload: ProfileUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ProfileService(session)
    profile = await service.update_profile(current_user, payload)
    return await _build_profile_read(
        profile, current_user, "self", session, current_user, ProfilePrivateRead
    )


@router.patch("/profiles/me/settings", response_model=ProfilePrivateRead)
async def update_my_settings(
    payload: ProfileSettingsUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ProfileService(session)
    profile = await service.update_settings(current_user, payload)
    return await _build_profile_read(
        profile, current_user, "self", session, current_user, ProfilePrivateRead
    )


@router.post("/presence/online", response_model=ProfilePrivateRead)
async def set_online(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ProfileService(session)
    profile = await service.touch_presence(current_user, online=True)
    return await _build_profile_read(
        profile, current_user, "self", session, current_user, ProfilePrivateRead
    )


@router.post("/presence/offline", response_model=ProfilePrivateRead)
async def set_offline(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ProfileService(session)
    profile = await service.touch_presence(current_user, online=False)
    return await _build_profile_read(
        profile, current_user, "self", session, current_user, ProfilePrivateRead
    )


@router.get("/profiles/{user_id}", response_model=ProfileRead)
async def get_player_profile(
    user_id: UUID,
    viewer: Optional[User] = Depends(get_optional_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ProfileService(session)
    profile, target_user, relationship = await service.get_profile_for_viewer(
        target_user_id=user_id, viewer=viewer
    )
    return await _build_profile_read(profile, target_user, relationship, session, viewer, ProfileRead)


@router.get("/search", response_model=PaginatedProfiles)
async def search_profiles(
    q: Optional[str] = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    session: AsyncSession = Depends(get_db_session),
):
    service = ProfileService(session)
    rows, total = await service.search(
        query=q, page=page, page_size=page_size, sort_by=sort_by, sort_order=sort_order
    )
    items = [
        await _build_profile_read(p, u, "none", session, None, ProfileRead) for p, u in rows
    ]
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedProfiles(items=items, total=total, page=page, page_size=page_size, total_pages=total_pages)


# ----------------------------------------------------------------------
# Friends
# ----------------------------------------------------------------------
@router.post("/friends/requests", response_model=FriendshipRead, status_code=201)
async def send_friend_request(
    payload: FriendRequestCreate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = FriendshipService(session)
    friendship = await service.send_request(current_user, payload.addressee_id)
    return FriendshipRead.model_validate(friendship)


@router.post("/friends/requests/{friendship_id}/accept", response_model=FriendshipRead)
async def accept_friend_request(
    friendship_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = FriendshipService(session)
    friendship = await service.accept_request(current_user, friendship_id)
    return FriendshipRead.model_validate(friendship)


@router.post("/friends/requests/{friendship_id}/reject", response_model=FriendshipRead)
async def reject_friend_request(
    friendship_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = FriendshipService(session)
    friendship = await service.reject_request(current_user, friendship_id)
    return FriendshipRead.model_validate(friendship)


@router.post("/friends/requests/{friendship_id}/cancel", response_model=FriendshipRead)
async def cancel_friend_request(
    friendship_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = FriendshipService(session)
    friendship = await service.cancel_request(current_user, friendship_id)
    return FriendshipRead.model_validate(friendship)


@router.get("/friends/requests/incoming", response_model=list[FriendshipRead])
async def list_incoming_requests(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = FriendshipService(session)
    rows = await service.list_incoming_requests(current_user)
    return [FriendshipRead.model_validate(r) for r in rows]


@router.get("/friends/requests/outgoing", response_model=list[FriendshipRead])
async def list_outgoing_requests(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = FriendshipService(session)
    rows = await service.list_outgoing_requests(current_user)
    return [FriendshipRead.model_validate(r) for r in rows]


@router.delete("/friends/{friend_user_id}", status_code=204)
async def remove_friend(
    friend_user_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = FriendshipService(session)
    await service.remove_friend(current_user, friend_user_id)
    return None


@router.get("/friends", response_model=PaginatedFriends)
async def list_my_friends(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, max_length=200),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = FriendshipService(session)
    rows, total = await service.list_friends(current_user, page=page, page_size=page_size, search=search)
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedFriends(
        items=[FriendListItem.model_validate(u) for u in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/friends/{other_user_id}/mutual", response_model=list[FriendListItem])
async def get_mutual_friends(
    other_user_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = FriendshipService(session)
    users = await service.mutual_friends(current_user, other_user_id)
    return [FriendListItem.model_validate(u) for u in users]


@router.get("/friends/suggestions", response_model=list[FriendListItem])
async def get_friend_suggestions(
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = FriendshipService(session)
    users = await service.suggest_friends(current_user, limit=limit)
    return [FriendListItem.model_validate(u) for u in users]


@router.post("/block", response_model=FriendshipRead)
async def block_user(
    payload: BlockUserRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = FriendshipService(session)
    friendship = await service.block_user(current_user, payload.user_id)
    return FriendshipRead.model_validate(friendship)


@router.post("/unblock/{user_id}", status_code=204)
async def unblock_user(
    user_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = FriendshipService(session)
    await service.unblock_user(current_user, user_id)
    return None


# ----------------------------------------------------------------------
# Follow
# ----------------------------------------------------------------------
@router.post("/follow", status_code=201)
async def follow_player(
    payload: FollowRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = FollowService(session)
    await service.follow(current_user, payload.user_id)
    return {"success": True}


@router.delete("/follow/{user_id}", status_code=204)
async def unfollow_player(
    user_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = FollowService(session)
    await service.unfollow(current_user, user_id)
    return None


@router.get("/profiles/{user_id}/followers", response_model=PaginatedUsers)
async def list_followers(
    user_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    service = FollowService(session)
    rows, total = await service.list_followers(user_id, page=page, page_size=page_size)
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedUsers(
        items=[FriendListItem.model_validate(u) for u in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/profiles/{user_id}/following", response_model=PaginatedUsers)
async def list_following(
    user_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
):
    service = FollowService(session)
    rows, total = await service.list_following(user_id, page=page, page_size=page_size)
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedUsers(
        items=[FriendListItem.model_validate(u) for u in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ----------------------------------------------------------------------
# Activity Feed
# ----------------------------------------------------------------------
@router.get("/feed", response_model=PaginatedActivityFeed)
async def get_activity_feed(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ActivityFeedService(session)
    rows, total = await service.get_feed_for_user(current_user, page=page, page_size=page_size)
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedActivityFeed(
        items=[ActivityFeedEntryRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
