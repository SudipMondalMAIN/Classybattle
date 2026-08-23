"""
Wallet service — Enterprise Wallet System (Phase 8).

Orchestrates wallet lifecycle (auto-create, lookup) and every balance
mutation (credit, debit, hold, release-hold, refund, bonus, admin
adjustment) as a single atomic DB transaction: the Wallet row is
row-locked, the new balances are computed and validated (never negative),
an immutable WalletTransaction ledger row is written with a snapshot of
the resulting balances, and — for admin-initiated mutations — an
AuditLog entry is recorded via the existing AuditService.

Duplicate-transaction protection
---------------------------------
Every mutation that originates from a domain event (tournament entry,
match payout, etc.) should pass ``reference_type`` + ``reference_id``.
The DB enforces a uniqueness constraint on
(reference_type, reference_id, type), so retried domain events cannot
double-credit/debit a wallet even without an Idempotency-Key. Callers
that also want request-level replay protection (e.g. a user retrying a
top-up API call) should additionally wrap the call site with
``IdempotencyService`` at the route layer, per the Phase 7.5 pattern.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional, Sequence
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
from app.models.user import User, UserRole
from app.models.wallet import Wallet
from app.models.wallet_transaction import (
    WalletBalanceSource,
    WalletTransaction,
    WalletTransactionStatus,
    WalletTransactionType,
)
from app.repositories.wallet_repository import WalletRepository
from app.repositories.wallet_transaction_repository import WalletTransactionRepository
from app.services.audit_service import AuditService

_ADMIN_ROLES = (UserRole.ADMIN, UserRole.SUPER_ADMIN)


class WalletService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.wallet_repo = WalletRepository(session)
        self.txn_repo = WalletTransactionRepository(session)
        self.audit_service = AuditService(session)

    # ------------------------------------------------------------------
    # Wallet lookup / auto-create
    # ------------------------------------------------------------------
    async def get_or_create_wallet(self, user: User) -> Wallet:
        wallet = await self.wallet_repo.get_by_user_id(user.id)
        if wallet is not None:
            return wallet
        try:
            wallet = await self.wallet_repo.create(user_id=user.id)
            await self.session.commit()
        except IntegrityError:
            # Concurrent request already created it (unique user_id).
            await self.session.rollback()
            wallet = await self.wallet_repo.get_by_user_id(user.id)
            if wallet is None:  # pragma: no cover - defensive
                raise
        return wallet

    async def get_wallet_for_admin(self, user_id: UUID) -> Wallet:
        wallet = await self.wallet_repo.get_by_user_id(user_id)
        if wallet is None:
            raise NotFoundException("Wallet not found for this user")
        return wallet

    # ------------------------------------------------------------------
    # Transaction history
    # ------------------------------------------------------------------
    async def list_transactions(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
        type_: Optional[WalletTransactionType] = None,
        status: Optional[WalletTransactionStatus] = None,
        date_from=None,
        date_to=None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[WalletTransaction], int]:
        wallet = await self.get_or_create_wallet(user)
        return await self.txn_repo.list_for_wallet(
            wallet.id,
            page=page,
            page_size=page_size,
            type_=type_,
            status=status,
            date_from=date_from,
            date_to=date_to,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def get_transaction_details(self, user: User, transaction_id: UUID) -> WalletTransaction:
        txn = await self.txn_repo.get_by_id(transaction_id)
        if txn is None:
            raise NotFoundException("Transaction not found")
        if txn.user_id != user.id and user.role not in _ADMIN_ROLES:
            raise ForbiddenException("You do not have permission to view this transaction")
        return txn

    async def list_transactions_admin(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        user_id: Optional[UUID] = None,
        type_: Optional[WalletTransactionType] = None,
        status: Optional[WalletTransactionStatus] = None,
        date_from=None,
        date_to=None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[WalletTransaction], int]:
        return await self.txn_repo.list_all_admin(
            page=page,
            page_size=page_size,
            user_id=user_id,
            type_=type_,
            status=status,
            date_from=date_from,
            date_to=date_to,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    # ------------------------------------------------------------------
    # Core atomic mutation primitive
    # ------------------------------------------------------------------
    async def _mutate(
        self,
        *,
        user_id: UUID,
        type_: WalletTransactionType,
        amount: Decimal,
        deposit_delta: Decimal = Decimal("0"),
        winnings_delta: Decimal = Decimal("0"),
        locked_delta: Decimal = Decimal("0"),
        balance_source: WalletBalanceSource = WalletBalanceSource.WINNINGS,
        status: WalletTransactionStatus = WalletTransactionStatus.SUCCESS,
        description: Optional[str] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        related_transaction_id: Optional[UUID] = None,
        performed_by: Optional[User] = None,
        metadata: Optional[dict] = None,
    ) -> WalletTransaction:
        if amount <= 0:
            raise ValidationException("Transaction amount must be greater than zero")

        # Duplicate-transaction protection: same domain event + type must
        # never be applied twice.
        if reference_type and reference_id:
            existing = await self.txn_repo.get_by_reference(reference_type, reference_id, type_)
            if existing is not None:
                raise ConflictException(
                    f"A '{type_.value}' transaction already exists for "
                    f"{reference_type}:{reference_id}"
                )

        wallet = await self.wallet_repo.get_by_user_id_for_update(user_id)
        if wallet is None:
            raise NotFoundException("Wallet not found for this user")
        if wallet.is_frozen:
            raise ForbiddenException("This wallet is frozen and cannot process transactions")

        new_deposit = wallet.deposit_balance + deposit_delta
        new_winnings = wallet.winnings_balance + winnings_delta
        new_locked = wallet.locked_balance + locked_delta

        if new_deposit < 0:
            raise BadRequestException("Insufficient deposit balance")
        if new_winnings < 0:
            raise BadRequestException("Insufficient winnings balance")
        if new_locked < 0:
            raise BadRequestException("Insufficient locked balance")

        wallet.deposit_balance = new_deposit
        wallet.winnings_balance = new_winnings
        wallet.locked_balance = new_locked

        try:
            txn = await self.txn_repo.create(
                wallet_id=wallet.id,
                user_id=user_id,
                type=type_,
                status=status,
                amount=amount,
                currency=wallet.currency,
                balance_source=balance_source,
                deposit_delta=deposit_delta,
                winnings_delta=winnings_delta,
                deposit_balance_after=new_deposit,
                winnings_balance_after=new_winnings,
                available_balance_after=new_deposit + new_winnings,
                locked_balance_after=new_locked,
                description=description,
                reference_type=reference_type,
                reference_id=reference_id,
                related_transaction_id=related_transaction_id,
                performed_by_id=performed_by.id if performed_by is not None else None,
                metadata_json=metadata,
            )
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictException(
                "A transaction with this reference has already been processed"
            ) from exc

        await self.session.flush()
        return txn

    # ------------------------------------------------------------------
    # User-facing operations
    # ------------------------------------------------------------------
    async def credit(
        self,
        user: User,
        *,
        amount: Decimal,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
        source: WalletBalanceSource = WalletBalanceSource.WINNINGS,
        commit: bool = True,
    ) -> WalletTransaction:
        """source=DEPOSIT for UPI top-ups (payment_service), WINNINGS
        (default) for prize payouts / refunds / bonuses — winnings are
        the only credited funds that stay withdrawable."""
        await self.get_or_create_wallet(user)
        deposit_delta = amount if source == WalletBalanceSource.DEPOSIT else Decimal("0")
        winnings_delta = amount if source == WalletBalanceSource.WINNINGS else Decimal("0")
        txn = await self._mutate(
            user_id=user.id,
            type_=WalletTransactionType.CREDIT,
            amount=amount,
            deposit_delta=deposit_delta,
            winnings_delta=winnings_delta,
            balance_source=source,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            metadata=metadata,
        )
        if commit:
            await self.session.commit()
            try:
                from app.models.notification import NotificationEventType
                from app.notifications.dispatch_service import NotificationDispatchService

                await NotificationDispatchService(self.session).dispatch(
                    user=user,
                    event_type=NotificationEventType.WALLET_CREDITED,
                    title="Wallet credited",
                    body=f"₹{amount} has been credited to your wallet."
                    + (f" ({description})" if description else ""),
                    event_key=f"wallet_credited:{txn.id}",
                    meta_data={"transaction_id": str(txn.id)},
                )
            except Exception:  # noqa: BLE001
                pass

            # Phase 15C: automatic WALLET_MILESTONE achievement evaluation,
            # keyed on the wallet's post-credit available balance.
            try:
                from app.models.achievement import AchievementTriggerType
                from app.services.achievement_service import AchievementService

                wallet = await self.wallet_repo.get_by_user_id(user.id)
                if wallet is not None:
                    await AchievementService(self.session).evaluate(
                        user_id=user.id,
                        trigger_type=AchievementTriggerType.WALLET_MILESTONE,
                        metric_value=wallet.available_balance,
                    )
            except Exception:  # noqa: BLE001
                pass
        return txn

    async def create_pending_deposit(
        self,
        user: User,
        *,
        amount: Decimal,
        reference_type: str,
        reference_id: str,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> WalletTransaction:
        """Write a PENDING ledger row for a deposit awaiting admin review,
        so it shows up in the user's transaction history right away.
        Deliberately does NOT touch the wallet balance — that only
        happens in settle_pending_deposit(), when an admin approves.
        """
        if amount <= 0:
            raise ValidationException("Transaction amount must be greater than zero")

        existing = await self.txn_repo.get_by_reference(
            reference_type, reference_id, WalletTransactionType.CREDIT
        )
        if existing is not None:
            raise ConflictException(
                f"A 'credit' transaction already exists for {reference_type}:{reference_id}"
            )

        wallet = await self.get_or_create_wallet(user)
        txn = await self.txn_repo.create(
            wallet_id=wallet.id,
            user_id=user.id,
            type=WalletTransactionType.CREDIT,
            status=WalletTransactionStatus.PENDING,
            amount=amount,
            currency=wallet.currency,
            balance_source=WalletBalanceSource.DEPOSIT,
            deposit_delta=Decimal("0"),
            winnings_delta=Decimal("0"),
            deposit_balance_after=wallet.deposit_balance,
            winnings_balance_after=wallet.winnings_balance,
            available_balance_after=wallet.available_balance,
            locked_balance_after=wallet.locked_balance,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            metadata_json=metadata,
        )
        await self.session.flush()
        return txn

    async def settle_pending_deposit(self, transaction_id: UUID) -> WalletTransaction:
        """Transition a PENDING deposit CREDIT to SUCCESS, applying the
        balance change now (called when an admin approves the deposit)."""
        txn = await self.txn_repo.get_by_id(transaction_id)
        if txn is None:
            raise NotFoundException("Transaction not found")
        if txn.status != WalletTransactionStatus.PENDING:
            raise ConflictException(f"Transaction is already {txn.status.value}")

        wallet = await self.wallet_repo.get_by_user_id_for_update(txn.user_id)
        if wallet is None:
            raise NotFoundException("Wallet not found for this user")
        if wallet.is_frozen:
            raise ForbiddenException("This wallet is frozen and cannot process transactions")

        new_deposit = wallet.deposit_balance + txn.amount
        wallet.deposit_balance = new_deposit

        txn.status = WalletTransactionStatus.SUCCESS
        txn.deposit_delta = txn.amount
        txn.deposit_balance_after = new_deposit
        txn.available_balance_after = new_deposit + wallet.winnings_balance
        txn.locked_balance_after = wallet.locked_balance
        await self.session.flush()
        return txn

    async def cancel_pending_deposit(
        self, transaction_id: UUID, *, failed: bool = True
    ) -> WalletTransaction:
        """Transition a PENDING deposit CREDIT to FAILED/CANCELLED (called
        when an admin rejects/holds it). No balance change — it was never
        applied while pending."""
        txn = await self.txn_repo.get_by_id(transaction_id)
        if txn is None:
            raise NotFoundException("Transaction not found")
        if txn.status != WalletTransactionStatus.PENDING:
            raise ConflictException(f"Transaction is already {txn.status.value}")
        txn.status = WalletTransactionStatus.FAILED if failed else WalletTransactionStatus.CANCELLED
        await self.session.flush()
        return txn

    async def debit(
        self,
        user: User,
        *,
        amount: Decimal,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
        commit: bool = True,
    ) -> WalletTransaction:
        """Plain debit — ALWAYS draws from winnings_balance only. Used for
        withdrawals (deposit money is never withdrawable). Tournament entry
        fees must use debit_entry_fee() instead, which can draw from both
        buckets."""
        await self.get_or_create_wallet(user)
        txn = await self._mutate(
            user_id=user.id,
            type_=WalletTransactionType.DEBIT,
            amount=amount,
            deposit_delta=Decimal("0"),
            winnings_delta=-amount,
            balance_source=WalletBalanceSource.WINNINGS,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            metadata=metadata,
        )
        if commit:
            await self.session.commit()
            try:
                from app.models.notification import NotificationEventType
                from app.notifications.dispatch_service import NotificationDispatchService

                await NotificationDispatchService(self.session).dispatch(
                    user=user,
                    event_type=NotificationEventType.WALLET_DEBITED,
                    title="Wallet debited",
                    body=f"₹{amount} has been debited from your wallet."
                    + (f" ({description})" if description else ""),
                    event_key=f"wallet_debited:{txn.id}",
                    meta_data={"transaction_id": str(txn.id)},
                )
            except Exception:  # noqa: BLE001
                pass
        return txn

    async def debit_entry_fee(
        self,
        user: User,
        *,
        amount: Decimal,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
        commit: bool = True,
    ) -> WalletTransaction:
        """Tournament join charge: draws from deposit_balance first, then
        winnings_balance for any remainder. Both bucket amounts are
        recorded on the ledger row (deposit_delta/winnings_delta) so a
        later cancellation can refund the exact same buckets via
        refund_entry_fee()."""
        await self.get_or_create_wallet(user)
        wallet = await self.wallet_repo.get_by_user_id(user.id)
        deposit_use = min(amount, wallet.deposit_balance) if wallet.deposit_balance > 0 else Decimal("0")
        winnings_use = amount - deposit_use

        source = (
            WalletBalanceSource.DEPOSIT
            if winnings_use == 0
            else WalletBalanceSource.WINNINGS
            if deposit_use == 0
            else WalletBalanceSource.MIXED
        )

        txn = await self._mutate(
            user_id=user.id,
            type_=WalletTransactionType.DEBIT,
            amount=amount,
            deposit_delta=-deposit_use,
            winnings_delta=-winnings_use,
            balance_source=source,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            metadata=metadata,
        )
        if commit:
            await self.session.commit()
        return txn

    async def refund_entry_fee(
        self,
        user: User,
        *,
        original_transaction_id: UUID,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
        commit: bool = True,
    ) -> WalletTransaction:
        """Refunds a previous debit_entry_fee() charge back to the exact
        same buckets it was drawn from (so deposit-money can never turn
        into withdrawable winnings just by joining then cancelling)."""
        original = await self.txn_repo.get_by_id(original_transaction_id)
        if original is None:
            raise NotFoundException("Original entry-fee transaction not found")

        deposit_back = -original.deposit_delta
        winnings_back = -original.winnings_delta
        amount = deposit_back + winnings_back
        if amount <= 0:
            raise BadRequestException("Original transaction has nothing to refund")

        source = (
            WalletBalanceSource.DEPOSIT
            if winnings_back == 0
            else WalletBalanceSource.WINNINGS
            if deposit_back == 0
            else WalletBalanceSource.MIXED
        )

        txn = await self._mutate(
            user_id=user.id,
            type_=WalletTransactionType.REFUND,
            amount=amount,
            deposit_delta=deposit_back,
            winnings_delta=winnings_back,
            balance_source=source,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            related_transaction_id=original.id,
            metadata=metadata,
        )
        if commit:
            await self.session.commit()
            try:
                from app.models.notification import NotificationEventType
                from app.notifications.dispatch_service import NotificationDispatchService

                await NotificationDispatchService(self.session).dispatch(
                    user=user,
                    event_type=NotificationEventType.REFUND_COMPLETED,
                    title="Refund completed",
                    body=f"₹{amount} has been refunded to your wallet."
                    + (f" ({description})" if description else ""),
                    event_key=f"refund_completed:{txn.id}",
                    meta_data={"transaction_id": str(txn.id)},
                )
            except Exception:  # noqa: BLE001
                pass
        return txn

    async def hold(
        self,
        user: User,
        *,
        amount: Decimal,
        reference_type: str,
        reference_id: str,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
        commit: bool = True,
    ) -> WalletTransaction:
        """Moves funds from winnings -> locked. Used to reserve funds
        before the outcome is known. Not used by the current tournament
        entry flow (which uses debit_entry_fee instead), kept for other
        hold-style callers (e.g. admin/legacy routes)."""
        await self.get_or_create_wallet(user)
        txn = await self._mutate(
            user_id=user.id,
            type_=WalletTransactionType.HOLD,
            amount=amount,
            deposit_delta=Decimal("0"),
            winnings_delta=-amount,
            locked_delta=amount,
            balance_source=WalletBalanceSource.WINNINGS,
            status=WalletTransactionStatus.PENDING,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            metadata=metadata,
        )
        if commit:
            await self.session.commit()
        return txn

    async def release_hold(
        self,
        user: User,
        *,
        hold_transaction_id: UUID,
        capture: bool = False,
        description: Optional[str] = None,
        commit: bool = True,
    ) -> WalletTransaction:
        """Settles a previously created HOLD.

        - capture=False (default): funds move locked -> available (the
          hold is released back to the user, e.g. entry cancelled).
        - capture=True: funds are removed from locked entirely (the hold
          is captured/spent, e.g. the tournament entry fee was consumed).
        """
        hold_txn = await self.txn_repo.get_by_id(hold_transaction_id)
        if hold_txn is None:
            raise NotFoundException("Hold transaction not found")
        if hold_txn.user_id != user.id:
            raise ForbiddenException("You do not have permission to release this hold")
        if hold_txn.type != WalletTransactionType.HOLD:
            raise BadRequestException("Referenced transaction is not a hold")
        if hold_txn.status != WalletTransactionStatus.PENDING:
            raise ConflictException("This hold has already been settled")

        wallet = await self.wallet_repo.get_by_user_id_for_update(user.id)
        if wallet is None:
            raise NotFoundException("Wallet not found for this user")

        # hold() always draws from winnings_balance, so release/capture
        # always settles against winnings_balance too.
        winnings_delta = Decimal("0") if capture else hold_txn.amount
        new_deposit = wallet.deposit_balance
        new_winnings = wallet.winnings_balance + winnings_delta
        new_locked = wallet.locked_balance - hold_txn.amount
        if new_locked < 0:
            raise BadRequestException("Insufficient locked balance to release")

        wallet.winnings_balance = new_winnings
        wallet.locked_balance = new_locked

        release_txn = await self.txn_repo.create(
            wallet_id=wallet.id,
            user_id=user.id,
            type=WalletTransactionType.RELEASE_HOLD,
            status=WalletTransactionStatus.SUCCESS,
            amount=hold_txn.amount,
            currency=wallet.currency,
            balance_source=WalletBalanceSource.WINNINGS,
            deposit_delta=Decimal("0"),
            winnings_delta=winnings_delta,
            deposit_balance_after=new_deposit,
            winnings_balance_after=new_winnings,
            available_balance_after=new_deposit + new_winnings,
            locked_balance_after=new_locked,
            description=description or ("Hold captured" if capture else "Hold released"),
            reference_type=hold_txn.reference_type,
            reference_id=hold_txn.reference_id,
            related_transaction_id=hold_txn.id,
        )
        await self.txn_repo.update_status(
            hold_txn,
            WalletTransactionStatus.SUCCESS if capture else WalletTransactionStatus.CANCELLED,
        )
        await self.session.flush()
        if commit:
            await self.session.commit()
        return release_txn

    async def refund(
        self,
        user: User,
        *,
        amount: Decimal,
        reference_type: str,
        reference_id: str,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
        commit: bool = True,
    ) -> WalletTransaction:
        # Generic refund (e.g. withdrawal cancelled) — always credited back
        # to winnings_balance, since debit() only ever draws from winnings.
        # Entry-fee refunds must use refund_entry_fee() instead.
        await self.get_or_create_wallet(user)
        txn = await self._mutate(
            user_id=user.id,
            type_=WalletTransactionType.REFUND,
            amount=amount,
            deposit_delta=Decimal("0"),
            winnings_delta=amount,
            balance_source=WalletBalanceSource.WINNINGS,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            metadata=metadata,
        )
        if commit:
            await self.session.commit()
            try:
                from app.models.notification import NotificationEventType
                from app.notifications.dispatch_service import NotificationDispatchService

                await NotificationDispatchService(self.session).dispatch(
                    user=user,
                    event_type=NotificationEventType.REFUND_COMPLETED,
                    title="Refund completed",
                    body=f"₹{amount} has been refunded to your wallet."
                    + (f" ({description})" if description else ""),
                    event_key=f"refund_completed:{txn.id}",
                    meta_data={"transaction_id": str(txn.id)},
                )
            except Exception:  # noqa: BLE001
                pass
        return txn

    async def bonus(
        self,
        user: User,
        *,
        amount: Decimal,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
        commit: bool = True,
    ) -> WalletTransaction:
        # Admin bonuses land in winnings_balance (withdrawable), matching
        # how promotional/bonus credit is generally expected to behave.
        await self.get_or_create_wallet(user)
        txn = await self._mutate(
            user_id=user.id,
            type_=WalletTransactionType.BONUS,
            amount=amount,
            deposit_delta=Decimal("0"),
            winnings_delta=amount,
            balance_source=WalletBalanceSource.WINNINGS,
            description=description,
            reference_type=reference_type,
            reference_id=reference_id,
            metadata=metadata,
        )
        if commit:
            await self.session.commit()
        return txn

    # ------------------------------------------------------------------
    # Admin operations
    # ------------------------------------------------------------------
    async def admin_adjust(
        self,
        *,
        target_user: User,
        amount: Decimal,
        reason: str,
        admin: User,
        source: WalletBalanceSource = WalletBalanceSource.WINNINGS,
    ) -> WalletTransaction:
        """amount > 0 credits the wallet, amount < 0 debits it. Always
        recorded as ADMIN_ADJUSTMENT and audited via AuditService.
        source picks which bucket is adjusted (default winnings)."""
        if admin.role not in _ADMIN_ROLES:
            raise ForbiddenException("Only admins can adjust wallet balances")
        if amount == 0:
            raise ValidationException("Adjustment amount must not be zero")

        await self.get_or_create_wallet(target_user)
        magnitude = abs(amount)
        deposit_delta = amount if source == WalletBalanceSource.DEPOSIT else Decimal("0")
        winnings_delta = amount if source == WalletBalanceSource.WINNINGS else Decimal("0")

        txn = await self._mutate(
            user_id=target_user.id,
            type_=WalletTransactionType.ADMIN_ADJUSTMENT,
            amount=magnitude,
            deposit_delta=deposit_delta,
            winnings_delta=winnings_delta,
            balance_source=source,
            description=reason,
            performed_by=admin,
            metadata={"direction": "credit" if amount > 0 else "debit"},
        )

        await self.audit_service.record(
            entity="wallet",
            action=AuditAction.UPDATE,
            entity_id=txn.wallet_id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            old_values={"transaction_type": "admin_adjustment"},
            new_values={
                "amount": str(amount),
                "target_user_id": str(target_user.id),
                "reason": reason,
                "transaction_id": str(txn.id),
            },
            description=f"Admin adjustment of {amount} on wallet for user {target_user.id}",
        )

        await self.session.commit()

        try:
            from app.models.notification import NotificationEventType
            from app.notifications.dispatch_service import NotificationDispatchService

            event_type = (
                NotificationEventType.WALLET_CREDITED
                if amount > 0
                else NotificationEventType.WALLET_DEBITED
            )
            await NotificationDispatchService(self.session).dispatch(
                user=target_user,
                event_type=event_type,
                title="Wallet credited" if amount > 0 else "Wallet debited",
                body=f"₹{magnitude} has been {'credited to' if amount > 0 else 'debited from'} your wallet."
                + (f" ({reason})" if reason else ""),
                event_key=f"wallet_admin_adjustment:{txn.id}",
                meta_data={"transaction_id": str(txn.id)},
            )
        except Exception:  # noqa: BLE001
            pass

        return txn

    async def admin_credit(
        self,
        *,
        target_user: User,
        amount: Decimal,
        reason: str,
        admin: User,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        source: WalletBalanceSource = WalletBalanceSource.WINNINGS,
    ) -> WalletTransaction:
        if admin.role not in _ADMIN_ROLES:
            raise ForbiddenException("Only admins can credit wallet balances")
        await self.get_or_create_wallet(target_user)

        deposit_delta = amount if source == WalletBalanceSource.DEPOSIT else Decimal("0")
        winnings_delta = amount if source == WalletBalanceSource.WINNINGS else Decimal("0")

        txn = await self._mutate(
            user_id=target_user.id,
            type_=WalletTransactionType.CREDIT,
            amount=amount,
            deposit_delta=deposit_delta,
            winnings_delta=winnings_delta,
            balance_source=source,
            description=reason,
            reference_type=reference_type,
            reference_id=reference_id,
            performed_by=admin,
        )

        await self.audit_service.record(
            entity="wallet",
            action=AuditAction.UPDATE,
            entity_id=txn.wallet_id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            new_values={
                "amount": str(amount),
                "target_user_id": str(target_user.id),
                "reason": reason,
                "transaction_id": str(txn.id),
            },
            description=f"Admin credit of {amount} on wallet for user {target_user.id}",
        )

        await self.session.commit()

        try:
            from app.models.notification import NotificationEventType
            from app.notifications.dispatch_service import NotificationDispatchService

            await NotificationDispatchService(self.session).dispatch(
                user=target_user,
                event_type=NotificationEventType.WALLET_CREDITED,
                title="Wallet credited",
                body=f"₹{amount} has been credited to your wallet."
                + (f" ({reason})" if reason else ""),
                event_key=f"wallet_admin_credit:{txn.id}",
                meta_data={"transaction_id": str(txn.id)},
            )
        except Exception:  # noqa: BLE001
            pass

        return txn

    async def admin_debit(
        self,
        *,
        target_user: User,
        amount: Decimal,
        reason: str,
        admin: User,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        source: WalletBalanceSource = WalletBalanceSource.WINNINGS,
    ) -> WalletTransaction:
        if admin.role not in _ADMIN_ROLES:
            raise ForbiddenException("Only admins can debit wallet balances")
        await self.get_or_create_wallet(target_user)

        deposit_delta = -amount if source == WalletBalanceSource.DEPOSIT else Decimal("0")
        winnings_delta = -amount if source == WalletBalanceSource.WINNINGS else Decimal("0")

        txn = await self._mutate(
            user_id=target_user.id,
            type_=WalletTransactionType.DEBIT,
            amount=amount,
            deposit_delta=deposit_delta,
            winnings_delta=winnings_delta,
            balance_source=source,
            description=reason,
            reference_type=reference_type,
            reference_id=reference_id,
            performed_by=admin,
        )

        await self.audit_service.record(
            entity="wallet",
            action=AuditAction.UPDATE,
            entity_id=txn.wallet_id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            new_values={
                "amount": str(amount),
                "target_user_id": str(target_user.id),
                "reason": reason,
                "transaction_id": str(txn.id),
            },
            description=f"Admin debit of {amount} on wallet for user {target_user.id}",
        )

        await self.session.commit()
        return txn

    async def admin_set_frozen(
        self, *, target_user: User, is_frozen: bool, reason: str, admin: User
    ) -> Wallet:
        if admin.role not in _ADMIN_ROLES:
            raise ForbiddenException("Only admins can freeze/unfreeze wallets")

        wallet = await self.get_or_create_wallet(target_user)
        old_value = wallet.is_frozen
        wallet.is_frozen = is_frozen
        await self.session.flush()

        await self.audit_service.record(
            entity="wallet",
            action=AuditAction.STATUS_CHANGE,
            entity_id=wallet.id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            old_values={"is_frozen": old_value},
            new_values={"is_frozen": is_frozen, "reason": reason},
            description=f"Wallet {'frozen' if is_frozen else 'unfrozen'} for user {target_user.id}",
        )

        await self.session.commit()
        await self.session.refresh(wallet)
        return wallet