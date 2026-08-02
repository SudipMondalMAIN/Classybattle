"""
Payment Method API routes — user's saved UPI/Bank withdrawal destinations.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.payment_method import PaymentMethodCreate, PaymentMethodRead, PaymentMethodUpdate
from app.services.payment_method_service import PaymentMethodService

router = APIRouter(prefix="/payment-methods", tags=["Payment Methods"])


@router.get("", response_model=list[PaymentMethodRead])
async def list_my_payment_methods(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = PaymentMethodService(session)
    methods = await service.list_for_user(current_user)
    return [PaymentMethodRead.model_validate(m) for m in methods]


@router.post("", response_model=PaymentMethodRead, status_code=status.HTTP_201_CREATED)
async def create_payment_method(
    payload: PaymentMethodCreate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = PaymentMethodService(session)
    method = await service.create(current_user, payload)
    return PaymentMethodRead.model_validate(method)


@router.patch("/{method_id}", response_model=PaymentMethodRead)
async def update_payment_method(
    method_id: UUID,
    payload: PaymentMethodUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = PaymentMethodService(session)
    method = await service.update(current_user, method_id, payload)
    return PaymentMethodRead.model_validate(method)


@router.delete("/{method_id}", response_model=MessageResponse)
async def delete_payment_method(
    method_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = PaymentMethodService(session)
    await service.delete(current_user, method_id)
    return MessageResponse(message="Payment method removed")