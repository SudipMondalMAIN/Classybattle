"""
AppVersion Pydantic schemas — force/soft update feature.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.app_version import AppPlatform


class AppVersionUpsert(BaseModel):
    latest_version: str = Field(..., max_length=20)
    latest_build_number: int = Field(..., gt=0)
    min_supported_version: str = Field(..., max_length=20)
    force_update: bool = False
    update_url: str = Field(..., max_length=500)
    update_title: str = Field(default="Update Available", max_length=150)
    update_message: str = Field(
        default="A new version of the app is available."
    )
    is_active: bool = True


class AppVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    platform: AppPlatform
    latest_version: str
    latest_build_number: int
    min_supported_version: str
    force_update: bool
    update_url: str
    update_title: str
    update_message: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AppVersionCheckResponse(BaseModel):
    """What the Flutter splash screen actually consumes."""

    update_available: bool
    force_update: bool
    latest_version: str
    update_url: str
    update_title: str
    update_message: str
