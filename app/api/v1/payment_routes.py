"""
Payment & Financial Operations API routes — Phase 17.
"""
import math
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationException
from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user, require_admin
from app.models.payment import PaymentProvider, PaymentRequestStatus
from app.models.user import User
from app.schemas.payment import (
    DepositQRRequest,
    DepositQRResponse,
    PaginatedPaymentRequests,
    PaymentApproveRequest,
    PaymentCancelRequest,
    PaymentHoldRequest,
    PaymentRejectRequest,
    PaymentRequestRead,
    PaymentSettingsRead,
    PaymentSettingsUpdateRequest,
)
from app.services.payment_service import PaymentService
from app.storage.storage_service import storage_service

router = APIRouter(tags=["Payments"])

_ALLOWED_SCREENSHOT_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_SCREENSHOT_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


def _paginate(items, total, page, page_size, model) -> PaginatedPaymentRequests:
    total_pages = math.ceil(total / page_size) if total else 0
    return PaginatedPaymentRequests(
        items=[model.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ----------------------------------------------------------------------
# Public/user payment settings read (only what a depositing user needs)
# ----------------------------------------------------------------------
@router.get("/payments/settings", response_model=PaymentSettingsRead)
async def get_payment_settings(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = PaymentService(session)
    settings_row = await service.get_settings()
    return PaymentSettingsRead.model_validate(settings_row)


# ----------------------------------------------------------------------
# User deposit flow
# ----------------------------------------------------------------------
@router.post("/payments/deposit/qr", response_model=DepositQRResponse)
async def generate_deposit_qr(
    payload: DepositQRRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = PaymentService(session)
    data = await service.get_deposit_qr(amount=payload.amount)
    return DepositQRResponse(**data)


@router.post("/payments/deposit", response_model=PaymentRequestRead, status_code=201)
async def submit_deposit(
    amount: str = Query(..., description="Deposit amount, e.g. 500.00"),
    utr_number: str = Query(..., min_length=1, max_length=64),
    screenshot: UploadFile = File(...),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    from decimal import Decimal, InvalidOperation

    try:
        parsed_amount = Decimal(amount)
    except InvalidOperation as exc:
        raise ValidationException("Invalid amount") from exc

    if screenshot.content_type not in _ALLOWED_SCREENSHOT_CONTENT_TYPES:
        raise ValidationException("Screenshot must be a JPEG, PNG or WEBP image")
    file_bytes = await screenshot.read()
    if len(file_bytes) > _MAX_SCREENSHOT_SIZE_BYTES:
        raise ValidationException("Screenshot must be smaller than 5 MB")

    extension = screenshot.content_type.split("/")[-1]
    path = f"payments/{current_user.id}/{uuid4().hex[:12]}.{extension}"
    screenshot_url = await storage_service.upload_file(path, file_bytes, screenshot.content_type)

    service = PaymentService(session)
    payment_request = await service.submit_deposit(
        user=current_user,
        amount=parsed_amount,
        utr_number=utr_number,
        screenshot_url=screenshot_url,
    )
    return PaymentRequestRead.model_validate(payment_request)


@router.get("/payments/deposits", response_model=PaginatedPaymentRequests)
async def list_my_deposits(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[PaymentRequestStatus] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = PaymentService(session)
    items, total = await service.list_my_requests(
        user=current_user,
        page=page,
        page_size=page_size,
        status=status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return _paginate(items, total, page, page_size, PaymentRequestRead)


@router.get("/payments/deposits/{payment_request_id}", response_model=PaymentRequestRead)
async def get_my_deposit(
    payment_request_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = PaymentService(session)
    payment_request = await service.get_request_for_user(
        user=current_user, payment_request_id=payment_request_id
    )
    return PaymentRequestRead.model_validate(payment_request)


@router.post("/payments/deposits/{payment_request_id}/cancel", response_model=PaymentRequestRead)
async def cancel_my_deposit(
    payment_request_id: UUID,
    payload: PaymentCancelRequest,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = PaymentService(session)
    payment_request = await service.cancel_own_request(
        user=current_user, payment_request_id=payment_request_id, reason=payload.reason
    )
    return PaymentRequestRead.model_validate(payment_request)


# ----------------------------------------------------------------------
# Admin payment settings
# ----------------------------------------------------------------------
@router.patch("/admin/payments/settings", response_model=PaymentSettingsRead)
async def admin_update_payment_settings(
    payload: PaymentSettingsUpdateRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PaymentService(session)
    settings_row = await service.update_settings(
        admin=admin, payload=payload.model_dump(exclude_unset=True)
    )
    return PaymentSettingsRead.model_validate(settings_row)


# ----------------------------------------------------------------------
# Admin verification
# ----------------------------------------------------------------------
@router.get("/admin/payments/deposits", response_model=PaginatedPaymentRequests)
async def admin_list_deposits(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[UUID] = Query(None),
    status: Optional[PaymentRequestStatus] = Query(None),
    provider: Optional[PaymentProvider] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc", pattern="^(?i)(asc|desc)$"),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PaymentService(session)
    items, total = await service.list_admin_requests(
        page=page,
        page_size=page_size,
        user_id=user_id,
        status=status,
        provider=provider,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return _paginate(items, total, page, page_size, PaymentRequestRead)


@router.get("/admin/payments/deposits/short/{short_id}", response_model=PaymentRequestRead)
async def admin_get_deposit_by_short_id(
    short_id: int,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin lookup by the human-friendly 8-digit short_id."""
    service = PaymentService(session)
    payment_request = await service.get_request_for_admin_by_short_id(short_id)
    return PaymentRequestRead.model_validate(payment_request)


@router.get("/admin/payments/deposits/txn/{txn_no}", response_model=PaymentRequestRead)
async def admin_get_deposit_by_txn_no(
    txn_no: str,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Admin lookup by the 10-digit transaction number shown to the user."""
    service = PaymentService(session)
    payment_request = await service.get_request_for_admin_by_txn_no(txn_no)
    return PaymentRequestRead.model_validate(payment_request)


@router.get("/admin/payments/deposits/{payment_request_id}", response_model=PaymentRequestRead)
async def admin_get_deposit(
    payment_request_id: UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PaymentService(session)
    payment_request = await service.get_request_for_admin(payment_request_id)
    return PaymentRequestRead.model_validate(payment_request)


@router.post(
    "/admin/payments/deposits/{payment_request_id}/approve", response_model=PaymentRequestRead
)
async def admin_approve_deposit(
    payment_request_id: UUID,
    payload: PaymentApproveRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PaymentService(session)
    payment_request = await service.approve(
        admin=admin, payment_request_id=payment_request_id, admin_note=payload.admin_note
    )
    return PaymentRequestRead.model_validate(payment_request)


@router.post(
    "/admin/payments/deposits/{payment_request_id}/reject", response_model=PaymentRequestRead
)
async def admin_reject_deposit(
    payment_request_id: UUID,
    payload: PaymentRejectRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PaymentService(session)
    payment_request = await service.reject(
        admin=admin,
        payment_request_id=payment_request_id,
        reason=payload.reason,
        note=payload.note,
    )
    return PaymentRequestRead.model_validate(payment_request)


@router.post("/admin/payments/deposits/{payment_request_id}/hold", response_model=PaymentRequestRead)
async def admin_hold_deposit(
    payment_request_id: UUID,
    payload: PaymentHoldRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = PaymentService(session)
    payment_request = await service.hold(
        admin=admin, payment_request_id=payment_request_id, admin_note=payload.admin_note
    )
    return PaymentRequestRead.model_validate(payment_request)
