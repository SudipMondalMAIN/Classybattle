"""
UserGameProfile — a user's identity within a specific game
(e.g. Free Fire nickname + UID, Valorant Riot ID).

Uses a JSONB `data` column validated at the service layer against the
owning Game's `profile_schema`, so new games never require a migration.
"""
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel


class UserGameProfile(BaseModel):
    __tablename__ = "user_game_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", "game_id", name="uq_user_game_profile"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    game_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("games.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Arbitrary key/value data matching Game.profile_schema, e.g. {"nickname": "...", "uid": "..."}
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    user: Mapped["User"] = relationship(back_populates="game_profiles")
    game: Mapped["Game"] = relationship(back_populates="game_profiles")

    def __repr__(self) -> str:
        return f"<UserGameProfile user_id={self.user_id} game_id={self.game_id}>"
