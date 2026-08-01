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


class GameCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    icon_url: Optional[str] = Field(None, max_length=500)
    is_active: bool = True
    profile_schema: list[ProfileFieldSchema] = Field(default_factory=list)


class GameUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    icon_url: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None
    profile_schema: Optional[list[ProfileFieldSchema]] = None


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
