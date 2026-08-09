"""
Withdrawal API routes.

User side: request a withdrawal against a saved payment method, view own
requests, cancel while still pending.

Admin side: list/inspect all withdrawal requests, mark a request
completed (funds paid out manually) or cancel it (refunds the user).
"""
import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user, require_admin, require_not_banned
from app.models.user import User
from app.models.withdrawal import WithdrawalStatus
from app.schemas.withdrawal import (
    PaginatedWithdrawalRequests,
    WithdrawalCancelRequest,
    WithdrawalCompleteRequest,
    WithdrawalRequestCreate,
    WithdrawalRequestRead,
)
from app.services.withdrawal_service import WithdrawalService

router = APIRouter(tags=["Withdrawals"])


# ----------------------------------------------------------------------
# User-facing
# ----------------------------------------------------------------------
@router.post("/withdrawals", response_model=WithdrawalRequestRead, status_code=201)
async def request_withdrawal(
    payload: WithdrawalRequestCreate,
    current_user: User = Depends(require_not_banned),
    session: AsyncSession = Depends(get_db_session),
):
    service = WithdrawalService(session)
    withdrawal = await service.request_withdrawal(current_user, payload)
    return WithdrawalRequestRead.model_validate(withdrawal)


@router.get("/withdrawals", response_model=PaginatedWithdrawalRequests)
async def list_my_withdrawals(
    status_filter: Optional[WithdrawalStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = WithdrawalService(session)
    rows, total = await service.list_my_requests(
        current_user, page=page, page_size=page_size, status=status_filter
    )
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedWithdrawalRequests(
        items=[WithdrawalRequestRead.model_validate(w) for w in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/withdrawals/{withdrawal_id}", response_model=WithdrawalRequestRead)
async def get_my_withdrawal(
    withdrawal_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = WithdrawalService(session)
    withdrawal = await service.get_owned(current_user, withdrawal_id)
    return WithdrawalRequestRead.model_validate(withdrawal)


@router.post("/withdrawals/{withdrawal_id}/cancel", response_model=WithdrawalRequestRead)
async def cancel_my_withdrawal(
    withdrawal_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = WithdrawalService(session)
    withdrawal = await service.cancel_own_request(current_user, withdrawal_id)
    return WithdrawalRequestRead.model_validate(withdrawal)


# ----------------------------------------------------------------------
# Admin-facing
# ----------------------------------------------------------------------
@router.get("/admin/withdrawals", response_model=PaginatedWithdrawalRequests)
async def admin_list_withdrawals(
    status_filter: Optional[WithdrawalStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
    _admin=Depends(require_admin),
):
    service = WithdrawalService(session)
    rows, total = await service.list_admin_requests(page=page, page_size=page_size, status=status_filter)
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedWithdrawalRequests(
        items=[WithdrawalRequestRead.model_validate(w) for w in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/admin/withdrawals/short/{short_id}", response_model=WithdrawalRequestRead)
async def admin_get_withdrawal_by_short_id(
    short_id: int,
    session: AsyncSession = Depends(get_db_session),
    _admin=Depends(require_admin),
):
    """Admin lookup by the human-friendly 8-digit short_id."""
    service = WithdrawalService(session)
    withdrawal = await service.get_for_admin_by_short_id(short_id)
    return WithdrawalRequestRead.model_validate(withdrawal)


@router.get("/admin/withdrawals/txn/{txn_no}", response_model=WithdrawalRequestRead)
async def admin_get_withdrawal_by_txn_no(
    txn_no: str,
    session: AsyncSession = Depends(get_db_session),
    _admin=Depends(require_admin),
):
    """Admin lookup by the 10-digit transaction number shown to the user."""
    service = WithdrawalService(session)
    withdrawal = await service.get_for_admin_by_txn_no(txn_no)
    return WithdrawalRequestRead.model_validate(withdrawal)


@router.get("/admin/withdrawals/{withdrawal_id}", response_model=WithdrawalRequestRead)
async def admin_get_withdrawal(
    withdrawal_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    _admin=Depends(require_admin),
):
    service = WithdrawalService(session)
    withdrawal = await service.get_for_admin(withdrawal_id)
    return WithdrawalRequestRead.model_validate(withdrawal)


@router.post("/admin/withdrawals/{withdrawal_id}/complete", response_model=WithdrawalRequestRead)
async def admin_complete_withdrawal(
    withdrawal_id: UUID,
    payload: WithdrawalCompleteRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = WithdrawalService(session)
    withdrawal = await service.complete(admin, withdrawal_id, payload.admin_note)
    return WithdrawalRequestRead.model_validate(withdrawal)


@router.post("/admin/withdrawals/{withdrawal_id}/cancel", response_model=WithdrawalRequestRead)
async def admin_cancel_withdrawal(
    withdrawal_id: UUID,
    payload: WithdrawalCancelRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = WithdrawalService(session)
    withdrawal = await service.cancel(admin, withdrawal_id, payload.admin_note)
    return WithdrawalRequestRead.model_validate(withdrawal)