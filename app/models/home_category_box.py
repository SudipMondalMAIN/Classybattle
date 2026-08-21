"""
HomeCategoryBox model — the 3-per-row tap boxes on the app home screen
(e.g. "Free Fire Solo", "Free Fire Clash Squad", "Custom Tournament").

Rendered with the same card design as a live tournament card, but the
content is fully static — admin sets a banner image + title. Tapping a
SOLO/SQUAD box takes the user to that game's tournament listing
(filtered by game_id + category); tapping a CUSTOM box takes the user
straight into the user-created tournament flow, so game_id is left
null for CUSTOM boxes.
"""
import enum
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel
from app.database.types import str_enum


class HomeCategoryBoxType(str, enum.Enum):
    SOLO = "solo"
    DUO = "duo"
    SQUAD = "squad"
    FREE = "free"
    CUSTOM = "custom"


class HomeCategoryBox(BaseModel):
    """A single home-screen category box managed by Admin."""

    __tablename__ = "home_category_boxes"
    __table_args__ = (
        CheckConstraint(
            "(box_type = 'custom' AND game_id IS NULL) OR "
            "(box_type != 'custom' AND game_id IS NOT NULL)",
            name="ck_home_category_boxes_game_required_unless_custom",
        ),
    )

    box_type: Mapped[HomeCategoryBoxType] = mapped_column(
        str_enum(HomeCategoryBoxType, "home_category_box_type"),
        nullable=False,
        index=True,
    )

    # Required for SOLO/SQUAD (drives the filter when tapped). Left null
    # for CUSTOM, which routes to the user tournament-creation flow instead.
    game_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    banner_url: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    game: Mapped[Optional["Game"]] = relationship(lazy="selectin")  # noqa: F821

    def __repr__(self) -> str:
        return f"<HomeCategoryBox id={self.id} type={self.box_type} title={self.title!r}>"