"""
Telegram Admin Bot service.

Responsibilities:
- Track which chats are authorized (via /start <code>).
- Push deposit notifications (with Confirm/Decline inline buttons) and
  withdrawal notifications (info-only) to every authorized chat.
- Handle inline button presses by calling the existing PaymentService
  approve()/reject() methods, acting as the configured bot admin user.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.core.logging import get_logger
from app.models.payment import PaymentRejectionReason, PaymentRequest
from app.models.telegram_chat import TelegramAuthorizedChat
from app.models.user import User
from app.models.withdrawal import WithdrawalRequest
from app.services.payment_service import PaymentService
from app.telegram_bot.client import telegram_client

logger = get_logger(__name__)

_CONFIRM_PREFIX = "dep_confirm:"
_DECLINE_PREFIX = "dep_decline:"


class TelegramBotService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------
    async def authorize_chat(self, chat_id: int, chat_title: Optional[str] = None) -> None:
        existing = await self.session.scalar(
            select(TelegramAuthorizedChat).where(TelegramAuthorizedChat.chat_id == chat_id)
        )
        if existing:
            existing.is_active = True
            if chat_title:
                existing.chat_title = chat_title
        else:
            self.session.add(
                TelegramAuthorizedChat(chat_id=chat_id, chat_title=chat_title, is_active=True)
            )
        await self.session.commit()

    async def is_authorized(self, chat_id: int) -> bool:
        row = await self.session.scalar(
            select(TelegramAuthorizedChat).where(
                TelegramAuthorizedChat.chat_id == chat_id,
                TelegramAuthorizedChat.is_active.is_(True),
            )
        )
        return row is not None

    async def _authorized_chat_ids(self) -> list[int]:
        rows = await self.session.scalars(
            select(TelegramAuthorizedChat.chat_id).where(
                TelegramAuthorizedChat.is_active.is_(True)
            )
        )
        return list(rows)

    async def _bot_admin(self) -> Optional[User]:
        if not settings.TELEGRAM_BOT_ADMIN_EMAIL:
            logger.error("telegram_bot_admin_email_not_configured")
            return None
        return await self.session.scalar(
            select(User).where(User.email == settings.TELEGRAM_BOT_ADMIN_EMAIL)
        )

    # ------------------------------------------------------------------
    # Outgoing notifications
    # ------------------------------------------------------------------
    async def notify_deposit_submitted(self, payment_request: PaymentRequest, user: User) -> None:
        chat_ids = await self._authorized_chat_ids()
        if not chat_ids:
            return

        caption = (
            "🟡 <b>New Deposit Request</b>\n\n"
            f"👤 <b>Name:</b> {user.full_name}\n"
            f"✉️ <b>Email:</b> {user.email}\n"
            f"💰 <b>Amount:</b> ₹{payment_request.amount}\n"
            f"🔢 <b>UTR:</b> <code>{payment_request.utr_number}</code>\n"
            f"🧾 <b>Txn No:</b> <code>{payment_request.txn_no}</code>\n"
            f"🆔 <b>Request:</b> #{payment_request.short_id}"
        )
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Confirm", "callback_data": f"{_CONFIRM_PREFIX}{payment_request.id}"},
                    {"text": "❌ Decline", "callback_data": f"{_DECLINE_PREFIX}{payment_request.id}"},
                ]
            ]
        }
        for chat_id in chat_ids:
            await telegram_client.send_photo(
                chat_id, payment_request.screenshot_url, caption, reply_markup
            )

    async def notify_withdrawal_submitted(self, withdrawal: WithdrawalRequest, user: User) -> None:
        chat_ids = await self._authorized_chat_ids()
        if not chat_ids:
            return

        details_lines = "\n".join(
            f"    {k}: {v}" for k, v in (withdrawal.method_details or {}).items()
        )
        text = (
            "🔵 <b>New Withdrawal Request</b>\n\n"
            f"👤 <b>Name:</b> {user.full_name}\n"
            f"✉️ <b>Email:</b> {user.email}\n"
            f"💰 <b>Amount:</b> ₹{withdrawal.amount}\n"
            f"🏦 <b>Method:</b> {withdrawal.method_type.value}\n"
            f"{details_lines}\n"
            f"🧾 <b>Txn No:</b> <code>{withdrawal.txn_no}</code>\n"
            f"🆔 <b>Request:</b> #{withdrawal.short_id}\n\n"
            "ℹ️ Withdrawals are info-only here — approve/reject from the admin panel."
        )
        for chat_id in chat_ids:
            await telegram_client.send_message(chat_id, text)

    # ------------------------------------------------------------------
    # Incoming updates
    # ------------------------------------------------------------------
    async def handle_update(self, update: dict) -> None:
        if "message" in update:
            await self._handle_message(update["message"])
        elif "callback_query" in update:
            await self._handle_callback(update["callback_query"])

    async def _handle_message(self, message: dict) -> None:
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        text = (message.get("text") or "").strip()
        if chat_id is None:
            return

        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            code = parts[1].strip() if len(parts) > 1 else ""
            if code == settings.TELEGRAM_AUTH_CODE:
                title = chat.get("title") or chat.get("username") or chat.get("first_name")
                await self.authorize_chat(chat_id, title)
                await telegram_client.send_message(
                    chat_id,
                    "✅ Authorized. You'll now receive deposit and withdrawal notifications here.",
                )
            else:
                await telegram_client.send_message(
                    chat_id, "🔒 Send /start <code> with the correct access code to authorize this chat."
                )
            return

        if not await self.is_authorized(chat_id):
            await telegram_client.send_message(
                chat_id, "🔒 This chat isn't authorized. Send /start <code> first."
            )

    async def _handle_callback(self, callback: dict) -> None:
        callback_id = callback["id"]
        chat = callback.get("message", {}).get("chat", {})
        chat_id = chat.get("id")
        message_id = callback.get("message", {}).get("message_id")
        data = callback.get("data", "")

        if chat_id is None or not await self.is_authorized(chat_id):
            await telegram_client.answer_callback_query(
                callback_id, "Not authorized.", show_alert=True
            )
            return

        admin = await self._bot_admin()
        if admin is None:
            await telegram_client.answer_callback_query(
                callback_id, "Bot admin account not configured on the server.", show_alert=True
            )
            return

        payment_service = PaymentService(self.session)

        if data.startswith(_CONFIRM_PREFIX):
            request_id = data[len(_CONFIRM_PREFIX):]
            await self._resolve_deposit(
                payment_service, admin, request_id, approve=True,
                chat_id=chat_id, message_id=message_id, callback_id=callback_id,
            )
        elif data.startswith(_DECLINE_PREFIX):
            request_id = data[len(_DECLINE_PREFIX):]
            await self._resolve_deposit(
                payment_service, admin, request_id, approve=False,
                chat_id=chat_id, message_id=message_id, callback_id=callback_id,
            )
        else:
            await telegram_client.answer_callback_query(callback_id, "Unknown action.")

    async def _resolve_deposit(
        self,
        payment_service: PaymentService,
        admin: User,
        request_id: str,
        approve: bool,
        chat_id: int,
        message_id: Optional[int],
        callback_id: str,
    ) -> None:
        from uuid import UUID

        try:
            payment_request_id = UUID(request_id)
        except ValueError:
            await telegram_client.answer_callback_query(callback_id, "Invalid request id.")
            return

        try:
            if approve:
                payment_request = await payment_service.approve(
                    admin=admin, payment_request_id=payment_request_id
                )
                status_line = "✅ <b>APPROVED</b>"
            else:
                payment_request = await payment_service.reject(
                    admin=admin,
                    payment_request_id=payment_request_id,
                    reason=PaymentRejectionReason.OTHER,
                    note="Declined via Telegram bot",
                )
                status_line = "❌ <b>DECLINED</b>"
        except Exception as exc:  # noqa: BLE001
            logger.exception("telegram_deposit_resolution_failed")
            await telegram_client.answer_callback_query(
                callback_id, f"Failed: {exc}", show_alert=True
            )
            return

        await telegram_client.answer_callback_query(callback_id, "Done.")
        if message_id is not None:
            user = await self.session.get(User, payment_request.user_id)
            caption = (
                f"{status_line}\n\n"
                f"👤 <b>Name:</b> {user.full_name}\n"
                f"✉️ <b>Email:</b> {user.email}\n"
                f"💰 <b>Amount:</b> ₹{payment_request.amount}\n"
                f"🔢 <b>UTR:</b> <code>{payment_request.utr_number}</code>\n"
                f"🧾 <b>Txn No:</b> <code>{payment_request.txn_no}</code>\n"
                f"🆔 <b>Request:</b> #{payment_request.short_id}"
            )
            await telegram_client.edit_message_caption(chat_id, message_id, caption)
