"""
AntiCheatService — Phase 16 (Anti-Cheat).

Runs detection heuristics against existing domain data (Users, Teams,
Participants, MatchResults, WalletTransactions) and raises deduplicated
FraudFlag + SecurityEvent records. Detection queries are intentionally
simple, explainable heuristics rather than a black-box ML model, so
admins reviewing a flag can see exactly why it was raised (see
`details` on each FraudFlag).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.core.logging import get_logger
from app.models.tournament_result import TournamentResult as MatchResult, TournamentResultStatus as MatchResultStatus
from app.models.participant import Participant
from app.models.security import (
    FraudFlag,
    FraudFlagStatus,
    FraudFlagType,
    SecurityEventSeverity,
    SecurityEventType,
)
from app.models.team import Team
from app.models.wallet_transaction import WalletTransaction, WalletTransactionStatus
from app.repositories.fraud_repository import FraudFlagRepository
from app.repositories.security_repository import LoginHistoryRepository, SecurityEventRepository

logger = get_logger(__name__)

# Detection thresholds — explainable, tunable constants.
MATCH_ABUSE_REJECTED_THRESHOLD = 3
MATCH_ABUSE_WINDOW_DAYS = 30
WALLET_ABUSE_TX_COUNT_THRESHOLD = 10
WALLET_ABUSE_WINDOW_MINUTES = 10
WALLET_ABUSE_AMOUNT_THRESHOLD = Decimal("50000")


class AntiCheatService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.fraud_repo = FraudFlagRepository(session)
        self.security_event_repo = SecurityEventRepository(session)
        self.login_history_repo = LoginHistoryRepository(session)

    # ------------------------------------------------------------------
    # Duplicate account detection (shared device / IP across accounts)
    # ------------------------------------------------------------------
    async def detect_duplicate_accounts(self, user_id: UUID) -> list[FraudFlag]:
        flags: list[FraudFlag] = []
        known_devices = await self.login_history_repo.known_devices_for_user(user_id)
        known_ips = await self.login_history_repo.known_ips_for_user(user_id)

        linked_users: set[UUID] = set()
        for device_id in known_devices:
            linked_users |= await self.login_history_repo.users_sharing_device(device_id, user_id)
        for ip_address in known_ips:
            linked_users |= await self.login_history_repo.users_sharing_ip(ip_address, user_id)

        for other_user_id in linked_users:
            flag, created = await self.fraud_repo.create_if_not_exists(
                user_id=user_id,
                flag_type=FraudFlagType.DUPLICATE_ACCOUNT,
                risk_score=40,
                related_entity_type="user",
                related_entity_id=str(other_user_id),
                details={"linked_user_id": str(other_user_id)},
                description=f"Account shares device/IP history with user {other_user_id}",
            )
            if created:
                await self._log_security_event(
                    user_id=user_id,
                    event_type=SecurityEventType.DUPLICATE_ACCOUNT,
                    description=f"Possible duplicate of user {other_user_id}",
                )
            flags.append(flag)

        await self.session.commit()
        return flags

    # ------------------------------------------------------------------
    # Duplicate team detection (same/near-identical team name in a tournament)
    # ------------------------------------------------------------------
    async def detect_duplicate_teams(self, tournament_id: UUID) -> list[FraudFlag]:
        stmt = (
            select(func.lower(Team.team_name), func.array_agg(Team.id), func.array_agg(Team.captain_id))
            .where(Team.tournament_id == tournament_id, Team.deleted_at.is_(None))
            .group_by(func.lower(Team.team_name))
            .having(func.count(Team.id) > 1)
        )
        result = await self.session.execute(stmt)
        flags: list[FraudFlag] = []
        for team_name, team_ids, captain_ids in result.all():
            for team_id, captain_id in zip(team_ids, captain_ids):
                if captain_id is None:
                    continue
                flag, created = await self.fraud_repo.create_if_not_exists(
                    user_id=captain_id,
                    flag_type=FraudFlagType.DUPLICATE_TEAM,
                    risk_score=25,
                    related_entity_type="team",
                    related_entity_id=str(team_id),
                    details={"team_name": team_name, "tournament_id": str(tournament_id)},
                    description=f"Duplicate team name '{team_name}' in tournament",
                )
                if created:
                    await self._log_security_event(
                        user_id=captain_id,
                        event_type=SecurityEventType.DUPLICATE_TEAM,
                        description=f"Duplicate team name '{team_name}'",
                    )
                flags.append(flag)

        await self.session.commit()
        return flags

    # ------------------------------------------------------------------
    # Multiple registration detection (same user registered >1x in a tournament)
    # ------------------------------------------------------------------
    async def detect_multiple_registration(self, tournament_id: UUID) -> list[FraudFlag]:
        stmt = (
            select(Participant.user_id, func.count(Participant.id))
            .where(Participant.tournament_id == tournament_id, Participant.deleted_at.is_(None))
            .group_by(Participant.user_id)
            .having(func.count(Participant.id) > 1)
        )
        result = await self.session.execute(stmt)
        flags: list[FraudFlag] = []
        for user_id, count in result.all():
            flag, created = await self.fraud_repo.create_if_not_exists(
                user_id=user_id,
                flag_type=FraudFlagType.MULTIPLE_REGISTRATION,
                risk_score=30,
                related_entity_type="tournament",
                related_entity_id=str(tournament_id),
                details={"registration_count": count},
                description=f"User registered {count} times in the same tournament",
            )
            if created:
                await self._log_security_event(
                    user_id=user_id,
                    event_type=SecurityEventType.MULTIPLE_REGISTRATION,
                    description=f"{count} registrations in tournament {tournament_id}",
                )
            flags.append(flag)

        await self.session.commit()
        return flags

    # ------------------------------------------------------------------
    # Match abuse detection (repeated rejected result submissions)
    # ------------------------------------------------------------------
    async def detect_match_abuse(self, user_id: Optional[UUID] = None) -> list[FraudFlag]:
        since = datetime.now(timezone.utc) - timedelta(days=MATCH_ABUSE_WINDOW_DAYS)
        stmt = (
            select(MatchResult.submitted_by, func.count(MatchResult.id))
            .where(
                MatchResult.status == MatchResultStatus.REJECTED,
                MatchResult.submitted_by.is_not(None),
                MatchResult.created_at >= since,
            )
            .group_by(MatchResult.submitted_by)
            .having(func.count(MatchResult.id) >= MATCH_ABUSE_REJECTED_THRESHOLD)
        )
        if user_id is not None:
            stmt = stmt.where(MatchResult.submitted_by == user_id)

        result = await self.session.execute(stmt)
        flags: list[FraudFlag] = []
        for submitted_by, count in result.all():
            flag, created = await self.fraud_repo.create_if_not_exists(
                user_id=submitted_by,
                flag_type=FraudFlagType.MATCH_ABUSE,
                risk_score=35,
                related_entity_type="match_result",
                related_entity_id="rejected_streak",
                details={"rejected_count": count, "window_days": MATCH_ABUSE_WINDOW_DAYS},
                description=f"{count} rejected match result submissions in {MATCH_ABUSE_WINDOW_DAYS} days",
            )
            if created:
                await self._log_security_event(
                    user_id=submitted_by,
                    event_type=SecurityEventType.MATCH_ABUSE,
                    description=f"{count} rejected match results",
                )
            flags.append(flag)

        await self.session.commit()
        return flags

    # ------------------------------------------------------------------
    # Wallet abuse detection (rapid-fire or unusually large transactions)
    # ------------------------------------------------------------------
    async def detect_wallet_abuse(self, user_id: Optional[UUID] = None) -> list[FraudFlag]:
        since = datetime.now(timezone.utc) - timedelta(minutes=WALLET_ABUSE_WINDOW_MINUTES)

        stmt = (
            select(
                WalletTransaction.user_id,
                func.count(WalletTransaction.id),
                func.coalesce(func.sum(WalletTransaction.amount), 0),
            )
            .where(
                WalletTransaction.created_at >= since,
                WalletTransaction.status == WalletTransactionStatus.SUCCESS,
            )
            .group_by(WalletTransaction.user_id)
            .having(
                (func.count(WalletTransaction.id) >= WALLET_ABUSE_TX_COUNT_THRESHOLD)
                | (func.coalesce(func.sum(WalletTransaction.amount), 0) >= WALLET_ABUSE_AMOUNT_THRESHOLD)
            )
        )
        if user_id is not None:
            stmt = stmt.where(WalletTransaction.user_id == user_id)

        result = await self.session.execute(stmt)

        flags: list[FraudFlag] = []
        for wallet_user_id, tx_count, total_amount in result.all():
            flag, created = await self.fraud_repo.create_if_not_exists(
                user_id=wallet_user_id,
                flag_type=FraudFlagType.WALLET_ABUSE,
                risk_score=45,
                related_entity_type="user",
                related_entity_id=str(wallet_user_id),
                details={
                    "transaction_count": tx_count,
                    "total_amount": str(total_amount),
                    "window_minutes": WALLET_ABUSE_WINDOW_MINUTES,
                },
                description=f"{tx_count} transactions totalling {total_amount} in "
                f"{WALLET_ABUSE_WINDOW_MINUTES} minutes",
            )
            if created:
                await self._log_security_event(
                    user_id=wallet_user_id,
                    event_type=SecurityEventType.WALLET_ABUSE,
                    description=f"{tx_count} rapid wallet transactions ({total_amount})",
                    severity=SecurityEventSeverity.HIGH,
                )
            flags.append(flag)

        await self.session.commit()
        return flags

    # ------------------------------------------------------------------
    # Full scan orchestration
    # ------------------------------------------------------------------
    async def run_full_scan(
        self, tournament_id: Optional[UUID] = None, user_id: Optional[UUID] = None
    ) -> dict:
        details = []
        flags_created = 0
        checks = 0

        if user_id is not None:
            checks += 1
            dup = await self.detect_duplicate_accounts(user_id)
            flags_created += len(dup)
            details.append({"check": "duplicate_accounts", "flags": len(dup)})

        if tournament_id is not None:
            checks += 1
            dup_team = await self.detect_duplicate_teams(tournament_id)
            flags_created += len(dup_team)
            details.append({"check": "duplicate_teams", "flags": len(dup_team)})

            checks += 1
            multi_reg = await self.detect_multiple_registration(tournament_id)
            flags_created += len(multi_reg)
            details.append({"check": "multiple_registration", "flags": len(multi_reg)})

        checks += 1
        match_abuse = await self.detect_match_abuse(user_id)
        flags_created += len(match_abuse)
        details.append({"check": "match_abuse", "flags": len(match_abuse)})

        checks += 1
        wallet_abuse = await self.detect_wallet_abuse(user_id)
        flags_created += len(wallet_abuse)
        details.append({"check": "wallet_abuse", "flags": len(wallet_abuse)})

        return {"flags_created": flags_created, "flags_checked": checks, "details": details}

    # ------------------------------------------------------------------
    # Fraud flag review
    # ------------------------------------------------------------------
    async def list_flags(
        self,
        page: int,
        page_size: int,
        status: Optional[FraudFlagStatus] = None,
        flag_type: Optional[FraudFlagType] = None,
        user_id: Optional[UUID] = None,
    ):
        skip = (page - 1) * page_size
        return await self.fraud_repo.list_flags(
            skip=skip, limit=page_size, status=status, flag_type=flag_type, user_id=user_id
        )

    async def review_flag(
        self, flag_id: UUID, reviewer_id: UUID, status: FraudFlagStatus, review_notes: Optional[str]
    ) -> FraudFlag:
        flag = await self.fraud_repo.get_by_id(flag_id)
        if flag is None:
            raise NotFoundException("Fraud flag not found")
        flag = await self.fraud_repo.update(
            flag,
            status=status,
            reviewed_by=reviewer_id,
            reviewed_at=datetime.now(timezone.utc),
            review_notes=review_notes,
        )
        await self.session.commit()
        return flag

    async def _log_security_event(
        self,
        *,
        user_id: UUID,
        event_type: SecurityEventType,
        description: str,
        severity: SecurityEventSeverity = SecurityEventSeverity.MEDIUM,
    ) -> None:
        await self.security_event_repo.create(
            user_id=user_id, event_type=event_type, severity=severity, description=description
        )
