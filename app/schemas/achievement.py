"""
Achievement Pydantic schemas — Phase 15C.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.achievement import AchievementComparison, AchievementTriggerType, BadgeTier


class BadgeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=500)
    icon_url: Optional[str] = Field(None, max_length=1000)
    tier: BadgeTier = BadgeTier.BRONZE


class BadgeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: Optional[str] = None
    icon_url: Optional[str] = None
    tier: BadgeTier
    is_active: bool


class AchievementCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = Field(None, max_length=500)
    badge_id: UUID
    trigger_type: AchievementTriggerType
    comparison: AchievementComparison = AchievementComparison.GTE
    threshold: Decimal


class AchievementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: Optional[str] = None
    badge: BadgeRead
    trigger_type: AchievementTriggerType
    comparison: AchievementComparison
    threshold: Decimal
    is_active: bool


class UserAchievementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    achievement: AchievementRead
    unlocked_at: datetime
    metric_value: Optional[Decimal] = None
