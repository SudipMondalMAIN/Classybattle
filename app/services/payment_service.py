"""
PaymentService — Manual Payment Verification System (Phase 17).

Deposit flow
------------
1. `get_deposit_qr` — user enters an amount; a dynamic UPI QR payload
   (a standard `upi://pay?...` deep link) is generated from the current
   PaymentSettings + the requested amount. Nothing is persisted yet.
2. `submit_deposit` — user uploads the payment screenshot and UTR number
   for that amount; a PaymentRequest row is created with status=PENDING.
3. An admin calls `approve` / `reject` / `hold` to verify it.

Security
--------
- Duplicate UTR protection: `utr_number` has a DB-level unique
  constraint (see PaymentRequest), and the service pre-checks it too so
  a friendly ConflictException is raised instead of a raw IntegrityError.
- Idempotent, exactly-once verification: `approve`/`reject`/`hold` all
  row-lock the PaymentRequest (`get_by_id_for_update`) and assert the
  current status before transitioning, so a retried/concurrent admin
  action can never verify the same request twice.
- Atomicity: wallet credit + PaymentRequest status update happen in one
  DB transaction (WalletService.credit is called with commit=False and
  the caller commits once after also updating the PaymentRequest row).
- Reusing WalletService's own duplicate-transaction guard: the wallet
  credit is created with reference_type="payment_deposit",
  reference_id=<payment_request.id>, so even if `approve` were somehow
  invoked twice concurrently past the row lock, the wallet ledger's
  unique constraint on (reference_type, reference_id, type) makes the
  second credit impossible.
- Every admin action is written to the existing AuditLog via
  AuditService, matching the Phase 7.5 pattern used elsewhere.

Future payment gateway support
-------------------------------
`PaymentRequest.provider` defaults to MANUAL_UPI but already supports
RAZORPAY / CASHFREE / PHONEPE. A future gateway integration would add a
`PaymentGatewayService` (webhook handler) that creates/updates
PaymentRequest rows the same way this service does for manual deposits,
and call the same `_approve_and_credit` primitive — no changes needed
here or to the schema.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional, Sequence
from urllib.parse import quote
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.models.audit_log import AuditAction, AuditActorType
from app.models.notification import NotificationEventType
from app.models.payment import (
    PaymentProvider,
    PaymentRejectionReason,
    PaymentRequest,
    PaymentRequestStatus,
    PaymentSettings,
)
from app.models.user import User, UserRole
from app.notifications.dispatch_service import NotificationDispatchService
from app.repositories.payment_repository import (
    PaymentRequestRepository,
    PaymentSettingsRepository,
)
from app.services.audit_service import AuditService
from app.services.wallet_service import WalletService

_ADMIN_ROLES = (UserRole.ADMIN, UserRole.SUPER_ADMIN)
_TERMINAL_STATUSES = (
    PaymentRequestStatus.APPROVED,
    PaymentRequestStatus.REJECTED,
    PaymentRequestStatus.CANCELLED,
)


def _build_upi_uri(*, upi_id: str, merchant_name: str, amount: Decimal, note: Optional[str]) -> str:
    """Standard UPI deep-link payload. Any UPI app / QR renderer on the
    frontend can turn this string directly into a scannable QR code."""
    params = {
        "pa": upi_id,
        "pn": merchant_name,
        "am": f"{amount:.2f}",
        "cu": "INR",
    }
    if note:
        params["tn"] = note
    query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    return f"upi://pay?{query}"


class PaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings_repo = PaymentSettingsRepository(session)
        self.request_repo = PaymentRequestRepository(session)
        self.audit_service = AuditService(session)
        self.wallet_service = WalletService(session)

    # ------------------------------------------------------------------
    # Payment settings
    # ------------------------------------------------------------------
    async def get_settings(self) -> PaymentSettings:
        settings_row = await self.settings_repo.get_singleton()
        if settings_row is None:
            settings_row = await self.settings_repo.create()
            await self.session.commit()
        return settings_row

    async def update_settings(
        self, *, admin: User, payload: dict
    ) -> PaymentSettings:
        if admin.role not in _ADMIN_ROLES:
            raise ForbiddenException("Only admins can change payment settings")

        settings_row = await self.get_settings()
        old_values = {
            "upi_id": settings_row.upi_id,
            "merchant_name": settings_row.merchant_name,
            "payment_note": settings_row.payment_note,
            "is_upi_enabled": settings_row.is_upi_enabled,
            "min_deposit_amount": settings_row.min_deposit_amount,
            "max_deposit_amount": settings_row.max_deposit_amount,
        }

        update_fields = {k: v for k, v in payload.items() if v is not None}
        if not update_fields:
            raise ValidationException("No fields provided to update")

        min_amt = update_fields.get("min_deposit_amount", settings_row.min_deposit_amount)
        max_amt = update_fields.get("max_deposit_amount", settings_row.max_deposit_amount)
        if min_amt is not None and max_amt is not None and min_amt > max_amt:
            raise ValidationException("min_deposit_amount cannot exceed max_deposit_amount")

        settings_row = await self.settings_repo.update(
            settings_row, **update_fields, updated_by_id=admin.id
        )

        await self.audit_service.record(
            entity="payment_settings",
            action=AuditAction.UPDATE,
            entity_id=settings_row.id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            old_values=old_values,
            new_values=update_fields,
            description="Payment settings updated",
        )

        await self.session.commit()
        await self.session.refresh(settings_row)
        return settings_row

    # ------------------------------------------------------------------
    # User deposit flow
    # ------------------------------------------------------------------
    async def get_deposit_qr(self, *, amount: Decimal) -> dict:
        settings_row = await self.get_settings()
        if not settings_row.is_upi_enabled or not settings_row.upi_id:
            raise BadRequestException("UPI deposits are currently disabled")
        if amount < settings_row.min_deposit_amount:
            raise ValidationException(
                f"Minimum deposit amount is {settings_row.min_deposit_amount}"
            )
        if amount > settings_row.max_deposit_amount:
            raise ValidationException(
                f"Maximum deposit amount is {settings_row.max_deposit_amount}"
            )

        qr_payload = _build_upi_uri(
            upi_id=settings_row.upi_id,
            merchant_name=settings_row.merchant_name,
            amount=amount,
            note=settings_row.payment_note,
        )
        return {
            "upi_id": settings_row.upi_id,
            "merchant_name": settings_row.merchant_name,
            "amount": amount,
            "currency": "INR",
            "note": settings_row.payment_note,
            "qr_payload": qr_payload,
        }

    async def submit_deposit(
        self,
        *,
        user: User,
        amount: Decimal,
        utr_number: str,
        screenshot_url: str,
    ) -> PaymentRequest:
        settings_row = await self.get_settings()
        if not settings_row.is_upi_enabled or not settings_row.upi_id:
            raise BadRequestException("UPI deposits are currently disabled")
        if amount < settings_row.min_deposit_amount:
            raise ValidationException(
                f"Minimum deposit amount is {settings_row.min_deposit_amount}"
            )
        if amount > settings_row.max_deposit_amount:
            raise ValidationException(
                f"Maximum deposit amount is {settings_row.max_deposit_amount}"
            )

        utr_number = utr_number.strip()
        if not utr_number:
            raise ValidationException("UTR number is required")

        existing = await self.request_repo.get_by_utr(utr_number)
        if existing is not None:
            raise ConflictException("This UTR number has already been submitted")

        qr_payload = _build_upi_uri(
            upi_id=settings_row.upi_id,
            merchant_name=settings_row.merchant_name,
            amount=amount,
            note=settings_row.payment_note,
        )

        try:
            payment_request = await self.request_repo.create(
                user_id=user.id,
                provider=PaymentProvider.MANUAL_UPI,
                amount=amount,
                currency="INR",
                upi_id_used=settings_row.upi_id,
                qr_payload=qr_payload,
                screenshot_url=screenshot_url,
                utr_number=utr_number,
                status=PaymentRequestStatus.PENDING,
            )
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictException("This UTR number has already been submitted") from exc

        await self.audit_service.record(
            entity="payment_request",
            action=AuditAction.CREATE,
            entity_id=payment_request.id,
            actor=user,
            actor_type=AuditActorType.USER,
            new_values={"amount": str(amount), "utr_number": utr_number},
            description=f"Deposit request submitted for {amount}",
        )

        await self.session.commit()
        await self.session.refresh(payment_request)
        return payment_request

    async def cancel_own_request(
        self, *, user: User, payment_request_id: UUID, reason: Optional[str] = None
    ) -> PaymentRequest:
        payment_request = await self.request_repo.get_by_id_for_update(payment_request_id)
        if payment_request is None:
            raise NotFoundException("Payment request not found")
        if payment_request.user_id != user.id:
            raise ForbiddenException("You do not have permission to cancel this request")
        if payment_request.status != PaymentRequestStatus.PENDING:
            raise ConflictException("Only pending requests can be cancelled")

        payment_request = await self.request_repo.update(
            payment_request,
            status=PaymentRequestStatus.CANCELLED,
            admin_note=reason,
        )
        await self.session.commit()
        return payment_request

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------
    async def get_request_for_user(self, *, user: User, payment_request_id: UUID) -> PaymentRequest:
        payment_request = await self.request_repo.get_by_id(payment_request_id)
        if payment_request is None:
            raise NotFoundException("Payment request not found")
        if payment_request.user_id != user.id and user.role not in _ADMIN_ROLES:
            raise ForbiddenException("You do not have permission to view this request")
        return payment_request

    async def get_request_for_admin(self, payment_request_id: UUID) -> PaymentRequest:
        payment_request = await self.request_repo.get_by_id(payment_request_id)
        if payment_request is None:
            raise NotFoundException("Payment request not found")
        return payment_request

    async def list_my_requests(
        self,
        *,
        user: User,
        page: int = 1,
        page_size: int = 20,
        status: Optional[PaymentRequestStatus] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[PaymentRequest], int]:
        return await self.request_repo.list_for_user(
            user.id,
            page=page,
            page_size=page_size,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def list_admin_requests(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        user_id: Optional[UUID] = None,
        status: Optional[PaymentRequestStatus] = None,
        provider: Optional[PaymentProvider] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[PaymentRequest], int]:
        return await self.request_repo.list_admin(
            page=page,
            page_size=page_size,
            user_id=user_id,
            status=status,
            provider=provider,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    # ------------------------------------------------------------------
    # Admin verification
    # ------------------------------------------------------------------
    async def approve(
        self, *, admin: User, payment_request_id: UUID, admin_note: Optional[str] = None
    ) -> PaymentRequest:
        if admin.role not in _ADMIN_ROLES:
            raise ForbiddenException("Only admins can approve payment requests")

        payment_request = await self.request_repo.get_by_id_for_update(payment_request_id)
        if payment_request is None:
            raise NotFoundException("Payment request not found")
        if payment_request.status in _TERMINAL_STATUSES:
            raise ConflictException(
                f"This request has already been {payment_request.status.value}"
            )

        target_user = payment_request.user

        # Wallet credit + PaymentRequest status transition happen in one
        # transaction: commit=False keeps the wallet mutation open, we
        # append the status update, and commit exactly once below.
        txn = await self.wallet_service.credit(
            target_user,
            amount=payment_request.amount,
            reference_type="payment_deposit",
            reference_id=str(payment_request.id),
            description=f"UPI deposit approved (UTR {payment_request.utr_number})",
            metadata={"payment_request_id": str(payment_request.id)},
            commit=False,
        )

        payment_request = await self.request_repo.update(
            payment_request,
            status=PaymentRequestStatus.APPROVED,
            verified_by_id=admin.id,
            verified_at=txn.created_at,
            admin_note=admin_note,
            wallet_transaction_id=txn.id,
        )

        await self.audit_service.record(
            entity="payment_request",
            action=AuditAction.STATUS_CHANGE,
            entity_id=payment_request.id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            old_values={"status": "pending"},
            new_values={
                "status": "approved",
                "amount": str(payment_request.amount),
                "wallet_transaction_id": str(txn.id),
            },
            description=f"Payment request approved and wallet credited for user {target_user.id}",
        )

        await self.session.commit()
        await self.session.refresh(payment_request)

        try:
            await NotificationDispatchService(self.session).dispatch(
                user=target_user,
                event_type=NotificationEventType.WALLET_CREDITED,
                title="Deposit approved",
                body=f"Your deposit of ₹{payment_request.amount} has been approved and credited.",
                event_key=f"payment_approved:{payment_request.id}",
            )
        except Exception:  # noqa: BLE001
            pass

        return payment_request

    async def reject(
        self,
        *,
        admin: User,
        payment_request_id: UUID,
        reason: PaymentRejectionReason,
        note: Optional[str] = None,
    ) -> PaymentRequest:
        if admin.role not in _ADMIN_ROLES:
            raise ForbiddenException("Only admins can reject payment requests")

        payment_request = await self.request_repo.get_by_id_for_update(payment_request_id)
        if payment_request is None:
            raise NotFoundException("Payment request not found")
        if payment_request.status in _TERMINAL_STATUSES:
            raise ConflictException(
                f"This request has already been {payment_request.status.value}"
            )

        target_user = payment_request.user

        payment_request = await self.request_repo.update(
            payment_request,
            status=PaymentRequestStatus.REJECTED,
            verified_by_id=admin.id,
            rejection_reason=reason,
            rejection_note=note,
        )
        from datetime import datetime, timezone

        payment_request = await self.request_repo.update(
            payment_request, verified_at=datetime.now(timezone.utc)
        )

        await self.audit_service.record(
            entity="payment_request",
            action=AuditAction.STATUS_CHANGE,
            entity_id=payment_request.id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            old_values={"status": "pending"},
            new_values={"status": "rejected", "reason": reason.value, "note": note},
            description=f"Payment request rejected for user {target_user.id}",
        )

        await self.session.commit()
        await self.session.refresh(payment_request)

        try:
            await NotificationDispatchService(self.session).dispatch(
                user=target_user,
                event_type=NotificationEventType.GENERAL,
                title="Deposit rejected",
                body=(
                    f"Your deposit of ₹{payment_request.amount} was rejected "
                    f"({reason.value.replace('_', ' ')})."
                ),
                event_key=f"payment_rejected:{payment_request.id}",
            )
        except Exception:  # noqa: BLE001
            pass

        return payment_request

    async def hold(
        self, *, admin: User, payment_request_id: UUID, admin_note: Optional[str] = None
    ) -> PaymentRequest:
        if admin.role not in _ADMIN_ROLES:
            raise ForbiddenException("Only admins can hold payment requests")

        payment_request = await self.request_repo.get_by_id_for_update(payment_request_id)
        if payment_request is None:
            raise NotFoundException("Payment request not found")
        if payment_request.status in _TERMINAL_STATUSES:
            raise ConflictException(
                f"This request has already been {payment_request.status.value}"
            )
        if payment_request.status == PaymentRequestStatus.ON_HOLD:
            raise ConflictException("This request is already on hold")

        payment_request = await self.request_repo.update(
            payment_request,
            status=PaymentRequestStatus.ON_HOLD,
            admin_note=admin_note,
        )

        await self.audit_service.record(
            entity="payment_request",
            action=AuditAction.STATUS_CHANGE,
            entity_id=payment_request.id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            old_values={"status": "pending"},
            new_values={"status": "on_hold", "note": admin_note},
            description=f"Payment request placed on hold for user {payment_request.user_id}",
        )

        await self.session.commit()
        await self.session.refresh(payment_request)
        return payment_request
