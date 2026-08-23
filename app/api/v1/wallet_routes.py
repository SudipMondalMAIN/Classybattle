"""
Wallet API routes — Enterprise Wallet System (Phase 8).
"""
import math
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user, require_admin
from app.models.payment import PaymentRequest
from app.models.wallet_transaction import WalletTransaction, WalletTransactionStatus, WalletTransactionType
from app.models.withdrawal import WithdrawalRequest
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.core.exceptions import NotFoundException
from app.schemas.wallet import (
    AdminWalletAdjustmentRequest,
    AdminWalletCreditRequest,
    AdminWalletDebitRequest,
    AdminWalletFreezeRequest,
    PaginatedWalletTransactions,
    WalletHoldRequest,
    WalletRead,
    WalletReadWithTotal,
    WalletReleaseHoldRequest,
    WalletTransactionRead,
)
from app.services.wallet_service import WalletService

router = APIRouter(tags=["Wallet"])

# reference_type values that have a human-facing txn_no on another table.
_DEPOSIT_REF_TYPE = "payment_deposit"
_WITHDRAWAL_REF_TYPE = "withdrawal_request"


async def _to_wallet_transaction_reads(
    session: AsyncSession, transactions: list[WalletTransaction]
) -> list[WalletTransactionRead]:
    """Batch-attaches txn_no to deposit/withdrawal rows in one query per
    type, instead of one lookup per row."""
    deposit_ids = [
        UUID(t.reference_id)
        for t in transactions
        if t.reference_type == _DEPOSIT_REF_TYPE and t.reference_id
    ]
    withdrawal_ids = [
        UUID(t.reference_id)
        for t in transactions
        if t.reference_type == _WITHDRAWAL_REF_TYPE and t.reference_id
    ]

    txn_no_by_id: dict[str, str] = {}
    if deposit_ids:
        result = await session.execute(
            select(PaymentRequest.id, PaymentRequest.txn_no).where(
                PaymentRequest.id.in_(deposit_ids)
            )
        )
        txn_no_by_id.update({str(pid): txn_no for pid, txn_no in result.all()})
    if withdrawal_ids:
        result = await session.execute(
            select(WithdrawalRequest.id, WithdrawalRequest.txn_no).where(
                WithdrawalRequest.id.in_(withdrawal_ids)
            )
        )
        txn_no_by_id.update({str(wid): txn_no for wid, txn_no in result.all()})

    reads = []
    for t in transactions:
        data = WalletTransactionRead.model_validate(t).model_dump()
        data["txn_no"] = txn_no_by_id.get(t.reference_id)
        reads.append(WalletTransactionRead(**data))
    return reads


def _to_wallet_with_total(wallet) -> WalletReadWithTotal:
    data = WalletRead.model_validate(wallet).model_dump()
    data["total_balance"] = wallet.available_balance + wallet.locked_balance
    return WalletReadWithTotal(**data)


