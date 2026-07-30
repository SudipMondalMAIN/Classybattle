"""
OTP repository.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.otp import OTP, OTPPurpose
from app.repositories.base import BaseRepository


class OTPRepository(BaseRepository[OTP]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, OTP)

    async def get_latest_active(self, email: str, purpose: OTPPurpose) -> Optional[OTP]:
        stmt = (
            select(OTP)
            .where(
                OTP.email == email.lower(),
                OTP.purpose == purpose,
                OTP.is_used.is_(False),
                OTP.deleted_at.is_(None),
                OTP.expires_at > datetime.now(timezone.utc),
            )
            .order_by(desc(OTP.created_at))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_recent(self, email: str, purpose: OTPPurpose, since: datetime) -> int:
        stmt = select(OTP).where(
            OTP.email == email.lower(),
            OTP.purpose == purpose,
            OTP.created_at >= since,
        )
        result = await self.session.execute(stmt)
        return len(result.scalars().all())

    async def invalidate_active_otps(self, email: str, purpose: OTPPurpose) -> None:
        stmt = select(OTP).where(
            OTP.email == email.lower(),
            OTP.purpose == purpose,
            OTP.is_used.is_(False),
        )
        result = await self.session.execute(stmt)
        for otp in result.scalars().all():
            otp.is_used = True
        await self.session.flush()
