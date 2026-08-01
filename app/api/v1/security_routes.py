"""
Security API routes — Phase 16 (Login History, Device/IP Tracking,
Account Lock, Risk Scoring, Security Audit Logs).
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user, require_admin
from app.models.security import SecurityEventType
from app.models.user import User
from app.schemas.security import (
    AccountLockRead,
    AccountLockRequest,
    AccountUnlockRequest,
    LoginHistoryRead,
    PaginatedLoginHistory,
    PaginatedSecurityEvents,
    RiskScoreRead,
    SecurityEventRead,
)
from app.services.security_service import SecurityService

router = APIRouter(tags=["Security"])


# ----------------------------------------------------------------------
# Self-service: current user's own security data
# ----------------------------------------------------------------------
@router.get("/security/login-history/me", response_model=list[LoginHistoryRead])
async def my_login_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = SecurityService(session)
    items = await service.list_login_history(current_user.id, page, page_size)
    return [LoginHistoryRead.model_validate(i) for i in items]


@router.get("/security/risk-score/me", response_model=RiskScoreRead)
async def my_risk_score(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = SecurityService(session)
    profile = await service.get_risk_profile(current_user.id)
    return RiskScoreRead(**profile)


# ----------------------------------------------------------------------
# Admin: login history & security events
# ----------------------------------------------------------------------
@router.get("/admin/security/login-history", response_model=PaginatedLoginHistory)
async def admin_login_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[UUID] = Query(None),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = SecurityService(session)
    items = await service.list_login_history(user_id, page, page_size)
    return PaginatedLoginHistory(
        items=[LoginHistoryRead.model_validate(i) for i in items],
        total=len(items),
        page=page,
        page_size=page_size,
    )


@router.get("/admin/security/events", response_model=PaginatedSecurityEvents)
async def admin_list_security_events(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[UUID] = Query(None),
    event_type: Optional[SecurityEventType] = Query(None),
    resolved: Optional[bool] = Query(None),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = SecurityService(session)
    items, total = await service.list_security_events(page, page_size, user_id, event_type, resolved)
    return PaginatedSecurityEvents(
        items=[SecurityEventRead.model_validate(i) for i in items], total=total, page=page, page_size=page_size
    )


@router.patch("/admin/security/events/{event_id}/resolve", response_model=SecurityEventRead)
async def admin_resolve_security_event(
    event_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = SecurityService(session)
    event = await service.resolve_security_event(event_id, admin.id)
    return SecurityEventRead.model_validate(event)


@router.get("/admin/security/risk-score/{user_id}", response_model=RiskScoreRead)
async def admin_get_risk_score(
    user_id: UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = SecurityService(session)
    profile = await service.get_risk_profile(user_id)
    return RiskScoreRead(**profile)


# ----------------------------------------------------------------------
# Admin: account lock / unlock
# ----------------------------------------------------------------------
@router.get("/admin/security/locked-accounts", response_model=list[AccountLockRead])
async def admin_list_locked_accounts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = SecurityService(session)
    items = await service.list_locked_accounts(page, page_size)
    return [AccountLockRead.model_validate(i) for i in items]


@router.post("/admin/security/accounts/{user_id}/lock", response_model=AccountLockRead)
async def admin_lock_account(
    user_id: UUID,
    payload: AccountLockRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = SecurityService(session)
    lock = await service.lock_account(user_id=user_id, reason=payload.reason, locked_by=admin.id)
    await session.commit()
    return AccountLockRead.model_validate(lock)


@router.post("/admin/security/accounts/{user_id}/unlock", response_model=AccountLockRead)
async def admin_unlock_account(
    user_id: UUID,
    payload: AccountUnlockRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = SecurityService(session)
    lock = await service.unlock_account(user_id=user_id, unlocked_by=admin.id, reason=payload.reason)
    return AccountLockRead.model_validate(lock)