# ----------------------------------------------------------------------
# Current user's wallet
# ----------------------------------------------------------------------
@router.get("/wallet", response_model=WalletReadWithTotal)
async def get_my_wallet(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = WalletService(session)
    wallet = await service.get_or_create_wallet(current_user)
    return _to_wallet_with_total(wallet)


@router.get("/wallet/transactions", response_model=PaginatedWalletTransactions)
async def list_my_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    type: Optional[WalletTransactionType] = Query(None),
    status: Optional[WalletTransactionStatus] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = WalletService(session)
    items, total = await service.list_transactions(
        current_user,
        page=page,
        page_size=page_size,
        type_=type,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedWalletTransactions(
        items=await _to_wallet_transaction_reads(session, list(items)),
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/wallet/transactions/{transaction_id}", response_model=WalletTransactionRead)
async def get_my_transaction_details(
    transaction_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = WalletService(session)
    txn = await service.get_transaction_details(current_user, transaction_id)
    reads = await _to_wallet_transaction_reads(session, [txn])
    return reads[0]


@router.post("/wallet/hold", response_model=WalletTransactionRead, status_code=201)
async def hold_funds(
    payload: WalletHoldRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = WalletService(session)
    txn = await service.hold(
        current_user,
        amount=payload.amount,
        reference_type=payload.reference_type,
        reference_id=payload.reference_id,
        description=payload.description,
    )
    return WalletTransactionRead.model_validate(txn)


@router.post("/wallet/release-hold", response_model=WalletTransactionRead)
async def release_hold(
    payload: WalletReleaseHoldRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = WalletService(session)
    txn = await service.release_hold(
        current_user,
        hold_transaction_id=payload.hold_transaction_id,
        capture=False,
        description=payload.description,
    )
    return WalletTransactionRead.model_validate(txn)


# ----------------------------------------------------------------------
# Admin wallet management
# ----------------------------------------------------------------------
async def _resolve_target_user(user_id: UUID, session: AsyncSession) -> User:
    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(user_id)
    if user is None:
        raise NotFoundException("User not found")
    return user


# NOTE: static-path routes (e.g. "/admin/wallets/transactions") MUST be
# registered before the dynamic "/admin/wallets/{user_id}" route below.
# FastAPI/Starlette matches routes in registration order, so if the
# {user_id} route comes first, a request to .../transactions gets
# captured by it with user_id="transactions", which then fails UUID
# parsing (422 uuid_parsing error). Keep this route above admin_get_wallet.
@router.get("/admin/wallets/transactions", response_model=PaginatedWalletTransactions)
async def admin_list_transactions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[UUID] = Query(None),
    type: Optional[WalletTransactionType] = Query(None),
    status: Optional[WalletTransactionStatus] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = WalletService(session)
    items, total = await service.list_transactions_admin(
        page=page,
        page_size=page_size,
        user_id=user_id,
        type_=type,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedWalletTransactions(
        items=await _to_wallet_transaction_reads(session, list(items)),
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/admin/wallets/{user_id}", response_model=WalletReadWithTotal)
async def admin_get_wallet(
    user_id: UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = WalletService(session)
    wallet = await service.get_wallet_for_admin(user_id)
    return _to_wallet_with_total(wallet)


@router.post("/admin/wallets/{user_id}/adjust", response_model=WalletTransactionRead)
async def admin_adjust_wallet(
    user_id: UUID,
    payload: AdminWalletAdjustmentRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = WalletService(session)
    target_user = await _resolve_target_user(user_id, session)
    txn = await service.admin_adjust(
        target_user=target_user, amount=payload.amount, reason=payload.reason, admin=admin
    )
    return WalletTransactionRead.model_validate(txn)


@router.post("/admin/wallets/{user_id}/credit", response_model=WalletTransactionRead)
async def admin_credit_wallet(
    user_id: UUID,
    payload: AdminWalletCreditRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = WalletService(session)
    target_user = await _resolve_target_user(user_id, session)
    txn = await service.admin_credit(
        target_user=target_user,
        amount=payload.amount,
        reason=payload.reason,
        admin=admin,
        reference_type=payload.reference_type,
        reference_id=payload.reference_id,
        source=payload.source,
    )
    return WalletTransactionRead.model_validate(txn)


@router.post("/admin/wallets/{user_id}/debit", response_model=WalletTransactionRead)
async def admin_debit_wallet(
    user_id: UUID,
    payload: AdminWalletDebitRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = WalletService(session)
    target_user = await _resolve_target_user(user_id, session)
    txn = await service.admin_debit(
        target_user=target_user,
        amount=payload.amount,
        reason=payload.reason,
        admin=admin,
        reference_type=payload.reference_type,
        reference_id=payload.reference_id,
    )
    return WalletTransactionRead.model_validate(txn)


@router.patch("/admin/wallets/{user_id}/freeze", response_model=WalletReadWithTotal)
async def admin_freeze_wallet(
    user_id: UUID,
    payload: AdminWalletFreezeRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = WalletService(session)
    target_user = await _resolve_target_user(user_id, session)
    wallet = await service.admin_set_frozen(
        target_user=target_user, is_frozen=payload.is_frozen, reason=payload.reason, admin=admin
    )
    return _to_wallet_with_total(wallet)