"""
OTP service — handles generation, rate limiting, hashing, and verification
of OTPs used by both signup and forgot-password flows.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.core.exceptions import OTPException, TooManyRequestsException
from app.core.logging import get_logger
from app.models.otp import OTP, OTPPurpose
from app.repositories.otp_repository import OTPRepository
from app.utils.otp_util import generate_numeric_otp, hash_otp, verify_otp_hash

logger = get_logger(__name__)


class OTPService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = OTPRepository(session)

    async def generate_and_store_otp(self, email: str, purpose: OTPPurpose) -> str:
        """Generate a new OTP, enforcing resend cooldown + hourly rate limits."""
        email = email.lower()
        now = datetime.now(timezone.utc)

        latest = await self.repo.get_latest_active(email, purpose)
        if latest is not None:
            cooldown_until = latest.created_at + timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)
            if now < cooldown_until:
                wait_seconds = int((cooldown_until - now).total_seconds())
                raise TooManyRequestsException(
                    f"Please wait {wait_seconds} seconds before requesting another OTP"
                )

        one_hour_ago = now - timedelta(hours=1)
        recent_count = await self.repo.count_recent(email, purpose, one_hour_ago)
        if recent_count >= settings.OTP_MAX_PER_HOUR:
            raise TooManyRequestsException(
                "OTP request limit reached. Please try again after some time."
            )

        # Invalidate any previously active OTPs for this purpose before issuing a new one
        await self.repo.invalidate_active_otps(email, purpose)

        otp_code = generate_numeric_otp()
        await self.repo.create(
            email=email,
            otp_hash=hash_otp(otp_code),
            purpose=purpose,
            expires_at=now + timedelta(minutes=settings.OTP_EXPIRY_MINUTES),
            attempts=0,
            is_used=False,
        )

        logger.info("otp_generated", email=email, purpose=purpose.value)
        return otp_code

    async def verify_otp(
        self, email: str, purpose: OTPPurpose, otp_code: str, mark_used: bool = True
    ) -> OTP:
        """
        Verify an OTP. Raises OTPException on any failure.
        When `mark_used` is True (default), consumes the OTP so it cannot be reused.
        Pass `mark_used=False` for a non-destructive "check only" verification
        (e.g. confirming a reset-password OTP before showing the reset form).
        """
        email = email.lower()
        otp_entry = await self.repo.get_latest_active(email, purpose)

        if otp_entry is None:
            raise OTPException("No active OTP found. Please request a new one.")

        if otp_entry.attempts >= settings.OTP_MAX_ATTEMPTS:
            raise OTPException("Maximum verification attempts exceeded. Please request a new OTP.")

        if not verify_otp_hash(otp_code, otp_entry.otp_hash):
            otp_entry.attempts += 1
            await self.session.flush()
            raise OTPException("Invalid OTP")

        if mark_used:
            otp_entry.is_used = True
        await self.session.flush()

        logger.info("otp_verified", email=email, purpose=purpose.value, mark_used=mark_used)
        return otp_entry
