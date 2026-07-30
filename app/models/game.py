"""
Game model — dynamic catalogue of games (managed by Admin in later phases).
No game name is hardcoded; games are pure data.
"""
from typing import Optional

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import BaseModel


class Game(BaseModel):
    """
    A game entry (e.g. Free Fire, BGMI, Valorant).

    `profile_schema` defines which fields a player's in-game profile for
    this game requires, e.g.:
        [
          {"key": "nickname", "label": "Nickname", "type": "string", "required": true},
          {"key": "uid", "label": "UID", "type": "string", "required": true}
        ]
    This lets new games be added by Admin without any schema/migration change —
    UserGameProfile stores the actual values in a JSONB column keyed by these fields.
    """

    __tablename__ = "games"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    icon_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Defines the shape of the per-game player profile (nickname, UID, Riot ID, etc.)
    profile_schema: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    game_profiles: Mapped[list["UserGameProfile"]] = relationship(
        back_populates="game", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Game id={self.id} name={self.name}>"
