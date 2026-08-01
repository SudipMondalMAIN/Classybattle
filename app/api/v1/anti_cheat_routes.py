"""
Anti-Cheat API routes — Phase 16.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import require_admin
from app.models.security import FraudFlagStatus, FraudFlagType
from app.models.user import User
from app.schemas.security import (
    AntiCheatScanRequest,
    AntiCheatScanResult,
    FraudFlagRead,
    FraudFlagReviewRequest,
    PaginatedFraudFlags,
)
from app.services.anti_cheat_service import AntiCheatService

router = APIRouter(prefix="/admin/anti-cheat", tags=["Anti-Cheat"])


@router.post("/scan", response_model=AntiCheatScanResult)
async def run_anti_cheat_scan(
    payload: AntiCheatScanRequest,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Run duplicate-account, duplicate-team, multiple-registration,
    match-abuse and wallet-abuse detectors, optionally scoped to a
    tournament and/or a specific user."""
    service = AntiCheatService(session)
    result = await service.run_full_scan(tournament_id=payload.tournament_id, user_id=payload.user_id)
    return AntiCheatScanResult(**result)


@router.get("/flags", response_model=PaginatedFraudFlags)
async def list_fraud_flags(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[FraudFlagStatus] = Query(None),
    flag_type: Optional[FraudFlagType] = Query(None),
    user_id: Optional[UUID] = Query(None),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = AntiCheatService(session)
    items, total = await service.list_flags(page, page_size, status, flag_type, user_id)
    return PaginatedFraudFlags(
        items=[FraudFlagRead.model_validate(i) for i in items], total=total, page=page, page_size=page_size
    )


@router.patch("/flags/{flag_id}/review", response_model=FraudFlagRead)
async def review_fraud_flag(
    flag_id: UUID,
    payload: FraudFlagReviewRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = AntiCheatService(session)
    flag = await service.review_flag(flag_id, admin.id, payload.status, payload.review_notes)
    return FraudFlagRead.model_validate(flag)
