"""
Banner Pydantic schemas.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BannerCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=150)
    redirect_link: Optional[str] = Field(None, max_length=500)
    sort_order: int = 0
    is_active: bool = True


class BannerUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=150)
    redirect_link: Optional[str] = Field(None, max_length=500)
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class BannerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    image_url: str
    title: Optional[str]
    redirect_link: Optional[str]
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
