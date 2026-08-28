"""
Referral System v2 — admin routes.

Config CRUD (reward amount, min deposit, step toggles, apply window,
fraud thresholds, milestone ladder) plus the ON_HOLD review queue.
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import require_admin
from app.models.user import User
from app.schemas.referral import (
    AdminReferralListItem,
    ReferralConfigRead,
    ReferralConfigUpdate,
    ReferralRejectRequest,
    ReferralStatusItem,
)
from app.services.referral_service import ReferralService

router = APIRouter(prefix="/admin/referrals", tags=["Admin - Referrals"])


@router.get("/config", response_model=ReferralConfigRead)
async def get_referral_config(
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = ReferralService(session)
    config = await service.get_config_for_admin()
    return ReferralConfigRead.model_validate(config)


@router.patch("/config", response_model=ReferralConfigRead)
async def update_referral_config(
    payload: ReferralConfigUpdate,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Every field here is admin-tunable at any time: reward amount, min
    Add Money to qualify, whether the deposit/tournament steps are even
    required, the apply window, IP/device fraud thresholds, and the
    milestone bonus ladder."""
    service = ReferralService(session)
    config = await service.update_config(
        admin=current_user, update_data=payload.model_dump(exclude_unset=True)
    )
    return ReferralConfigRead.model_validate(config)


@router.get("/pending", response_model=list[AdminReferralListItem])
async def list_pending_referrals(
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Referrals stuck ON_HOLD by the IP/device fraud check -- Referral ID,
    Referrer, Referred User, IP, Device, Deposit/Tournament step status,
    and the risk reason -- for Approve / Reject."""
    service = ReferralService(session)
    referrals = await service.list_pending_admin()
    return [
        AdminReferralListItem(
            id=r.id,
            referrer_id=r.referrer_id,
            referrer_name=r.referrer.full_name if r.referrer else "—",
            referrer_email=r.referrer.email if r.referrer else "—",
            referee_id=r.referee_id,
            referee_name=r.referee.full_name if r.referee else "—",
            referee_email=r.referee.email if r.referee else "—",
            status=r.status,
            ip_address=r.ip_address,
            device_id=r.device_id,
            deposit_met=r.deposit_met,
            tournament_met=r.tournament_met,
            risk_flagged=r.risk_flagged,
            risk_reason=r.risk_reason,
            reward_amount=r.reward_amount,
            created_at=r.created_at,
        )
        for r in referrals
    ]


@router.post("/{referral_id}/approve", response_model=ReferralStatusItem)
async def approve_referral(
    referral_id: UUID,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = ReferralService(session)
    referral = await service.admin_approve(admin=current_user, referral_id=referral_id)
    return ReferralStatusItem(
        id=referral.id,
        referee_name=referral.referee.full_name if referral.referee else "—",
        status=referral.status,
        deposit_met=referral.deposit_met,
        tournament_met=referral.tournament_met,
        reward_amount=referral.reward_amount,
        reward_credited=referral.reward_credited,
        created_at=referral.created_at,
    )


@router.post("/{referral_id}/reject", response_model=ReferralStatusItem)
async def reject_referral(
    referral_id: UUID,
    payload: ReferralRejectRequest,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = ReferralService(session)
    referral = await service.admin_reject(
        admin=current_user, referral_id=referral_id, admin_note=payload.admin_note
    )
    return ReferralStatusItem(
        id=referral.id,
        referee_name=referral.referee.full_name if referral.referee else "—",
        status=referral.status,
        deposit_met=referral.deposit_met,
        tournament_met=referral.tournament_met,
        reward_amount=referral.reward_amount,
        reward_credited=referral.reward_credited,
        created_at=referral.created_at,
    )
