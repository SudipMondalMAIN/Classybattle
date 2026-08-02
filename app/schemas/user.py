"""
User-related Pydantic schemas.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole, UserStatus


class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=150)
    country: Optional[str] = Field(None, max_length=100)
    avatar_id: Optional[str] = Field(None, max_length=50)
    bio: Optional[str] = Field(None, max_length=500)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    email: EmailStr
    phone_number: str
    player_uid: str
    role: UserRole
    status: UserStatus
    is_email_verified: bool
    is_active: bool
    country: Optional[str] = None
    avatar_id: Optional[str] = None
    bio: Optional[str] = None
    created_at: datetime


class UserPublic(BaseModel):
    """Minimal public-facing user representation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    player_uid: str
    avatar_id: Optional[str] = None


class PaginatedAdminUsers(BaseModel):
    items: list[UserRead]
    total: int
    page: int
    page_size: int
    total_pages: int