"""
Tournament Core API routes (Phase 2).
"""
import math
from typing import Optional, Union
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_delete_prefix, cache_get, cache_set
from app.core.exceptions import ValidationException
from app.database.session import get_db_session
from app.dependencies.auth import (
    get_current_active_verified_user,
    get_current_user_optional,
    require_admin,
)
from app.models.tournament import ScheduleCategory, TournamentStatus, TournamentVisibility
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.tournament import (
    PaginatedTournaments,
    TournamentAssetUploadResponse,
    TournamentCreate,
    TournamentCustomCreate,
    TournamentListItem,
    TournamentPublishRoom,
    TournamentRead,
    TournamentRoomRead,
    TournamentStatusUpdate,
    TournamentUpdate,
)
from app.services.tournament_service import TournamentService

router = APIRouter(prefix="/tournaments", tags=["Tournaments"])

# Tournaments are read constantly (home feed, browse, polling for status/
# room updates) but only mutated by admins/hosts occasionally, so caching
# reads and invalidating the whole namespace on any write is a big win.
# Kept short (list) / moderate (detail) since room_id/room_password and
# status are time-sensitive -- a stale cache must never outlive a real
# publish-room/status-change by more than a few seconds.
_CACHE_PREFIX = "tournament:"
# Every mutation path (update, status change, publish-room, delete,
# banner/cover upload, plus the background scheduler's auto-complete and
# daily rollover) explicitly invalidates this cache immediately, so a
# long TTL is safe -- nothing goes stale between changes, it just skips
# the DB entirely until something actually changes.
_LIST_TTL = 300
_DETAIL_TTL = 3600
# Terminal states (see TOURNAMENT_STATUS_TRANSITIONS) never change again,
# so their detail payload is cached even longer as a nice-to-have (not
# strictly needed since invalidation already handles freshness, but
# there's zero chance a completed match's data changes).
_TERMINAL_STATUSES = {TournamentStatus.COMPLETED, TournamentStatus.CANCELLED}
_TERMINAL_DETAIL_TTL = 86400


async def _invalidate_tournament_cache() -> None:
    await cache_delete_prefix(_CACHE_PREFIX)

# Convenience aliases the frontend can send instead of (or alongside) the
# exact TournamentStatus enum values.
_STATUS_ALIASES: dict[str, list[TournamentStatus]] = {
    "upcoming": [TournamentStatus.SCHEDULED],
    "ongoing": [TournamentStatus.LIVE],
    "past": [TournamentStatus.COMPLETED, TournamentStatus.CANCELLED],
}


async def _to_tournament_read(service: TournamentService, tournament, current_user) -> TournamentRead:
    """Serialize a Tournament, stripping room_id/room_password unless the
    caller is a registered participant or admin (room credentials must
    never leak through the public tournament-detail endpoints)."""
    data = TournamentRead.model_validate(tournament)
    if not await service.can_view_room(tournament, current_user):
        data.room_id = None
        data.room_password = None
    return data


def _resolve_status_filter(
    status: Optional[str],
) -> Optional[Union[TournamentStatus, list[TournamentStatus]]]:
    if status is None:
        return None
    key = status.strip().lower()
    if key in _STATUS_ALIASES:
        return _STATUS_ALIASES[key]
    try:
        return TournamentStatus(key)
    except ValueError:
        valid = ", ".join(sorted(set(_STATUS_ALIASES) | {s.value for s in TournamentStatus}))
        raise ValidationException(f"Invalid status '{status}'. Valid values: {valid}")


