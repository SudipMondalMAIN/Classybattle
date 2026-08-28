"""
Referral System v2 — user-facing routes.

Deliberately separate from signup: the referral code is applied from a
dedicated "Refer & Earn" screen, not the signup form.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_context import get_client_ip
from app.database.session import get_db_session
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.referral import (
    ApplyReferralCodeRequest,
    MyReferralCodeResponse,
    ReferralStatusItem,
)
from app.services.referral_service import ReferralService

router = APIRouter(prefix="/referrals", tags=["Referrals"])


@router.get("/my-code", response_model=MyReferralCodeResponse)
async def get_my_referral_code(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """The 'Refer & Earn' screen: the user's own shareable code plus
    running totals (referred / completed / pending / on-hold / earned,
    and the next milestone they're working towards)."""
    service = ReferralService(session)
    data = await service.get_my_code_and_stats(current_user)
    return MyReferralCodeResponse(**data)


@router.post("/apply", response_model=ReferralStatusItem, status_code=201)
async def apply_referral_code(
    payload: ApplyReferralCodeRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Apply someone else's referral code -- only allowed once, and only
    within the admin-configured window from the caller's own signup date."""
    service = ReferralService(session)
    referral = await service.apply_code(
        referee=current_user,
        code=payload.referral_code,
        ip_address=get_client_ip(),
        device_id=payload.device_id,
    )
    return ReferralStatusItem(
        id=referral.id,
        referee_name=current_user.full_name,
        status=referral.status,
        deposit_met=referral.deposit_met,
        tournament_met=referral.tournament_met,
        reward_amount=referral.reward_amount,
        reward_credited=referral.reward_credited,
        created_at=referral.created_at,
    )


@router.get("/history", response_model=list[ReferralStatusItem])
async def list_my_referrals(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Everyone the current user has referred, with each one's progress."""
    service = ReferralService(session)
    referrals = await service.list_my_referrals(current_user)
    return [
        ReferralStatusItem(
            id=r.id,
            referee_name=r.referee.full_name if r.referee else "—",
            status=r.status,
            deposit_met=r.deposit_met,
            tournament_met=r.tournament_met,
            reward_amount=r.reward_amount,
            reward_credited=r.reward_credited,
            created_at=r.created_at,
        )
        for r in referrals
    ]
