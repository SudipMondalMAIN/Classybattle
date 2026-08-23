"""
Telegram Admin Bot webhook.

Telegram POSTs every update (message / callback_query) here. The path
includes TELEGRAM_WEBHOOK_SECRET so it can't be guessed, and we also
verify Telegram's own `X-Telegram-Bot-Api-Secret-Token` header when a
secret is configured.
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.core.logging import get_logger
from app.database.session import get_db_session
from app.telegram_bot.service import TelegramBotService

logger = get_logger(__name__)

router = APIRouter(prefix="/telegram", tags=["Telegram Bot"])


@router.post("/webhook/{secret}")
async def telegram_webhook(
    secret: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=503, detail="Telegram bot is not configured")
    if secret != settings.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=404)
    if settings.TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token != settings.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403)

    update = await request.json()
    try:
        await TelegramBotService(session).handle_update(update)
    except Exception:  # noqa: BLE001 - never let a bad update 500 the webhook
        logger.exception("telegram_webhook_update_failed")
    return {"ok": True}
