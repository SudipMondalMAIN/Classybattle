"""
Run once (locally or via `railway run` / Render shell) after deploying,
or any time TELEGRAM_WEBHOOK_SECRET / the backend domain changes:

    python scripts/set_telegram_webhook.py

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET from the environment
and registers https://api.classybattle.online/api/v1/telegram/webhook/<secret>
as the bot's webhook.
"""
import asyncio
import sys

sys.path.insert(0, ".")

from app.config.settings import settings  # noqa: E402
from app.telegram_bot.client import telegram_client  # noqa: E402

BACKEND_BASE_URL = "https://api.classybattle.online"


async def main() -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is not set.")
        return
    if not settings.TELEGRAM_WEBHOOK_SECRET:
        print("TELEGRAM_WEBHOOK_SECRET is not set — set a random string first.")
        return

    url = f"{BACKEND_BASE_URL}/api/v1/telegram/webhook/{settings.TELEGRAM_WEBHOOK_SECRET}"
    result = await telegram_client.set_webhook(url, secret_token=settings.TELEGRAM_WEBHOOK_SECRET)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
