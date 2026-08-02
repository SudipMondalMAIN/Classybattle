"""
User-related Pydantic schemas.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.user import UserRole, UserStatus

# Fixed set of avatars bundled inside the Flutter app
# (assets/avatars/avatar_1.png ... avatar_6.png). No custom photo upload —
# user only picks one of these six. Add/remove entries here if the set
# ever changes; nothing else needs to change.
VALID_AVATAR_IDS = {"avatar_1", "avatar_2", "avatar_3", "avatar_4", "avatar_5", "avatar_6"}


class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=150)
    country: Optional[str] = Field(None, max_length=100)
    avatar_id: Optional[str] = Field(None, max_length=50)
    bio: Optional[str] = Field(None, max_length=500)

    @field_validator("avatar_id")
    @classmethod
    def validate_avatar_id(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in VALID_AVATAR_IDS:
            raise ValueError(f"avatar_id must be one of: {', '.join(sorted(VALID_AVATAR_IDS))}")
        return value


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    short_id: int
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