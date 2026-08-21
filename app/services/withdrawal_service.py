"""
Withdrawal service — orchestrates user withdrawal requests against a saved
PaymentMethod. The amount is DEBITED from the wallet immediately on
request (not just reserved), so the balance drops right away. If an admin
later cancels/rejects the request, the amount is refunded via a CREDIT.
If completed, nothing further happens to the wallet — the money is
already gone.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
    ValidationException,
)
from app.models.notification import NotificationEventType
from app.models.user import User
from app.models.withdrawal import WithdrawalRequest, WithdrawalStatus
from app.notifications.dispatch_service import NotificationDispatchService
from app.schemas.withdrawal import WithdrawalRequestCreate
from app.services.payment_method_service import PaymentMethodService
from app.services.payment_service import PaymentService
from app.services.wallet_service import WalletService
from app.utils.txn_id import generate_unique_txn_no

_REFERENCE_TYPE = "withdrawal_request"


class WithdrawalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.wallet_service = WalletService(session)
        self.payment_method_service = PaymentMethodService(session)
        self.payment_service = PaymentService(session)

    # ------------------------------------------------------------------
    # User-facing
    # ------------------------------------------------------------------
    async def request_withdrawal(
        self, user: User, payload: WithdrawalRequestCreate
    ) -> WithdrawalRequest:
        method = await self.payment_method_service.get_owned(user, payload.payment_method_id)
        if not method.is_active:
            raise BadRequestException("This payment method is not active")

        settings_row = await self.payment_service.get_settings()
        if payload.amount < settings_row.min_withdrawal_amount:
            raise ValidationException(
                f"Minimum withdrawal amount is {settings_row.min_withdrawal_amount}"
            )
        if payload.amount > settings_row.max_withdrawal_amount:
            raise ValidationException(
                f"Maximum withdrawal amount is {settings_row.max_withdrawal_amount}"
            )

        txn_no = await generate_unique_txn_no(self.session, WithdrawalRequest)

        withdrawal = WithdrawalRequest(
            user_id=user.id,
            amount=payload.amount,
            payment_method_id=method.id,
            method_type=method.method_type,
            method_details=method.as_snapshot(),
            status=WithdrawalStatus.PENDING,
            txn_no=txn_no,
        )
        self.session.add(withdrawal)
        await self.session.flush()

        # Deduct the amount from the wallet immediately on request — the
        # user's balance drops right away instead of just being reserved.
        # If the request is later cancelled/rejected, this is refunded via
        # a CREDIT (see _settle). If completed, nothing further happens to
        # the wallet — the money is already gone.
        debit_txn = await self.wallet_service.debit(
            user,
            amount=payload.amount,
            reference_type=_REFERENCE_TYPE,
            reference_id=str(withdrawal.id),
            description=f"Withdrawal request {withdrawal.id}",
            commit=False,
        )
        withdrawal.hold_transaction_id = debit_txn.id
        await self.session.commit()
        await self.session.refresh(withdrawal)

        try:
            await NotificationDispatchService(self.session).dispatch(
                user=user,
                event_type=NotificationEventType.WALLET_DEBITED,
                title="Withdrawal requested",
                body=f"Your withdrawal request of ₹{withdrawal.amount} has been submitted and is pending review.",
                event_key=f"withdrawal_requested:{withdrawal.id}",
                send_email=True,
            )
        except Exception:  # noqa: BLE001 - never block the request itself
            pass

        return withdrawal

    async def get_owned(self, user: User, withdrawal_id: UUID) -> WithdrawalRequest:
        withdrawal = await self._get(withdrawal_id)
        if withdrawal.user_id != user.id:
            raise NotFoundException("Withdrawal request not found")
        return withdrawal

    async def list_my_requests(
        self, user: User, *, page: int, page_size: int, status: Optional[WithdrawalStatus]
    ) -> tuple[list[WithdrawalRequest], int]:
        stmt = select(WithdrawalRequest).where(WithdrawalRequest.user_id == user.id)
        count_stmt = select(func.count(WithdrawalRequest.id)).where(WithdrawalRequest.user_id == user.id)
        if status is not None:
            stmt = stmt.where(WithdrawalRequest.status == status)
            count_stmt = count_stmt.where(WithdrawalRequest.status == status)
        stmt = stmt.order_by(WithdrawalRequest.created_at.desc()).offset((page - 1) * page_size).limit(
            page_size
        )
        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total

    async def cancel_own_request(self, user: User, withdrawal_id: UUID) -> WithdrawalRequest:
        """User-initiated cancel, only while still pending — refunds the debited amount."""
        withdrawal = await self.get_owned(user, withdrawal_id)
        return await self._settle(withdrawal, capture=False, actor=user, admin_note=None)

    # ------------------------------------------------------------------
    # Admin-facing
    # ------------------------------------------------------------------
    async def list_admin_requests(
        self, *, page: int, page_size: int, status: Optional[WithdrawalStatus]
    ) -> tuple[list[WithdrawalRequest], int]:
        stmt = select(WithdrawalRequest)
        count_stmt = select(func.count(WithdrawalRequest.id))
        if status is not None:
            stmt = stmt.where(WithdrawalRequest.status == status)
            count_stmt = count_stmt.where(WithdrawalRequest.status == status)
        # Newest first: admins reviewing withdrawals need to see the latest
        # requests on page 1, not buried behind however many old ones exist.
        stmt = stmt.order_by(WithdrawalRequest.created_at.desc()).offset((page - 1) * page_size).limit(
            page_size
        )
        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (await self.session.execute(stmt)).scalars().all()
        return list(rows), total

    async def get_for_admin(self, withdrawal_id: UUID) -> WithdrawalRequest:
        return await self._get(withdrawal_id)

    async def get_for_admin_by_short_id(self, short_id: int) -> WithdrawalRequest:
        stmt = select(WithdrawalRequest).where(WithdrawalRequest.short_id == short_id)
        result = await self.session.execute(stmt)
        withdrawal = result.scalar_one_or_none()
        if withdrawal is None:
            raise NotFoundException("Withdrawal request not found")
        return withdrawal

    async def get_for_admin_by_txn_no(self, txn_no: str) -> WithdrawalRequest:
        stmt = select(WithdrawalRequest).where(WithdrawalRequest.txn_no == txn_no)
        result = await self.session.execute(stmt)
        withdrawal = result.scalar_one_or_none()
        if withdrawal is None:
            raise NotFoundException("Withdrawal request not found for this transaction number")
        return withdrawal

    async def complete(
        self, admin: User, withdrawal_id: UUID, admin_note: Optional[str]
    ) -> WithdrawalRequest:
        """Admin has manually paid the user via the snapshotted method —
        the amount was already debited from the wallet at request time,
        so this just marks the request as paid out."""
        withdrawal = await self._get(withdrawal_id)
        return await self._settle(withdrawal, capture=True, actor=admin, admin_note=admin_note)

    async def cancel(
        self, admin: User, withdrawal_id: UUID, admin_note: Optional[str]
    ) -> WithdrawalRequest:
        """Admin cancels/rejects — refunds the previously debited amount
        back to the user's available balance."""
        withdrawal = await self._get(withdrawal_id)
        return await self._settle(withdrawal, capture=False, actor=admin, admin_note=admin_note)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    async def _get(self, withdrawal_id: UUID) -> WithdrawalRequest:
        stmt = select(WithdrawalRequest).where(WithdrawalRequest.id == withdrawal_id)
        result = await self.session.execute(stmt)
        withdrawal = result.scalar_one_or_none()
        if withdrawal is None:
            raise NotFoundException("Withdrawal request not found")
        return withdrawal

    async def _settle(
        self,
        withdrawal: WithdrawalRequest,
        *,
        capture: bool,
        actor: User,
        admin_note: Optional[str],
    ) -> WithdrawalRequest:
        if withdrawal.status != WithdrawalStatus.PENDING:
            raise ConflictException("This withdrawal request has already been processed")
        if withdrawal.hold_transaction_id is None:
            raise ConflictException("This withdrawal request has no reserved funds to settle")

        owner = await self.session.get(User, withdrawal.user_id)

        if capture:
            # Amount was already deducted from the wallet at request time —
            # completing just marks the request as paid out, no further
            # wallet movement is needed.
            settlement_txn = None
        else:
            # Refund the previously debited amount back to the user.
            settlement_txn = await self.wallet_service.credit(
                owner,
                amount=withdrawal.amount,
                reference_type=_REFERENCE_TYPE,
                reference_id=str(withdrawal.id),
                description=f"Withdrawal {withdrawal.id} cancelled/refunded",
                commit=False,
            )

        withdrawal.settlement_transaction_id = settlement_txn.id if settlement_txn else None
        withdrawal.status = WithdrawalStatus.COMPLETED if capture else WithdrawalStatus.CANCELLED
        withdrawal.processed_by_id = actor.id
        withdrawal.processed_at = datetime.now(timezone.utc)
        if admin_note:
            withdrawal.admin_note = admin_note

        await self.session.commit()
        await self.session.refresh(withdrawal)

        try:
            if capture:
                title = "Withdrawal paid"
                body = f"₹{withdrawal.amount} has been sent to your {withdrawal.method_type.value.upper()} account."
                event_type = NotificationEventType.WALLET_DEBITED
            else:
                title = "Withdrawal cancelled"
                body = f"Your withdrawal of ₹{withdrawal.amount} was cancelled and refunded to your wallet."
                event_type = NotificationEventType.REFUND_COMPLETED

            await NotificationDispatchService(self.session).dispatch(
                user=owner,
                event_type=event_type,
                title=title,
                body=body,
                event_key=f"withdrawal_settled:{withdrawal.id}",
                send_email=True,
            )
        except Exception:  # noqa: BLE001 - never block the settlement itself
            pass

        return withdrawal