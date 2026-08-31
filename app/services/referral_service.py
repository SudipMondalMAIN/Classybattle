"""
Referral System v2 Service.

A referral code is applied on a dedicated "Refer & Earn" screen (NOT at
signup) within `apply_window_days` of the referee's own signup date.
Conditions (configurable, each individually enable/disable-able):

1. Referee signs up (implicit -- Referral row only exists once applied).
2. Referee adds at least `min_deposit_amount` via Add Money.
3. Referee joins at least one Paid Tournament (entry_fee > 0), excluding
   self-hosted 1v1 Custom Tournaments (Tournament.category IS NULL).

Once every ENABLED step is satisfied, the referrer's Add Money
(deposit_balance) is credited `reward_amount` -- UNLESS a fraud check
flags it, in which case the referral goes ON_HOLD for admin review
instead of paying automatically.

Milestone bonuses stack on top: every N-th completed referral (per the
admin-configured ladder) pays an extra bonus to the referrer, once each,
tracked via ReferralMilestoneClaim so re-evaluation never double-pays.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_delete_prefix, cache_get, cache_set
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.core.logging import get_logger
from app.core.referral_code import generate_referral_code
from app.models.notification import NotificationEventType
from app.models.referral import Referral, ReferralConfig, ReferralStatus
from app.models.tournament import Tournament
from app.models.user import User, UserRole
from app.notifications.dispatch_service import NotificationDispatchService
from app.repositories.referral_repository import (
    ReferralConfigRepository,
    ReferralMilestoneClaimRepository,
    ReferralRepository,
)
from app.repositories.user_repository import UserRepository
from app.services.wallet_service import WalletService

logger = get_logger("referral_service")

_CACHE_KEY = "referral:config"
_CACHE_TTL_SECONDS = 300
_ADMIN_ROLES = (UserRole.ADMIN, UserRole.SUPER_ADMIN)


class ReferralService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.config_repo = ReferralConfigRepository(session)
        self.referral_repo = ReferralRepository(session)
        self.milestone_repo = ReferralMilestoneClaimRepository(session)
        self.user_repo = UserRepository(session)
        self.wallet_service = WalletService(session)

    # ------------------------------------------------------------------
    # Config (cached)
    # ------------------------------------------------------------------
    async def get_config(self) -> ReferralConfig:
        cached = await cache_get(_CACHE_KEY)
        if cached is not None:
            # Transient (non-session-attached) instance built purely for
            # reading fields -- never passed to config_repo.update() etc.
            return ReferralConfig(
                id=cached["id"],
                reward_amount=Decimal(cached["reward_amount"]),
                min_deposit_amount=Decimal(cached["min_deposit_amount"]),
                require_deposit_step=cached["require_deposit_step"],
                require_paid_tournament_step=cached["require_paid_tournament_step"],
                apply_window_days=cached["apply_window_days"],
                fraud_check_enabled=cached["fraud_check_enabled"],
                max_accounts_per_ip=cached["max_accounts_per_ip"],
                milestone_rules=cached["milestone_rules"],
            )

        config = await self.config_repo.get_singleton()
        await self._cache_config(config)
        return config

    async def _cache_config(self, config: ReferralConfig) -> None:
        data = {
            "id": str(config.id),
            "reward_amount": str(config.reward_amount),
            "min_deposit_amount": str(config.min_deposit_amount),
            "require_deposit_step": config.require_deposit_step,
            "require_paid_tournament_step": config.require_paid_tournament_step,
            "apply_window_days": config.apply_window_days,
            "fraud_check_enabled": config.fraud_check_enabled,
            "max_accounts_per_ip": config.max_accounts_per_ip,
            "milestone_rules": config.milestone_rules,
        }
        await cache_set(_CACHE_KEY, data, ttl=_CACHE_TTL_SECONDS)

    async def get_config_for_admin(self) -> ReferralConfig:
        """Always reads straight from the DB (bypasses cache) so the admin
        panel never shows a stale value right after another admin's edit."""
        return await self.config_repo.get_singleton()

    async def get_rules_for_user(self) -> ReferralConfig:
        """User-facing "how it works" rules -- reuses the cached config
        (same one hot referral evaluation reads), so the app always
        reflects whatever the admin has configured, never a hardcoded
        value baked into the client."""
        return await self.get_config()

    async def update_config(self, *, admin: User, update_data: dict) -> ReferralConfig:
        if admin.role not in _ADMIN_ROLES:
            raise ForbiddenException("Only admins can update referral configuration")
        config = await self.config_repo.get_singleton()

        if "milestone_rules" in update_data and update_data["milestone_rules"] is not None:
            rules = sorted(
                (
                    {"threshold": r.threshold if hasattr(r, "threshold") else r["threshold"],
                     "bonus": str(r.bonus if hasattr(r, "bonus") else r["bonus"])}
                    for r in update_data["milestone_rules"]
                ),
                key=lambda r: r["threshold"],
            )
            update_data = {**update_data, "milestone_rules": rules}

        update_data = {k: v for k, v in update_data.items() if v is not None}
        config = await self.config_repo.update(config, **update_data)
        await self.session.commit()
        await self.session.refresh(config)
        # Invalidate immediately -- next get_config() re-reads from DB and
        # re-populates the cache, so hot paths never see stale config for
        # longer than the write itself takes.
        await cache_delete_prefix(_CACHE_KEY)
        return config

    # ------------------------------------------------------------------
    # User-facing: my code + stats
    # ------------------------------------------------------------------
    async def _ensure_referral_code(self, user: User) -> str:
        if user.referral_code:
            return user.referral_code
        while True:
            candidate = generate_referral_code()
            if await self.user_repo.get_by_referral_code(candidate) is None:
                break
        user.referral_code = candidate
        await self.session.flush()
        return candidate

    async def get_my_code_and_stats(self, user: User) -> dict:
        code = await self._ensure_referral_code(user)
        await self.session.commit()

        referrals = await self.referral_repo.list_by_referrer(user.id)
        completed = [r for r in referrals if r.status == ReferralStatus.COMPLETED]
        pending = [r for r in referrals if r.status == ReferralStatus.PENDING]
        on_hold = [r for r in referrals if r.status == ReferralStatus.ON_HOLD]

        total_earned = sum((r.reward_amount or Decimal("0")) for r in completed)
        claimed_thresholds = await self.milestone_repo.get_claimed_thresholds(user.id)
        total_earned += sum(
            Decimal(rule["bonus"])
            for rule in (await self.get_config()).milestone_rules
            if rule["threshold"] in claimed_thresholds
        )

        config = await self.get_config()
        next_milestone = next(
            (
                rule
                for rule in sorted(config.milestone_rules, key=lambda r: r["threshold"])
                if rule["threshold"] not in claimed_thresholds
            ),
            None,
        )

        applied_as_referee = await self.referral_repo.get_by_referee_id(user.id)

        return {
            "referral_code": code,
            "total_referred": len(referrals),
            "completed_referrals": len(completed),
            "pending_referrals": len(pending),
            "on_hold_referrals": len(on_hold),
            "total_earned": total_earned,
            "next_milestone_at": next_milestone["threshold"] if next_milestone else None,
            "next_milestone_bonus": Decimal(next_milestone["bonus"]) if next_milestone else None,
            "has_applied_referral_code": applied_as_referee is not None,
        }

    async def list_my_referrals(self, user: User) -> list[Referral]:
        return list(await self.referral_repo.list_by_referrer(user.id))

    # ------------------------------------------------------------------
    # Apply a code
    # ------------------------------------------------------------------
    async def apply_code(
        self,
        *,
        referee: User,
        code: str,
        ip_address: Optional[str],
        device_id: Optional[str],
    ) -> Referral:
        existing = await self.referral_repo.get_by_referee_id(referee.id)
        if existing is not None:
            raise ConflictException("You have already applied a referral code")

        config = await self.get_config()
        window_end = referee.created_at + timedelta(days=config.apply_window_days)
        now = datetime.now(timezone.utc)
        if now > window_end:
            raise ValidationException(
                f"The {config.apply_window_days}-day window to apply a referral code has expired"
            )

        referrer = await self.user_repo.get_by_referral_code(code)
        if referrer is None:
            raise NotFoundException("Invalid referral code")
        if referrer.id == referee.id:
            raise ValidationException("You cannot apply your own referral code")

        referral = await self.referral_repo.create(
            referrer_id=referrer.id,
            referee_id=referee.id,
            code_used=code,
            status=ReferralStatus.PENDING,
            ip_address=ip_address,
            device_id=device_id,
        )
        await self.session.commit()
        logger.info(
            "referral_code_applied",
            referral_id=str(referral.id),
            referrer_id=str(referrer.id),
            referee_id=str(referee.id),
        )
        return referral

    # ------------------------------------------------------------------
    # Progress hooks -- called (best-effort) from payment_service on
    # deposit settlement and from participant_service on tournament join.
    # ------------------------------------------------------------------
    async def record_deposit_progress(self, referee: User, deposit_amount: Decimal) -> None:
        referral = await self.referral_repo.get_by_referee_id(referee.id)
        if referral is None or referral.status not in (ReferralStatus.PENDING, ReferralStatus.ON_HOLD):
            return

        config = await self.get_config()
        if not referral.deposit_met and deposit_amount >= config.min_deposit_amount:
            referral.deposit_met = True
            referral.deposit_met_at = datetime.now(timezone.utc)
            await self.session.flush()

        await self._check_and_complete(referral, config)

    async def record_tournament_join_progress(self, referee: User, tournament: Tournament) -> None:
        # Custom (self-hosted 1v1) tournaments have category=None and are
        # explicitly excluded from the "Paid Tournament" condition.
        is_qualifying_paid_tournament = (
            tournament.category is not None
            and bool(tournament.entry_fee and tournament.entry_fee > 0)
        )
        if not is_qualifying_paid_tournament:
            return

        referral = await self.referral_repo.get_by_referee_id(referee.id)
        if referral is None or referral.status not in (ReferralStatus.PENDING, ReferralStatus.ON_HOLD):
            return

        config = await self.get_config()
        if not referral.tournament_met:
            referral.tournament_met = True
            referral.tournament_met_at = datetime.now(timezone.utc)
            await self.session.flush()

        await self._check_and_complete(referral, config)

    # ------------------------------------------------------------------
    # Completion + fraud check + reward + milestones
    # ------------------------------------------------------------------
    async def _check_and_complete(self, referral: Referral, config: ReferralConfig) -> None:
        deposit_ok = (not config.require_deposit_step) or referral.deposit_met
        tournament_ok = (not config.require_paid_tournament_step) or referral.tournament_met
        if not (deposit_ok and tournament_ok):
            await self.session.commit()
            return

        risk_reason = await self._evaluate_risk(referral, config)
        if risk_reason:
            referral.status = ReferralStatus.ON_HOLD
            referral.risk_flagged = True
            referral.risk_reason = risk_reason
            await self.session.commit()
            logger.warning(
                "referral_flagged_on_hold",
                referral_id=str(referral.id),
                reason=risk_reason,
            )
            return

        await self._credit_reward(referral, config)
        await self.session.commit()

    async def _evaluate_risk(self, referral: Referral, config: ReferralConfig) -> Optional[str]:
        if not config.fraud_check_enabled:
            return None

        if referral.ip_address:
            ip_count = await self.referral_repo.count_eligible_by_ip(
                referral.ip_address, exclude_referral_id=referral.id
            )
            if ip_count + 1 > config.max_accounts_per_ip:
                return (
                    f"IP {referral.ip_address} already has {ip_count} eligible referred "
                    f"account(s), exceeding the limit of {config.max_accounts_per_ip}"
                )

        if referral.device_id:
            duplicate = await self.referral_repo.has_duplicate_device(
                referral.device_id, exclude_referral_id=referral.id
            )
            if duplicate:
                return f"Device {referral.device_id} matches another referred account"

        return None

    async def _credit_reward(self, referral: Referral, config: ReferralConfig) -> None:
        referrer = await self.user_repo.get_by_id(referral.referrer_id)
        txn = await self.wallet_service.credit_referral_reward(
            referrer,
            amount=config.reward_amount,
            reference_type="referral_reward",
            reference_id=str(referral.id),
            description="Referral reward credit",
            commit=False,
        )
        referral.status = ReferralStatus.COMPLETED
        referral.reward_amount = config.reward_amount
        referral.reward_credited = True
        referral.credited_at = datetime.now(timezone.utc)
        referral.wallet_transaction_id = txn.id
        await self.session.flush()

        logger.info(
            "referral_completed",
            referral_id=str(referral.id),
            referrer_id=str(referral.referrer_id),
            amount=str(config.reward_amount),
        )

        # Reward gets credited to the wallet above, but nobody ever told
        # the referrer -- this service never called the notification
        # dispatcher anywhere, so a completed referral paid out silently.
        try:
            await NotificationDispatchService(self.session).dispatch(
                user=referrer,
                event_type=NotificationEventType.WALLET_CREDITED,
                title="Referral reward credited \U0001f389",
                body=f"₹{config.reward_amount} has been credited to your wallet for a successful referral.",
                event_key=f"referral_reward:{referral.id}",
                send_email=False,
                meta_data={"referral_id": str(referral.id)},
                commit=False,
            )
        except Exception:  # noqa: BLE001 - never block the reward itself
            pass

        await self._check_milestones(referral.referrer_id, config)

    async def _check_milestones(self, referrer_id: UUID, config: ReferralConfig) -> None:
        completed_count = await self.referral_repo.count_completed_by_referrer(referrer_id)
        claimed = await self.milestone_repo.get_claimed_thresholds(referrer_id)

        referrer = await self.user_repo.get_by_id(referrer_id)
        for rule in sorted(config.milestone_rules, key=lambda r: r["threshold"]):
            threshold = rule["threshold"]
            bonus = Decimal(str(rule["bonus"]))
            if threshold > completed_count or threshold in claimed:
                continue

            txn = await self.wallet_service.credit_referral_reward(
                referrer,
                amount=bonus,
                reference_type="referral_milestone",
                reference_id=f"{referrer_id}:{threshold}",
                description=f"Referral milestone bonus ({threshold} referrals)",
                commit=False,
            )
            await self.milestone_repo.create(
                referrer_id=referrer_id,
                threshold=threshold,
                bonus_amount=bonus,
                wallet_transaction_id=txn.id,
            )
            logger.info(
                "referral_milestone_credited",
                referrer_id=str(referrer_id),
                threshold=threshold,
                bonus=str(bonus),
            )

            try:
                await NotificationDispatchService(self.session).dispatch(
                    user=referrer,
                    event_type=NotificationEventType.WALLET_CREDITED,
                    title="Referral milestone bonus \U0001f389",
                    body=f"₹{bonus} milestone bonus credited for reaching {threshold} referrals.",
                    event_key=f"referral_milestone:{referrer_id}:{threshold}",
                    send_email=False,
                    meta_data={"threshold": threshold},
                    commit=False,
                )
            except Exception:  # noqa: BLE001 - never block the reward itself
                pass

    # ------------------------------------------------------------------
    # Admin: pending list + approve/reject
    # ------------------------------------------------------------------
    async def list_pending_admin(self) -> list[Referral]:
        return list(await self.referral_repo.list_pending_admin())

    async def list_history_for_user(self, user_id: UUID) -> list[Referral]:
        """Full referral history for one user -- every referral where they
        are the referrer or the referee. Used by the admin user-profile
        screen so an admin can see who a user referred and who referred
        them, resolved to real profiles rather than raw IDs."""
        return list(await self.referral_repo.list_involving_user(user_id))

    async def admin_approve(self, *, admin: User, referral_id: UUID) -> Referral:
        if admin.role not in _ADMIN_ROLES:
            raise ForbiddenException("Only admins can approve referrals")

        referral = await self.referral_repo.get_by_id_for_update(referral_id)
        if referral is None:
            raise NotFoundException("Referral not found")
        if referral.status != ReferralStatus.ON_HOLD:
            raise ConflictException(f"Referral is not on hold (status={referral.status.value})")

        config = await self.get_config()
        await self._credit_reward(referral, config)
        referral.reviewed_by_id = admin.id
        referral.reviewed_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(referral)
        return referral

    async def admin_reject(
        self, *, admin: User, referral_id: UUID, admin_note: Optional[str] = None
    ) -> Referral:
        if admin.role not in _ADMIN_ROLES:
            raise ForbiddenException("Only admins can reject referrals")

        referral = await self.referral_repo.get_by_id_for_update(referral_id)
        if referral is None:
            raise NotFoundException("Referral not found")
        if referral.status != ReferralStatus.ON_HOLD:
            raise ConflictException(f"Referral is not on hold (status={referral.status.value})")

        referral.status = ReferralStatus.REJECTED
        referral.reviewed_by_id = admin.id
        referral.reviewed_at = datetime.now(timezone.utc)
        referral.admin_note = admin_note
        await self.session.commit()
        await self.session.refresh(referral)
        return referral