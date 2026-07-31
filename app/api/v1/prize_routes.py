"""
Prize Pool & Prize Distribution API routes — Phase 10.
"""
import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user, require_admin
from app.models.prize import PrizePayoutStatus, PrizePoolStatus
from app.models.user import User
from app.schemas.prize import (
    AdminManualPayoutRequest,
    AssignWinnersRequest,
    PaginatedPrizePayouts,
    PaginatedPrizePools,
    PrizePayoutRead,
    PrizePoolCreate,
    PrizePoolRead,
    PrizePoolUpdate,
)
from app.services.prize_service import PrizeService

router = APIRouter(tags=["Prize Pool"])


def _rules_to_json(rules) -> list[dict]:
    """Converts Pydantic PrizeRankRule models into plain, JSON-safe dicts
    (Decimal values stringified) for storage in the PortableJSONB column."""
    out = []
    for r in rules:
        entry = {"rank": r.rank}
        if r.percentage is not None:
            entry["percentage"] = str(r.percentage)
        if r.amount is not None:
            entry["amount"] = str(r.amount)
        out.append(entry)
    return out


def _paginate(total: int, page: int, page_size: int) -> int:
    return math.ceil(total / page_size) if total else 0


# ----------------------------------------------------------------------
# Admin: prize pool configuration
# ----------------------------------------------------------------------
@router.post(
    "/admin/tournaments/{tournament_id}/prize-pool",
    response_model=PrizePoolRead,
    status_code=201,
)
async def create_prize_pool(
    tournament_id: UUID,
    payload: PrizePoolCreate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PrizeService(session)
    pool = await service.create_prize_pool(
        tournament_id=tournament_id,
        admin=admin,
        total_amount=payload.total_amount,
        distribution_type=payload.distribution_type,
        distribution_rules=_rules_to_json(payload.distribution_rules),
    )
    return PrizePoolRead.model_validate(pool)


@router.patch(
    "/admin/tournaments/{tournament_id}/prize-pool",
    response_model=PrizePoolRead,
)
async def update_prize_pool(
    tournament_id: UUID,
    payload: PrizePoolUpdate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PrizeService(session)
    pool = await service.update_prize_pool(
        tournament_id=tournament_id,
        admin=admin,
        total_amount=payload.total_amount,
        distribution_type=payload.distribution_type,
        distribution_rules=(
            _rules_to_json(payload.distribution_rules)
            if payload.distribution_rules is not None
            else None
        ),
    )
    return PrizePoolRead.model_validate(pool)


@router.post(
    "/admin/tournaments/{tournament_id}/prize-pool/publish",
    response_model=PrizePoolRead,
)
async def publish_prize_pool(
    tournament_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PrizeService(session)
    pool = await service.publish_prize_pool(tournament_id=tournament_id, admin=admin)
    return PrizePoolRead.model_validate(pool)


@router.post(
    "/admin/tournaments/{tournament_id}/prize-pool/cancel",
    response_model=PrizePoolRead,
)
async def cancel_prize_pool(
    tournament_id: UUID,
    reason: str = Query(..., min_length=3, max_length=500),
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PrizeService(session)
    pool = await service.cancel_prize_pool(tournament_id=tournament_id, admin=admin, reason=reason)
    return PrizePoolRead.model_validate(pool)


@router.get("/admin/prize-pools", response_model=PaginatedPrizePools)
async def admin_list_prize_pools(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[PrizePoolStatus] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PrizeService(session)
    items, total = await service.list_prize_pools(
        page=page, page_size=page_size, status=status, sort_by=sort_by, sort_order=sort_order
    )
    return PaginatedPrizePools(
        items=[PrizePoolRead.model_validate(p) for p in items],
        total=total, page=page, page_size=page_size, total_pages=_paginate(total, page, page_size),
    )


# ----------------------------------------------------------------------
# Public / participant: prize pool visibility
# ----------------------------------------------------------------------
@router.get("/tournaments/{tournament_id}/prize-pool", response_model=PrizePoolRead)
async def get_tournament_prize_pool(
    tournament_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    service = PrizeService(session)
    pool = await service.get_prize_pool(tournament_id=tournament_id)
    return PrizePoolRead.model_validate(pool)


# ----------------------------------------------------------------------
# Admin: winner assignment & distribution
# ----------------------------------------------------------------------
@router.post(
    "/admin/tournaments/{tournament_id}/prize-pool/winners",
    response_model=list[PrizePayoutRead],
    status_code=201,
)
async def assign_winners(
    tournament_id: UUID,
    payload: AssignWinnersRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PrizeService(session)
    payouts = await service.assign_winners(
        tournament_id=tournament_id,
        admin=admin,
        winners=[w.model_dump() for w in payload.winners],
    )
    return [PrizePayoutRead.model_validate(p) for p in payouts]


@router.post(
    "/admin/tournaments/{tournament_id}/prize-pool/distribute",
    response_model=list[PrizePayoutRead],
)
async def distribute_prizes(
    tournament_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PrizeService(session)
    payouts = await service.distribute_prizes(tournament_id=tournament_id, admin=admin)
    return [PrizePayoutRead.model_validate(p) for p in payouts]


@router.post(
    "/admin/prize-payouts/{payout_id}/pay",
    response_model=PrizePayoutRead,
)
async def admin_manual_payout(
    payout_id: UUID,
    payload: AdminManualPayoutRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PrizeService(session)
    payout = await service.admin_manual_payout(payout_id=payout_id, admin=admin, reason=payload.reason)
    return PrizePayoutRead.model_validate(payout)


@router.post(
    "/admin/prize-payouts/{payout_id}/retry",
    response_model=PrizePayoutRead,
)
async def retry_prize_payout(
    payout_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PrizeService(session)
    payout = await service.retry_payout(payout_id=payout_id, admin=admin)
    return PrizePayoutRead.model_validate(payout)


@router.get("/admin/prize-payouts", response_model=PaginatedPrizePayouts)
async def admin_list_prize_payouts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tournament_id: Optional[UUID] = Query(None),
    prize_pool_id: Optional[UUID] = Query(None),
    user_id: Optional[UUID] = Query(None),
    status: Optional[PrizePayoutStatus] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PrizeService(session)
    items, total = await service.list_payouts_admin(
        page=page, page_size=page_size, tournament_id=tournament_id, prize_pool_id=prize_pool_id,
        user_id=user_id, status=status, sort_by=sort_by, sort_order=sort_order,
    )
    return PaginatedPrizePayouts(
        items=[PrizePayoutRead.model_validate(p) for p in items],
        total=total, page=page, page_size=page_size, total_pages=_paginate(total, page, page_size),
    )


# ----------------------------------------------------------------------
# Public / participant: payout history
# ----------------------------------------------------------------------
@router.get("/tournaments/{tournament_id}/prize-payouts", response_model=PaginatedPrizePayouts)
async def list_tournament_prize_payouts(
    tournament_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[PrizePayoutStatus] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    session: AsyncSession = Depends(get_db_session),
):
    service = PrizeService(session)
    items, total = await service.list_payouts_for_tournament(
        tournament_id=tournament_id, page=page, page_size=page_size, status=status,
        sort_by=sort_by, sort_order=sort_order,
    )
    return PaginatedPrizePayouts(
        items=[PrizePayoutRead.model_validate(p) for p in items],
        total=total, page=page, page_size=page_size, total_pages=_paginate(total, page, page_size),
    )


@router.get("/prize-payouts/me", response_model=PaginatedPrizePayouts)
async def list_my_prize_payouts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[PrizePayoutStatus] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = PrizeService(session)
    items, total = await service.list_my_payouts(
        user=current_user, page=page, page_size=page_size, status=status,
        sort_by=sort_by, sort_order=sort_order,
    )
    return PaginatedPrizePayouts(
        items=[PrizePayoutRead.model_validate(p) for p in items],
        total=total, page=page, page_size=page_size, total_pages=_paginate(total, page, page_size),
    )


@router.get("/prize-payouts/{payout_id}", response_model=PrizePayoutRead)
async def get_prize_payout(
    payout_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = PrizeService(session)
    payout = await service.get_payout(payout_id=payout_id, user=current_user)
    return PrizePayoutRead.model_validate(payout)
