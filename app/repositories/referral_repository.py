"""
Referral repository — DB access for ReferralConfig, Referral, and
ReferralMilestoneClaim.
"""
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.referral import (
    DEFAULT_MILESTONE_RULES,
    Referral,
    ReferralConfig,
    ReferralMilestoneClaim,
    ReferralStatus,
)
from app.repositories.base import BaseRepository


class ReferralConfigRepository(BaseRepository[ReferralConfig]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ReferralConfig)

    async def get_singleton(self) -> ReferralConfig:
        """Returns the single global config row, creating it with
        defaults on first access (e.g. right after this feature's
        migration runs on a fresh DB)."""
        stmt = select(ReferralConfig).order_by(ReferralConfig.created_at.asc()).limit(1)
        result = await self.session.execute(stmt)
        config = result.scalar_one_or_none()
        if config is None:
            config = ReferralConfig(milestone_rules=DEFAULT_MILESTONE_RULES)
            self.session.add(config)
            await self.session.flush()
        return config


class ReferralRepository(BaseRepository[Referral]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Referral)

    async def get_by_referee_id(self, referee_id: UUID) -> Optional[Referral]:
        stmt = select(Referral).where(Referral.referee_id == referee_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, referral_id: UUID) -> Optional[Referral]:
        stmt = (
            select(Referral)
            .where(Referral.id == referral_id)
            .options(selectinload(Referral.referrer), selectinload(Referral.referee))
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def count_eligible_by_ip(
        self, ip_address: str, *, exclude_referral_id: Optional[UUID] = None
    ) -> int:
        """Non-rejected referrals (PENDING/ON_HOLD/COMPLETED) sharing this
        apply-time IP -- used for the "max N accounts per IP" fraud check."""
        stmt = select(func.count()).select_from(Referral).where(
            Referral.ip_address == ip_address,
            Referral.status != ReferralStatus.REJECTED,
        )
        if exclude_referral_id is not None:
            stmt = stmt.where(Referral.id != exclude_referral_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def has_duplicate_device(
        self, device_id: str, *, exclude_referral_id: Optional[UUID] = None
    ) -> bool:
        if not device_id:
            return False
        stmt = select(func.count()).select_from(Referral).where(
            Referral.device_id == device_id,
            Referral.status != ReferralStatus.REJECTED,
        )
        if exclude_referral_id is not None:
            stmt = stmt.where(Referral.id != exclude_referral_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one()) > 0

    async def count_completed_by_referrer(self, referrer_id: UUID) -> int:
        stmt = select(func.count()).select_from(Referral).where(
            Referral.referrer_id == referrer_id,
            Referral.status == ReferralStatus.COMPLETED,
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_by_referrer(self, referrer_id: UUID) -> Sequence[Referral]:
        stmt = (
            select(Referral)
            .where(Referral.referrer_id == referrer_id)
            .order_by(Referral.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_pending_admin(self) -> Sequence[Referral]:
        """ON_HOLD referrals awaiting admin approve/reject, newest first."""
        stmt = (
            select(Referral)
            .where(Referral.status == ReferralStatus.ON_HOLD)
            .options(selectinload(Referral.referrer), selectinload(Referral.referee))
            .order_by(Referral.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_involving_user(self, user_id: UUID) -> Sequence[Referral]:
        """Every referral where the given user appears as either the
        referrer or the referee -- i.e. that user's full referral
        history, newest first. Used by the admin user-profile screen."""
        from sqlalchemy import or_

        stmt = (
            select(Referral)
            .where(or_(Referral.referrer_id == user_id, Referral.referee_id == user_id))
            .options(selectinload(Referral.referrer), selectinload(Referral.referee))
            .order_by(Referral.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class ReferralMilestoneClaimRepository(BaseRepository[ReferralMilestoneClaim]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ReferralMilestoneClaim)

    async def get_claimed_thresholds(self, referrer_id: UUID) -> set[int]:
        stmt = select(ReferralMilestoneClaim.threshold).where(
            ReferralMilestoneClaim.referrer_id == referrer_id
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())
