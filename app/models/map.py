"""
Map model — Phase 4.

A "map" belongs to a Game and, optionally, a specific GameMode (e.g. a
Battle Royale map differs from a Clash Squad map even within the same
game). Maps are managed by Admins and consumed by the Tournament module
and mobile/web clients to render map pickers per-game/per-mode.
"""
import uuid
from typing import Optional

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel


class Map(BaseModel):
    """A map belonging to a specific Game, optionally scoped to a GameMode."""

    __tablename__ = "maps"
    __table_args__ = (
        UniqueConstraint("game_id", "mode_id", "slug", name="uq_maps_game_id_mode_id_slug"),
        UniqueConstraint("game_id", "mode_id", "name", name="uq_maps_game_id_mode_id_name"),
        Index("ix_maps_game_active", "game_id", "is_active"),
        Index("ix_maps_game_featured", "game_id", "is_featured"),
        Index("ix_maps_game_mode", "game_id", "mode_id"),
    )

    map_uid: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, nullable=False, default=lambda: uuid.uuid4().hex[:12]
    )

    game_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mode_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("game_modes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(130), nullable=False, index=True)
    short_name: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    game: Mapped["Game"] = relationship(lazy="selectin")  # noqa: F821
    mode: Mapped[Optional["GameMode"]] = relationship(lazy="selectin")  # noqa: F821
    creator: Mapped[Optional["User"]] = relationship(  # noqa: F821
        foreign_keys=[created_by], lazy="selectin"
    )
    updater: Mapped[Optional["User"]] = relationship(  # noqa: F821
        foreign_keys=[updated_by], lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Map id={self.id} slug={self.slug} game_id={self.game_id}>"
