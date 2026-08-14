"""
HomeCategoryBox Pydantic schemas.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.home_category_box import HomeCategoryBoxType


class HomeCategoryBoxCreate(BaseModel):
    box_type: HomeCategoryBoxType
    game_id: Optional[UUID] = None
    banner_url: str = Field(..., max_length=500)
    title: Optional[str] = Field(None, max_length=150)
    sort_order: int = 0
    is_active: bool = True

    @model_validator(mode="after")
    def _validate_game_id(self) -> "HomeCategoryBoxCreate":
        if self.box_type == HomeCategoryBoxType.CUSTOM:
            self.game_id = None
        elif self.game_id is None:
            raise ValueError("game_id is required for solo/squad boxes")
        return self


class HomeCategoryBoxUpdate(BaseModel):
    box_type: Optional[HomeCategoryBoxType] = None
    game_id: Optional[UUID] = None
    banner_url: Optional[str] = Field(None, max_length=500)
    title: Optional[str] = Field(None, max_length=150)
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class HomeCategoryBoxRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    box_type: HomeCategoryBoxType
    game_id: Optional[UUID]
    banner_url: str
    title: Optional[str]
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
