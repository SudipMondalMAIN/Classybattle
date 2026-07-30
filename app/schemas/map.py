"""
Map Pydantic schemas (Phase 4).
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MapCreate(BaseModel):
    game_id: UUID
    mode_id: Optional[UUID] = None
    name: str = Field(..., min_length=2, max_length=100)
    short_name: Optional[str] = Field(None, max_length=30)
    description: Optional[str] = Field(None, max_length=2000)
    image_url: Optional[str] = Field(None, max_length=500)
    thumbnail_url: Optional[str] = Field(None, max_length=500)
    sort_order: int = Field(default=0, ge=0)
    is_active: bool = True
    is_featured: bool = False


class MapUpdate(BaseModel):
    mode_id: Optional[UUID] = None
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    short_name: Optional[str] = Field(None, max_length=30)
    description: Optional[str] = Field(None, max_length=2000)
    image_url: Optional[str] = Field(None, max_length=500)
    thumbnail_url: Optional[str] = Field(None, max_length=500)
    sort_order: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None
    is_featured: Optional[bool] = None


class MapRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    map_uid: str
    game_id: UUID
    mode_id: Optional[UUID] = None
    name: str
    slug: str
    short_name: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    sort_order: int
    is_active: bool
    is_featured: bool
    created_by: Optional[UUID] = None
    updated_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


class MapListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    map_uid: str
    game_id: UUID
    mode_id: Optional[UUID] = None
    name: str
    slug: str
    short_name: Optional[str] = None
    thumbnail_url: Optional[str] = None
    sort_order: int
    is_active: bool
    is_featured: bool


class PaginatedMaps(BaseModel):
    items: list[MapListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class MapAssetUploadResponse(BaseModel):
    url: str