@router.post("", response_model=TournamentRead, status_code=201)
async def create_tournament(
    payload: TournamentCreate,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = TournamentService(session)
    tournament = await service.create_tournament(payload, current_user)
    await _invalidate_tournament_cache()
    return TournamentRead.model_validate(tournament)


@router.post("/custom", response_model=TournamentRead, status_code=201)
async def create_custom_tournament(
    payload: TournamentCustomCreate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Regular user "Custom Tournament" creation -- host sets entry fee &
    player count, prize pool is auto-calculated, goes live immediately, no
    admin approval needed."""
    service = TournamentService(session)
    tournament = await service.create_custom_tournament(payload, current_user)
    await _invalidate_tournament_cache()
    return TournamentRead.model_validate(tournament)


@router.get("", response_model=PaginatedTournaments)
async def list_tournaments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    game_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    visibility: Optional[TournamentVisibility] = Query(None),
    is_featured: Optional[bool] = Query(None),
    category: Optional[ScheduleCategory] = Query(None),
    format: Optional[str] = Query(
        None,
        description="Browse-tournaments filter chip: solo | duo | squad | free | custom. "
        "Combine with game_id to get e.g. 'this game, solo only'.",
    ),
    is_custom: Optional[bool] = Query(
        None,
        description="True: only user-hosted Custom Tournaments (no schedule category). "
        "False: only admin/schedule tournaments (solo or squad).",
    ),
    search: Optional[str] = Query(None, max_length=200),
    sort_by: str = Query("starts_at"),
    sort_order: str = Query("asc", pattern="^(?i)(asc|desc)$"),
    session: AsyncSession = Depends(get_db_session),
):
    cache_key = (
        f"{_CACHE_PREFIX}list:{page}:{page_size}:{game_id}:{status}:{visibility}:"
        f"{is_featured}:{category}:{format}:{is_custom}:{search}:{sort_by}:{sort_order}"
    )
    cached = await cache_get(cache_key)
    if cached is not None:
        return PaginatedTournaments.model_validate(cached)

    service = TournamentService(session)
    items, total = await service.list_tournaments(
        page=page,
        page_size=page_size,
        game_id=game_id,
        status=_resolve_status_filter(status),
        visibility=visibility,
        is_featured=is_featured,
        category=category,
        format=format,
        is_custom=is_custom,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        requesting_user=None,
    )
    total_pages = math.ceil(total / page_size) if total else 0
    result = PaginatedTournaments(
        items=[TournamentListItem.model_validate(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
    await cache_set(cache_key, result.model_dump(mode="json"), ttl=_LIST_TTL)
    return result


@router.get("/slug/{slug}", response_model=TournamentRead)
async def get_tournament_by_slug(
    slug: str,
    current_user: Optional[User] = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_db_session),
):
    # Keyed per-viewer (not just per-tournament) since room_id/room_password
    # visibility depends on who's asking -- never share one cached payload
    # across a participant and a stranger.
    cache_key = f"{_CACHE_PREFIX}slug:{slug}:{current_user.id if current_user else 'anon'}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return TournamentRead.model_validate(cached)

    service = TournamentService(session)
    tournament = await service.get_by_slug(slug)
    result = await _to_tournament_read(service, tournament, current_user)
    ttl = _TERMINAL_DETAIL_TTL if tournament.status in _TERMINAL_STATUSES else _DETAIL_TTL
    await cache_set(cache_key, result.model_dump(mode="json"), ttl=ttl)
    return result


@router.get("/short/{short_id}", response_model=TournamentRead)
async def get_tournament_by_short_id(
    short_id: int,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin lookup by the human-friendly 8-digit short_id."""
    service = TournamentService(session)
    tournament = await service.get_by_short_id(short_id)
    return await _to_tournament_read(service, tournament, current_user)


@router.get("/{tournament_id}", response_model=TournamentRead)
async def get_tournament(
    tournament_id: UUID,
    current_user: Optional[User] = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_db_session),
):
    cache_key = f"{_CACHE_PREFIX}id:{tournament_id}:{current_user.id if current_user else 'anon'}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return TournamentRead.model_validate(cached)

    service = TournamentService(session)
    tournament = await service.get_by_id(tournament_id)
    result = await _to_tournament_read(service, tournament, current_user)
    # COMPLETED/CANCELLED are terminal states (see TOURNAMENT_STATUS_TRANSITIONS
    # in app/models/tournament.py -- COMPLETED has no outgoing transitions),
    # so once a tournament reaches one, its data can never change again.
    # Cache it far longer instead of re-hitting the DB every 30s for a
    # match that's already over.
    ttl = _TERMINAL_DETAIL_TTL if tournament.status in _TERMINAL_STATUSES else _DETAIL_TTL
    await cache_set(cache_key, result.model_dump(mode="json"), ttl=ttl)
    return result


@router.patch("/{tournament_id}", response_model=TournamentRead)
async def update_tournament(
    tournament_id: UUID,
    payload: TournamentUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TournamentService(session)
    tournament = await service.update_tournament(tournament_id, payload, current_user)
    await _invalidate_tournament_cache()
    return TournamentRead.model_validate(tournament)


@router.patch("/{tournament_id}/status", response_model=TournamentRead)
async def update_tournament_status(
    tournament_id: UUID,
    payload: TournamentStatusUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TournamentService(session)
    tournament = await service.update_status(tournament_id, payload.status, current_user)
    await _invalidate_tournament_cache()
    return TournamentRead.model_validate(tournament)


@router.post("/{tournament_id}/publish-room", response_model=TournamentRead)
async def publish_room(
    tournament_id: UUID,
    payload: TournamentPublishRoom,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin OR the tournament's host (for user-hosted Custom Tournaments)
    sets room_id/room_password -> tournament auto-flips to LIVE.
    Permission is enforced in the service layer via _assert_can_manage."""
    service = TournamentService(session)
    tournament = await service.publish_room(
        tournament_id, payload.room_id, payload.room_password, current_user
    )
    await _invalidate_tournament_cache()
    return TournamentRead.model_validate(tournament)


@router.get("/{tournament_id}/room", response_model=TournamentRoomRead)
async def get_room(
    tournament_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Room credentials -- visible only to registered participants/admins."""
    service = TournamentService(session)
    tournament = await service.get_room_info(tournament_id, current_user)
    return TournamentRoomRead.model_validate(tournament)


@router.delete("/{tournament_id}", response_model=MessageResponse)
async def delete_tournament(
    tournament_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = TournamentService(session)
    await service.soft_delete_tournament(tournament_id, current_user)
    await _invalidate_tournament_cache()
    return MessageResponse(message="Tournament deleted successfully")


@router.post("/{tournament_id}/banner", response_model=TournamentAssetUploadResponse)
async def upload_tournament_banner(
    tournament_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    if file.content_type is None:
        raise ValidationException("File content type is required")
    file_bytes = await file.read()
    service = TournamentService(session)
    tournament = await service.upload_banner(
        tournament_id, file_bytes, file.content_type, current_user
    )
    await _invalidate_tournament_cache()
    return TournamentAssetUploadResponse(url=tournament.banner_url)


@router.post("/{tournament_id}/cover", response_model=TournamentAssetUploadResponse)
async def upload_tournament_cover(
    tournament_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    if file.content_type is None:
        raise ValidationException("File content type is required")
    file_bytes = await file.read()
    service = TournamentService(session)
    tournament = await service.upload_cover(
        tournament_id, file_bytes, file.content_type, current_user
    )
    await _invalidate_tournament_cache()
    return TournamentAssetUploadResponse(url=tournament.cover_url)
