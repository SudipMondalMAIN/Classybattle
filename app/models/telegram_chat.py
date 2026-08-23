"""
TelegramAuthorizedChat model — Telegram Admin Bot.

One row per chat that has successfully authorized itself with the bot
via /start <code>. Authorized chats receive deposit/withdrawal
notifications and (for deposits) can Confirm/Decline via inline buttons.
"""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database.base import Base


class TelegramAuthorizedChat(Base):
    __tablename__ = "telegram_authorized_chats"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, nullable=False
    )

    # Telegram chat id (can be a user DM or a group). Unique — a chat only
    # ever gets one row, re-auth just keeps it active.
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    chat_title: Mapped[str] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    authorized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<TelegramAuthorizedChat chat_id={self.chat_id} active={self.is_active}>"
