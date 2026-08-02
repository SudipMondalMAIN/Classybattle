"""
Social System Pydantic schemas — Phase 15A.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.social import ActivityType, FriendshipStatus, ProfileVisibility


# ----------------------------------------------------------------------
# Player Profile
# ----------------------------------------------------------------------
class ProfileUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=2, max_length=150)
    bio: Optional[str] = Field(None, max_length=500)
    avatar_url: Optional[str] = Field(None, max_length=500)
    cover_image_url: Optional[str] = Field(None, max_length=500)
    social_links: Optional[dict] = None


class ProfileSettingsUpdate(BaseModel):
    visibility: Optional[ProfileVisibility] = None
    show_match_history: Optional[bool] = None
    show_stats: Optional[bool] = None


class GameProfileSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    game_id: UUID
    game_name: str
    game_slug: str
    data: dict = Field(default_factory=dict, description='e.g. {"nickname": "...", "uid": "..."}')


class PublicUserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    player_uid: str
    country: Optional[str] = None
    game_profiles: list[GameProfileSummary] = Field(default_factory=list)


class PrivateUserSummary(PublicUserSummary):
    """Same as PublicUserSummary but also includes contact details —
    only ever used for the viewer's own profile (/profiles/me)."""

    email: str
    phone_number: str


class PlayerStatsSummary(BaseModel):
    matches_played: int = 0
    matches_won: int = 0
    win_rate: float = 0.0
    kd_ratio: float = 0.0
    tournaments_played: int = 0
    tournaments_won: int = 0
    current_rank: Optional[int] = None


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_image_url: Optional[str] = None
    visibility: ProfileVisibility
    social_links: Optional[dict] = None
    is_online: bool
    last_seen_at: Optional[datetime] = None
    friends_count: int
    followers_count: int
    following_count: int
    created_at: datetime
    user: Optional[PublicUserSummary] = None
    stats: Optional[PlayerStatsSummary] = None
    relationship_status: Optional[str] = Field(
        None, description="Viewer's relationship to this profile: self/friend/pending/blocked/none"
    )
    is_following: Optional[bool] = None


class ProfilePrivateRead(ProfileRead):
    show_match_history: bool
    following_count: int


# ----------------------------------------------------------------------
# Friends
# ----------------------------------------------------------------------
class FriendRequestCreate(BaseModel):
    addressee_id: UUID


class FriendshipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    requester_id: UUID
    addressee_id: UUID
    status: FriendshipStatus
    created_at: datetime
    responded_at: Optional[datetime] = None


class FriendListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    player_uid: str
    country: Optional[str] = None


class PaginatedFriends(BaseModel):
    items: list[FriendListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class BlockUserRequest(BaseModel):
    user_id: UUID


# ----------------------------------------------------------------------
# Follow
# ----------------------------------------------------------------------
class FollowRequest(BaseModel):
    user_id: UUID


class PaginatedUsers(BaseModel):
    items: list[FriendListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


# ----------------------------------------------------------------------
# Activity Feed
# ----------------------------------------------------------------------
class ActivityFeedEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_id: UUID
    activity_type: ActivityType
    title: str
    meta_data: Optional[dict] = None
    created_at: datetime


class PaginatedActivityFeed(BaseModel):
    items: list[ActivityFeedEntryRead]
    total: int
    page: int
    page_size: int
    total_pages: int


# ----------------------------------------------------------------------
# Search
# ----------------------------------------------------------------------
class PaginatedProfiles(BaseModel):
    items: list[ProfileRead]
    total: int
    page: int
    page_size: int
    total_pages: int