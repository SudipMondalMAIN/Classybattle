"""
Minimal Telegram Bot API HTTP client. No third-party SDK — just the
handful of endpoints the admin bot needs (sendMessage, sendPhoto,
answerCallbackQuery, editMessageReplyMarkup, setWebhook).
"""
from typing import Any, Optional

import httpx

from app.config.settings import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/{method}"


class TelegramClient:
    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token or settings.TELEGRAM_BOT_TOKEN

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    async def _call(self, method: str, payload: dict[str, Any]) -> Optional[dict]:
        if not self.enabled:
            logger.warning("telegram_bot_disabled", extra={"method": method})
            return None
        url = _API_BASE.format(token=self.token, method=method)
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.post(url, json=payload)
                data = resp.json()
                if not data.get("ok"):
                    logger.error("telegram_api_error", extra={"method": method, "response": data})
                return data
            except Exception:  # noqa: BLE001
                logger.exception("telegram_api_call_failed", extra={"method": method})
                return None

    async def send_message(
        self, chat_id: int, text: str, reply_markup: Optional[dict] = None
    ) -> Optional[dict]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._call("sendMessage", payload)

    async def send_photo(
        self, chat_id: int, photo_url: str, caption: str, reply_markup: Optional[dict] = None
    ) -> Optional[dict]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": "HTML",
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        result = await self._call("sendPhoto", payload)
        if result is None or not result.get("ok"):
            # Fall back to a plain text message + link, in case the proof
            # image URL isn't reachable/valid as a Telegram photo (e.g.
            # non-image content-type, private bucket, etc.)
            fallback_text = f"{caption}\n\n🖼 Proof: {photo_url}"
            return await self.send_message(chat_id, fallback_text, reply_markup)
        return result

    async def answer_callback_query(
        self, callback_query_id: str, text: str = "", show_alert: bool = False
    ) -> Optional[dict]:
        return await self._call(
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id, "text": text, "show_alert": show_alert},
        )

    async def edit_message_caption(
        self,
        chat_id: int,
        message_id: int,
        caption: str,
        reply_markup: Optional[dict] = None,
    ) -> Optional[dict]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "caption": caption,
            "parse_mode": "HTML",
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._call("editMessageCaption", payload)

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: Optional[dict] = None,
    ) -> Optional[dict]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._call("editMessageText", payload)

    async def set_webhook(self, url: str, secret_token: Optional[str] = None) -> Optional[dict]:
        payload: dict[str, Any] = {"url": url, "allowed_updates": ["message", "callback_query"]}
        if secret_token:
            payload["secret_token"] = secret_token
        return await self._call("setWebhook", payload)


telegram_client = TelegramClient()
