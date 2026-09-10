"""
Admin routes for automatic promotional notification campaigns.

Creating a campaign here doesn't send anything itself -- it just writes
the schedule. `app.core.scheduler`'s `_send_due_promotional_campaigns`
job (ticks every PROMOTIONAL_CAMPAIGN_CHECK_INTERVAL_MINUTES) is what
actually fires it once due, via PromotionalCampaignService.send_due_campaigns().
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import require_admin
from app.models.user import User
from app.schemas.promotional_campaign import (
    PromotionalCampaignCreate,
    PromotionalCampaignRead,
    PromotionalCampaignSetActiveRequest,
)
from app.services.promotional_campaign_service import PromotionalCampaignService

router = APIRouter(prefix="/admin/promotional-campaigns", tags=["Admin - Promotional Campaigns"])


@router.post("", response_model=PromotionalCampaignRead)
async def create_promotional_campaign(
    payload: PromotionalCampaignCreate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PromotionalCampaignService(session)
    campaign = await service.create(
        admin=admin,
        title=payload.title,
        body=payload.body,
        schedule_type=payload.schedule_type,
        scheduled_at=payload.scheduled_at,
        send_hour=payload.send_hour,
        send_minute=payload.send_minute,
        interval_hours=payload.interval_hours,
        send_push=payload.send_push,
        send_email=payload.send_email,
    )
    return PromotionalCampaignRead.model_validate(campaign)


@router.get("", response_model=list[PromotionalCampaignRead])
async def list_promotional_campaigns(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PromotionalCampaignService(session)
    campaigns = await service.list_for_admin()
    return [PromotionalCampaignRead.model_validate(c) for c in campaigns]


@router.patch("/{campaign_id}/active", response_model=PromotionalCampaignRead)
async def set_promotional_campaign_active(
    campaign_id: UUID,
    payload: PromotionalCampaignSetActiveRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Pause/resume a campaign without deleting it. A paused DAILY or
    INTERVAL_HOURS campaign simply stops firing until re-activated; a
    ONCE campaign that was already sent stays inactive regardless."""
    service = PromotionalCampaignService(session)
    campaign = await service.set_active(campaign_id, payload.is_active)
    return PromotionalCampaignRead.model_validate(campaign)


@router.delete("/{campaign_id}", status_code=204)
async def delete_promotional_campaign(
    campaign_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PromotionalCampaignService(session)
    await service.delete(campaign_id)
