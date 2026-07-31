"""
PrizeService — Prize Pool & Prize Distribution System (Phase 10).

Orchestrates:
- Prize pool configuration (rank-based rules: single winner, top-N,
  percentage-based, fixed-amount) with full validation against the
  tournament's total prize pool.
- Winner assignment (rank -> participant) producing PENDING PrizePayout
  rows, guarded by unique (pool, rank) / (pool, participant) constraints
  so the same rank or participant can never be paid twice.
- Atomic, idempotent distribution: each payout is settled by crediting
  the winner's Wallet (Phase 8) via WalletService.credit(...), passing
  reference_type="prize_payout" + reference_id=<payout.id> so a retried
  distribution can never double-credit a wallet (enforced by
  WalletTransaction's own DB-level uniqueness constraint).
- Manual admin payout / retry-failed-payout, both reusing the same
  atomic settlement primitive.
- Full audit trail via the existing AuditService.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.models.audit_log import AuditAction, AuditActorType
from app.models.participant import Participant, ParticipantStatus
from app.models.prize import (
    PRIZE_POOL_STATUS_TRANSITIONS,
    PrizeDistributionType,
    PrizePayout,
    PrizePayoutStatus,
    PrizePool,
    PrizePoolStatus,
)
from app.models.user import User, UserRole
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.prize_repository import PrizePayoutRepository, PrizePoolRepository
from app.repositories.tournament_repository import TournamentRepository
from app.services.audit_service import AuditService
from app.services.wallet_service import WalletService

_MANAGER_ROLES = {UserRole.ADMIN, UserRole.SUPER_ADMIN}
_TWO_PLACES = Decimal("0.01")


class PrizeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.pool_repo = PrizePoolRepository(session)
        self.payout_repo = PrizePayoutRepository(session)
        self.tournament_repo = TournamentRepository(session)
        self.participant_repo = ParticipantRepository(session)
        self.audit = AuditService(session)
        self.wallet_service = WalletService(session)

    # ------------------------------------------------------------------
    # Authorization helper
    # ------------------------------------------------------------------
    @staticmethod
    def _assert_admin(user: User) -> None:
        if user.role not in _MANAGER_ROLES:
            raise ForbiddenException("Only admins can manage prize pools and payouts")

    # ------------------------------------------------------------------
    # Rule validation
    # ------------------------------------------------------------------
    def _validate_rules(
        self,
        *,
        distribution_type: PrizeDistributionType,
        total_amount: Decimal,
        rules: list[dict],
    ) -> None:
        if not rules:
            raise ValidationException("distribution_rules must not be empty")

        ranks = [int(r["rank"]) for r in rules]
        if len(ranks) != len(set(ranks)):
            raise ValidationException("distribution_rules contains duplicate ranks")
        if sorted(ranks) != list(range(1, len(ranks) + 1)):
            raise ValidationException("distribution_rules ranks must be contiguous starting at 1")

        if distribution_type == PrizeDistributionType.SINGLE_WINNER and len(rules) != 1:
            raise ValidationException("single_winner distribution must have exactly one rank")

        if distribution_type in (
            PrizeDistributionType.SINGLE_WINNER,
            PrizeDistributionType.TOP_N,
            PrizeDistributionType.PERCENTAGE,
        ):
            total_pct = Decimal("0")
            for r in rules:
                pct = r.get("percentage")
                if pct is None:
                    raise ValidationException(
                        f"Rank {r['rank']}: 'percentage' is required for {distribution_type.value}"
                    )
                total_pct += Decimal(str(pct))
            if total_pct != Decimal("100"):
                raise ValidationException(
                    f"distribution_rules percentages must sum to 100, got {total_pct}"
                )
        elif distribution_type == PrizeDistributionType.FIXED_AMOUNT:
            total_amt = Decimal("0")
            for r in rules:
                amt = r.get("amount")
                if amt is None:
                    raise ValidationException(
                        f"Rank {r['rank']}: 'amount' is required for fixed_amount distribution"
                    )
                total_amt += Decimal(str(amt))
            if total_amt.quantize(_TWO_PLACES) != Decimal(str(total_amount)).quantize(_TWO_PLACES):
                raise ValidationException(
                    f"Sum of fixed amounts ({total_amt}) must equal total_amount ({total_amount})"
                )

    def _compute_amount_for_rank(
        self, *, distribution_type: PrizeDistributionType, total_amount: Decimal, rule: dict
    ) -> Decimal:
        if distribution_type == PrizeDistributionType.FIXED_AMOUNT:
            return Decimal(str(rule["amount"])).quantize(_TWO_PLACES)
        pct = Decimal(str(rule["percentage"]))
        return (Decimal(str(total_amount)) * pct / Decimal("100")).quantize(_TWO_PLACES)

    # ------------------------------------------------------------------
    # Prize pool CRUD
    # ------------------------------------------------------------------
    async def create_prize_pool(
        self, *, tournament_id: UUID, admin: User, total_amount: Decimal,
        distribution_type: PrizeDistributionType, distribution_rules: list[dict],
    ) -> PrizePool:
        self._assert_admin(admin)

        tournament = await self.tournament_repo.get_by_id(tournament_id)
        if tournament is None:
            raise NotFoundException("Tournament not found")

        existing = await self.pool_repo.get_by_tournament_id(tournament_id)
        if existing is not None:
            raise ConflictException("A prize pool already exists for this tournament")

        self._validate_rules(
            distribution_type=distribution_type, total_amount=total_amount, rules=distribution_rules
        )

        pool = await self.pool_repo.create(
            tournament_id=tournament_id,
            total_amount=total_amount,
            currency="INR",
            distribution_type=distribution_type,
            distribution_rules=distribution_rules,
            status=PrizePoolStatus.DRAFT,
            created_by=admin.id,
        )

        await self.audit.record(
            entity="prize_pool",
            action=AuditAction.CREATE,
            entity_id=pool.id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            new_values={
                "tournament_id": str(tournament_id),
                "total_amount": str(total_amount),
                "distribution_type": distribution_type.value,
                "distribution_rules": distribution_rules,
            },
            description=f"Prize pool created for tournament {tournament_id}",
        )
        await self.session.commit()
        await self.session.refresh(pool)
        return pool

    async def update_prize_pool(
        self,
        *,
        tournament_id: UUID,
        admin: User,
        total_amount: Optional[Decimal] = None,
        distribution_type: Optional[PrizeDistributionType] = None,
        distribution_rules: Optional[list[dict]] = None,
    ) -> PrizePool:
        self._assert_admin(admin)
        pool = await self.pool_repo.get_by_tournament_id(tournament_id)
        if pool is None:
            raise NotFoundException("Prize pool not found for this tournament")
        if pool.status != PrizePoolStatus.DRAFT:
            raise BadRequestException("Only a DRAFT prize pool can be edited")

        new_total = total_amount if total_amount is not None else pool.total_amount
        new_type = distribution_type if distribution_type is not None else pool.distribution_type
        new_rules = distribution_rules if distribution_rules is not None else pool.distribution_rules

        self._validate_rules(distribution_type=new_type, total_amount=new_total, rules=new_rules)

        old_values = {
            "total_amount": str(pool.total_amount),
            "distribution_type": pool.distribution_type.value,
            "distribution_rules": pool.distribution_rules,
        }

        pool.total_amount = new_total
        pool.distribution_type = new_type
        pool.distribution_rules = new_rules
        await self.session.flush()

        await self.audit.record(
            entity="prize_pool",
            action=AuditAction.UPDATE,
            entity_id=pool.id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            old_values=old_values,
            new_values={
                "total_amount": str(new_total),
                "distribution_type": new_type.value,
                "distribution_rules": new_rules,
            },
            description=f"Prize pool updated for tournament {tournament_id}",
        )
        await self.session.commit()
        await self.session.refresh(pool)
        return pool

    async def publish_prize_pool(self, *, tournament_id: UUID, admin: User) -> PrizePool:
        self._assert_admin(admin)
        pool = await self.pool_repo.get_by_tournament_id(tournament_id)
        if pool is None:
            raise NotFoundException("Prize pool not found for this tournament")
        if PrizePoolStatus.PUBLISHED not in PRIZE_POOL_STATUS_TRANSITIONS[pool.status]:
            raise BadRequestException(f"Cannot publish a prize pool in status '{pool.status.value}'")

        pool.status = PrizePoolStatus.PUBLISHED
        pool.published_at = datetime.now(timezone.utc)
        await self.session.flush()

        await self.audit.record(
            entity="prize_pool",
            action=AuditAction.STATUS_CHANGE,
            entity_id=pool.id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            new_values={"status": PrizePoolStatus.PUBLISHED.value},
            description=f"Prize pool published for tournament {tournament_id}",
        )
        await self.session.commit()
        await self.session.refresh(pool)
        return pool

    async def cancel_prize_pool(self, *, tournament_id: UUID, admin: User, reason: str) -> PrizePool:
        self._assert_admin(admin)
        pool = await self.pool_repo.get_by_tournament_id(tournament_id)
        if pool is None:
            raise NotFoundException("Prize pool not found for this tournament")
        if PrizePoolStatus.CANCELLED not in PRIZE_POOL_STATUS_TRANSITIONS[pool.status]:
            raise BadRequestException(f"Cannot cancel a prize pool in status '{pool.status.value}'")

        pool.status = PrizePoolStatus.CANCELLED
        await self.session.flush()

        await self.audit.record(
            entity="prize_pool",
            action=AuditAction.STATUS_CHANGE,
            entity_id=pool.id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            new_values={"status": PrizePoolStatus.CANCELLED.value, "reason": reason},
            description=f"Prize pool cancelled for tournament {tournament_id}: {reason}",
        )
        await self.session.commit()
        await self.session.refresh(pool)
        return pool

    async def get_prize_pool(self, *, tournament_id: UUID) -> PrizePool:
        pool = await self.pool_repo.get_by_tournament_id(tournament_id)
        if pool is None:
            raise NotFoundException("Prize pool not found for this tournament")
        return pool

    async def list_prize_pools(
        self, *, page: int = 1, page_size: int = 20, status: Optional[PrizePoolStatus] = None,
        sort_by: str = "created_at", sort_order: str = "desc",
    ) -> tuple[Sequence[PrizePool], int]:
        return await self.pool_repo.list_paginated(
            page=page, page_size=page_size, status=status, sort_by=sort_by, sort_order=sort_order
        )

    # ------------------------------------------------------------------
    # Winner assignment -> PrizePayout creation
    # ------------------------------------------------------------------
    async def assign_winners(
        self, *, tournament_id: UUID, admin: User, winners: list[dict]
    ) -> list[PrizePayout]:
        """winners: [{"rank": 1, "participant_id": UUID}, ...].

        Idempotent: re-assigning the same rank/participant pair is a
        no-op (existing PENDING payout is left untouched); assigning a
        rank or participant that already has a payout raises a conflict
        so winners can't silently be overwritten after the fact.
        """
        self._assert_admin(admin)
        pool = await self.pool_repo.get_by_tournament_id(tournament_id)
        if pool is None:
            raise NotFoundException("Prize pool not found for this tournament")
        if pool.status not in (PrizePoolStatus.PUBLISHED, PrizePoolStatus.DISTRIBUTING):
            raise BadRequestException(
                "Winners can only be assigned once the prize pool is PUBLISHED"
            )

        rule_by_rank = {int(r["rank"]): r for r in pool.distribution_rules}
        created: list[PrizePayout] = []

        for winner in winners:
            rank = int(winner["rank"])
            participant_id = winner["participant_id"]
            if isinstance(participant_id, str):
                participant_id = UUID(participant_id)

            rule = rule_by_rank.get(rank)
            if rule is None:
                raise ValidationException(f"Rank {rank} has no matching distribution rule")

            participant = await self.participant_repo.get_by_id(participant_id)
            if participant is None or participant.tournament_id != tournament_id:
                raise NotFoundException(f"Participant {participant_id} not found in this tournament")
            if participant.status not in (
                ParticipantStatus.CONFIRMED,
                ParticipantStatus.CHECKED_IN,
            ):
                raise BadRequestException(
                    f"Participant {participant_id} is not in a winnable status"
                )

            existing_rank = await self.payout_repo.get_by_pool_and_rank(pool.id, rank)
            existing_participant = await self.payout_repo.get_by_pool_and_participant(
                pool.id, participant_id
            )
            if existing_rank is not None or existing_participant is not None:
                if (
                    existing_rank is not None
                    and existing_rank.participant_id == participant_id
                ):
                    # Already assigned exactly this way — idempotent no-op.
                    created.append(existing_rank)
                    continue
                raise ConflictException(
                    f"Rank {rank} or participant {participant_id} is already assigned a payout"
                )

            amount = self._compute_amount_for_rank(
                distribution_type=pool.distribution_type, total_amount=pool.total_amount, rule=rule
            )

            payout = await self.payout_repo.create(
                prize_pool_id=pool.id,
                tournament_id=tournament_id,
                participant_id=participant_id,
                user_id=participant.user_id,
                rank=rank,
                amount=amount,
                currency=pool.currency,
                status=PrizePayoutStatus.PENDING,
            )
            created.append(payout)

        if pool.status == PrizePoolStatus.PUBLISHED:
            pool.status = PrizePoolStatus.DISTRIBUTING
            await self.session.flush()

        await self.audit.record(
            entity="prize_pool",
            action=AuditAction.CREATE,
            entity_id=pool.id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            new_values={"winners_assigned": [str(p.id) for p in created]},
            description=f"Winners assigned for tournament {tournament_id}",
        )
        await self.session.commit()
        for p in created:
            await self.session.refresh(p)
        return created

    # ------------------------------------------------------------------
    # Atomic, idempotent settlement primitive
    # ------------------------------------------------------------------
    async def _settle_payout(self, *, payout: PrizePayout, admin: Optional[User]) -> PrizePayout:
        """Credits the winner's wallet for a single PENDING/FAILED payout,
        atomically transitioning it to PAID. Safe to call repeatedly:
        already-PAID payouts are returned unchanged, and the underlying
        WalletService.credit(...) call is itself protected by a DB unique
        constraint on (reference_type, reference_id, type), so a payout
        can never be credited twice even under concurrent retries."""
        if payout.status == PrizePayoutStatus.PAID:
            return payout
        if payout.status not in (PrizePayoutStatus.PENDING, PrizePayoutStatus.FAILED):
            raise BadRequestException(
                f"Payout {payout.id} cannot be settled from status '{payout.status.value}'"
            )

        payout.status = PrizePayoutStatus.PROCESSING
        await self.session.flush()

        try:
            user = payout.user
            txn = await self.wallet_service.credit(
                user,
                amount=payout.amount,
                reference_type="prize_payout",
                reference_id=str(payout.id),
                description=f"Prize payout for rank {payout.rank} — tournament {payout.tournament_id}",
                metadata={
                    "prize_pool_id": str(payout.prize_pool_id),
                    "tournament_id": str(payout.tournament_id),
                    "rank": payout.rank,
                },
                commit=False,
            )
        except ConflictException:
            # A wallet transaction for this exact payout already exists —
            # distribution already succeeded previously; treat as settled.
            payout.status = PrizePayoutStatus.PAID
            payout.paid_at = payout.paid_at or datetime.now(timezone.utc)
            await self.session.flush()
            return payout
        except Exception as exc:  # noqa: BLE001 - any wallet failure marks payout FAILED
            payout.status = PrizePayoutStatus.FAILED
            payout.failure_reason = str(exc)
            payout.retry_count += 1
            await self.session.flush()
            raise

        payout.status = PrizePayoutStatus.PAID
        payout.wallet_transaction_id = txn.id
        payout.paid_at = datetime.now(timezone.utc)
        payout.failure_reason = None
        payout.performed_by = admin.id if admin is not None else None
        await self.session.flush()
        return payout

    # ------------------------------------------------------------------
    # Automatic distribution
    # ------------------------------------------------------------------
    async def distribute_prizes(self, *, tournament_id: UUID, admin: User) -> list[PrizePayout]:
        """Processes every PENDING/FAILED payout for the tournament's
        prize pool, crediting winners' wallets atomically and
        idempotently. Already-PAID payouts are left untouched, so calling
        this multiple times (e.g. after a partial failure) is safe."""
        self._assert_admin(admin)
        pool = await self.pool_repo.get_by_tournament_id(tournament_id)
        if pool is None:
            raise NotFoundException("Prize pool not found for this tournament")
        if pool.status not in (PrizePoolStatus.DISTRIBUTING, PrizePoolStatus.PUBLISHED):
            raise BadRequestException(
                f"Cannot distribute a prize pool in status '{pool.status.value}'"
            )

        payouts = await self.payout_repo.list_pending_or_failed_for_pool(pool.id)
        if not payouts:
            raise BadRequestException("No pending payouts to distribute — assign winners first")

        settled: list[PrizePayout] = []
        errors: list[str] = []
        for payout in payouts:
            try:
                result = await self._settle_payout(payout=payout, admin=admin)
                settled.append(result)
            except Exception as exc:  # noqa: BLE001 - continue processing remaining payouts
                errors.append(f"{payout.id}: {exc}")
                continue

        all_payouts = await self.payout_repo.list_for_pool(pool.id)
        all_paid = all(p.status == PrizePayoutStatus.PAID for p in all_payouts)
        if all_paid:
            pool.status = PrizePoolStatus.DISTRIBUTED
            pool.distributed_at = datetime.now(timezone.utc)
        else:
            pool.status = PrizePoolStatus.DISTRIBUTING
        await self.session.flush()

        await self.audit.record(
            entity="prize_pool",
            action=AuditAction.OTHER,
            entity_id=pool.id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            new_values={
                "settled_count": len(settled),
                "error_count": len(errors),
                "errors": errors,
                "pool_status": pool.status.value,
            },
            description=f"Prize distribution run for tournament {tournament_id}",
        )
        await self.session.commit()
        for p in settled:
            await self.session.refresh(p)
        return settled

    # ------------------------------------------------------------------
    # Admin manual payout / retry
    # ------------------------------------------------------------------
    async def admin_manual_payout(
        self, *, payout_id: UUID, admin: User, reason: str
    ) -> PrizePayout:
        self._assert_admin(admin)
        payout = await self.payout_repo.get_by_id_for_update(payout_id)
        if payout is None:
            raise NotFoundException("Prize payout not found")
        if payout.status == PrizePayoutStatus.PAID:
            raise ConflictException("This payout has already been paid")

        result = await self._settle_payout(payout=payout, admin=admin)

        await self.audit.record(
            entity="prize_payout",
            action=AuditAction.UPDATE,
            entity_id=payout.id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            new_values={"status": result.status.value, "reason": reason},
            description=f"Manual payout for prize payout {payout.id}: {reason}",
        )
        await self.session.commit()
        await self.session.refresh(result)
        return result

    async def retry_payout(self, *, payout_id: UUID, admin: User) -> PrizePayout:
        self._assert_admin(admin)
        payout = await self.payout_repo.get_by_id_for_update(payout_id)
        if payout is None:
            raise NotFoundException("Prize payout not found")
        if payout.status != PrizePayoutStatus.FAILED:
            raise BadRequestException("Only a FAILED payout can be retried")

        result = await self._settle_payout(payout=payout, admin=admin)

        await self.audit.record(
            entity="prize_payout",
            action=AuditAction.UPDATE,
            entity_id=payout.id,
            actor=admin,
            actor_type=AuditActorType.ADMIN,
            new_values={"status": result.status.value, "retry_count": result.retry_count},
            description=f"Retried prize payout {payout.id}",
        )
        await self.session.commit()
        await self.session.refresh(result)
        return result

    # ------------------------------------------------------------------
    # History / lookups
    # ------------------------------------------------------------------
    async def get_payout(self, *, payout_id: UUID, user: User) -> PrizePayout:
        payout = await self.payout_repo.get_by_id(payout_id)
        if payout is None:
            raise NotFoundException("Prize payout not found")
        if payout.user_id != user.id and user.role not in _MANAGER_ROLES:
            raise ForbiddenException("You do not have permission to view this payout")
        return payout

    async def list_payouts_for_tournament(
        self,
        *,
        tournament_id: UUID,
        page: int = 1,
        page_size: int = 20,
        status: Optional[PrizePayoutStatus] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[PrizePayout], int]:
        return await self.payout_repo.list_paginated(
            page=page,
            page_size=page_size,
            tournament_id=tournament_id,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def list_my_payouts(
        self,
        *,
        user: User,
        page: int = 1,
        page_size: int = 20,
        status: Optional[PrizePayoutStatus] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[PrizePayout], int]:
        return await self.payout_repo.list_paginated(
            page=page, page_size=page_size, user_id=user.id, status=status,
            sort_by=sort_by, sort_order=sort_order,
        )

    async def list_payouts_admin(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        prize_pool_id: Optional[UUID] = None,
        tournament_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        status: Optional[PrizePayoutStatus] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[PrizePayout], int]:
        return await self.payout_repo.list_paginated(
            page=page,
            page_size=page_size,
            prize_pool_id=prize_pool_id,
            tournament_id=tournament_id,
            user_id=user_id,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
        )
