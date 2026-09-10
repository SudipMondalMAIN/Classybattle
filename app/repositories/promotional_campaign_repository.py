"""
Repository for admin-defined promotional campaigns.
"""
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.promotional_campaign import PromotionalCampaign
from app.repositories.base import BaseRepository


class PromotionalCampaignRepository(BaseRepository[PromotionalCampaign]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PromotionalCampaign)

    async def list_active(self) -> Sequence[PromotionalCampaign]:
        stmt = select(PromotionalCampaign).where(
            PromotionalCampaign.is_active.is_(True),
            PromotionalCampaign.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_for_admin(self) -> Sequence[PromotionalCampaign]:
        stmt = (
            select(PromotionalCampaign)
            .where(PromotionalCampaign.deleted_at.is_(None))
            .order_by(PromotionalCampaign.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
