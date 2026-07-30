"""
GameMode model — Phase 3.

A "mode" belongs to a Game (e.g. "Battle Royale", "Clash Squad" for
Free Fire; "Solo", "Duo", "Squad" for BGMI). Modes are managed by
Admins and consumed by the Tournament module and mobile/web clients
to render mode pickers per-game.
"""
import uuid
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


class GameMode(BaseModel):
    """A game mode belonging to a specific Game."""

    __tablename__ = "game_modes"
    __table_args__ = (
        UniqueConstraint("game_id", "slug", name="uq_game_modes_game_id_slug"),
        UniqueConstraint("game_id", "name", name="uq_game_modes_game_id_name"),
        CheckConstraint("min_players > 0", name="ck_game_modes_min_players_positive"),
        CheckConstraint("max_players >= min_players", name="ck_game_modes_max_ge_min_players"),
        CheckConstraint("max_team_size > 0", name="ck_game_modes_max_team_size_positive"),
        Index("ix_game_modes_game_active", "game_id", "is_active"),
        Index("ix_game_modes_game_featured", "game_id", "is_featured"),
    )

    mode_uid: Mapped[str] = mapped_column(
        String(20), unique=True, index=True, nullable=False, default=lambda: uuid.uuid4().hex[:12]
    )

    game_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("games.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(130), nullable=False, index=True)
    short_name: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    icon_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    max_team_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    min_players: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_players: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

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
    creator: Mapped[Optional["User"]] = relationship(  # noqa: F821
        foreign_keys=[created_by], lazy="selectin"
    )
    updater: Mapped[Optional["User"]] = relationship(  # noqa: F821
        foreign_keys=[updated_by], lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<GameMode id={self.id} slug={self.slug} game_id={self.game_id}>"
