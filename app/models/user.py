"""
User model.
"""
import enum
from typing import Optional

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel, ShortIdMixin
from app.database.types import str_enum


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    BANNED = "banned"


class User(ShortIdMixin, BaseModel):
    __tablename__ = "users"

    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    player_uid: Mapped[str] = mapped_column(String(8), unique=True, index=True, nullable=False)
    # Referral System v2 -- every user's own shareable code (referrals.py
    # apply endpoint looks another user up by this). Nullable only for the
    # brief moment before ReferralService lazily backfills it on an old
    # user's first referral-related request; new signups get one immediately.
    referral_code: Mapped[Optional[str]] = mapped_column(
        String(16), unique=True, index=True, nullable=True
    )

    role: Mapped[UserRole] = mapped_column(
        str_enum(UserRole, "user_role"), default=UserRole.USER, nullable=False
    )
    status: Mapped[UserStatus] = mapped_column(
        str_enum(UserStatus, "user_status"), default=UserStatus.ACTIVE, nullable=False
    )

    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Profile fields
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    avatar_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    game_profiles: Mapped[list["UserGameProfile"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email}>"
