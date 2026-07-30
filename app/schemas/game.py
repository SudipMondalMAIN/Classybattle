"""
Game and game-profile Pydantic schemas.
"""
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProfileFieldSchema(BaseModel):
    key: str
    label: str
    type: str = "string"
    required: bool = True


class GameRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    icon_url: Optional[str] = None
    is_active: bool
    profile_schema: list[dict[str, Any]] = Field(default_factory=list)


class UserGameProfileCreate(BaseModel):
    game_id: UUID
    data: dict[str, Any]


class UserGameProfileUpdate(BaseModel):
    data: dict[str, Any]


class UserGameProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    game_id: UUID
    data: dict[str, Any]
