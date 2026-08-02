"""
Payment Method service — manage a user's saved withdrawal destinations.
"""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.payment_method import PaymentMethod
from app.models.user import User
from app.schemas.payment_method import PaymentMethodCreate, PaymentMethodUpdate


class PaymentMethodService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(self, user: User) -> list[PaymentMethod]:
        stmt = (
            select(PaymentMethod)
            .where(PaymentMethod.user_id == user.id, PaymentMethod.deleted_at.is_(None))
            .order_by(PaymentMethod.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_owned(self, user: User, method_id: UUID) -> PaymentMethod:
        stmt = select(PaymentMethod).where(
            PaymentMethod.id == method_id, PaymentMethod.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        method = result.scalar_one_or_none()
        if method is None:
            raise NotFoundException("Payment method not found")
        if method.user_id != user.id:
            raise ForbiddenException("You do not have permission to access this payment method")
        return method

    async def create(self, user: User, payload: PaymentMethodCreate) -> PaymentMethod:
        method = PaymentMethod(
            user_id=user.id,
            method_type=payload.method_type,
            account_holder_name=payload.account_holder_name,
            upi_id=payload.upi_id,
            account_number=payload.account_number,
            ifsc_code=payload.ifsc_code,
        )
        self.session.add(method)
        await self.session.commit()
        await self.session.refresh(method)
        return method

    async def update(
        self, user: User, method_id: UUID, payload: PaymentMethodUpdate
    ) -> PaymentMethod:
        method = await self.get_owned(user, method_id)
        update_data = payload.model_dump(exclude_unset=True)

        # Only fields relevant to this method's existing type are ever
        # written — the type itself is immutable once created.
        if method.method_type.value == "bank_account":
            update_data.pop("upi_id", None)
        else:
            update_data.pop("account_number", None)
            update_data.pop("ifsc_code", None)

        for key, value in update_data.items():
            setattr(method, key, value)

        await self.session.commit()
        await self.session.refresh(method)
        return method

    async def delete(self, user: User, method_id: UUID) -> None:
        method = await self.get_owned(user, method_id)
        from datetime import datetime, timezone

        method.deleted_at = datetime.now(timezone.utc)
        await self.session.commit()