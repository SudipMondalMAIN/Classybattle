"""
Cloudflare Turnstile captcha verification, used to gate /auth/signup
and /auth/login against bots.
"""
import httpx

from app.config.settings import settings
from app.core.exceptions import BadRequestException
from app.core.logging import get_logger

logger = get_logger("captcha")


async def verify_captcha(token: str | None, remote_ip: str | None = None) -> None:
    """Raises BadRequestException if the Turnstile token is missing/invalid.

    No-op when TURNSTILE_SECRET_KEY isn't configured, so local dev and
    tests don't need a real captcha token.
    """
    if not settings.TURNSTILE_SECRET_KEY:
        return

    if not token:
        raise BadRequestException("Captcha verification is required")

    payload = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(settings.TURNSTILE_VERIFY_URL, data=payload)
            resp.raise_for_status()
            result = resp.json()
    except httpx.HTTPError as exc:
        logger.error("captcha_verify_request_failed", error=str(exc))
        raise BadRequestException("Could not verify captcha, please try again") from exc

    if not result.get("success"):
        logger.warning("captcha_verify_rejected", errors=result.get("error-codes"))
        raise BadRequestException("Captcha verification failed, please try again")
