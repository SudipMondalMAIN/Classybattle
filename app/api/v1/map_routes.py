"""
Maps API routes (Phase 4).

Read APIs are public; create/update/delete/upload are restricted to Admins.
"""
import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationException
from app.database.session import get_db_session
from app.dependencies.auth import require_admin
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.map import (
    MapAssetUploadResponse,
    MapCreate,
    MapListItem,
    MapRead,
    MapUpdate,
    PaginatedMaps,
)
from app.services.map_service import MapService

router = APIRouter(prefix="/maps", tags=["Maps"])


@router.post("", response_model=MapRead, status_code=201)
async def create_map(
    payload: MapCreate,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = MapService(session)
    map_ = await service.create_map(payload, current_user)
    return MapRead.model_validate(map_)


@router.get("", response_model=PaginatedMaps)
async def list_maps(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    game_id: Optional[UUID] = Query(None),
    mode_id: Optional[UUID] = Query(None),
    is_active: Optional[bool] = Query(None),
    is_featured: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    sort_by: str = Query("sort_order", pattern="^(?i)(sort_order|name|created_at)$"),
    sort_order: str = Query("asc", pattern="^(?i)(asc|desc)$"),
    session: AsyncSession = Depends(get_db_session),
):
    service = MapService(session)
    items, total = await service.list_maps(
        page=page,
        page_size=page_size,
        game_id=game_id,
        mode_id=mode_id,
        is_active=is_active,
        is_featured=is_featured,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedMaps(
        items=[MapListItem.model_validate(m) for m in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/slug/{game_id}/{slug}", response_model=MapRead)
async def get_map_by_slug(
    game_id: UUID,
    slug: str,
    session: AsyncSession = Depends(get_db_session),
):
    service = MapService(session)
    map_ = await service.get_by_slug(game_id, slug)
    return MapRead.model_validate(map_)


@router.get("/{map_id}", response_model=MapRead)
async def get_map(
    map_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = MapService(session)
    map_ = await service.get_by_id(map_id)
    return MapRead.model_validate(map_)


@router.patch("/{map_id}", response_model=MapRead)
async def update_map(
    map_id: UUID,
    payload: MapUpdate,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = MapService(session)
    map_ = await service.update_map(map_id, payload, current_user)
    return MapRead.model_validate(map_)


@router.delete("/{map_id}", response_model=MessageResponse)
async def delete_map(
    map_id: UUID,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = MapService(session)
    await service.soft_delete_map(map_id, current_user)
    return MessageResponse(message="Map deleted successfully")


@router.post("/{map_id}/image", response_model=MapAssetUploadResponse)
async def upload_map_image(
    map_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    if file.content_type is None:
        raise ValidationException("File content type is required")
    file_bytes = await file.read()
    service = MapService(session)
    map_ = await service.upload_image(map_id, file_bytes, file.content_type, current_user)
    return MapAssetUploadResponse(url=map_.image_url)


@router.post("/{map_id}/thumbnail", response_model=MapAssetUploadResponse)
async def upload_map_thumbnail(
    map_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    if file.content_type is None:
        raise ValidationException("File content type is required")
    file_bytes = await file.read()
    service = MapService(session)
    map_ = await service.upload_thumbnail(map_id, file_bytes, file.content_type, current_user)
    return MapAssetUploadResponse(url=map_.thumbnail_url)
