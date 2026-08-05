"""
AnalyticsRepository — Phase 16 (Analytics & Admin Dashboard).

Provides read-only aggregate queries across existing domain tables
(User, Tournament, Match, Wallet, Participant, PrizePool/Payout, Team)
plus a small cache table (AnalyticsSnapshot) so repeated dashboard reads
don't need to recompute the same aggregation within the same period.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


from app.models.participant import Participant
from app.models.prize import PrizePayout, PrizePayoutStatus, PrizePool
from app.models.security import AnalyticsMetricType, AnalyticsPeriodType, AnalyticsSnapshot
from app.models.team import Team
from app.models.tournament import Tournament, TournamentStatus
from app.models.user import User
from app.models.wallet import Wallet
from app.models.wallet_transaction import (
    WalletTransaction,
    WalletTransactionStatus,
    WalletTransactionType,
)


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Dashboard "totals" (point-in-time counts)
    # ------------------------------------------------------------------
    async def count_total_users(self) -> int:
        stmt = select(func.count()).select_from(User).where(User.deleted_at.is_(None))
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_total_teams(self) -> int:
        stmt = select(func.count()).select_from(Team).where(Team.deleted_at.is_(None))
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_total_tournaments(self) -> int:
        stmt = select(func.count()).select_from(Tournament).where(Tournament.deleted_at.is_(None))
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_total_matches(self) -> int:
        """Match-refactor: a "match" is now a generated (non-template)
        Tournament slot row."""
        stmt = (
            select(func.count())
            .select_from(Tournament)
            .where(Tournament.deleted_at.is_(None), Tournament.is_recurring_schedule.is_(False))
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_active_tournaments(self) -> int:
        stmt = (
            select(func.count())
            .select_from(Tournament)
            .where(
                Tournament.deleted_at.is_(None),
                Tournament.status.in_([TournamentStatus.SCHEDULED, TournamentStatus.LIVE]),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_active_matches(self) -> int:
        stmt = (
            select(func.count())
            .select_from(Tournament)
            .where(
                Tournament.deleted_at.is_(None),
                Tournament.is_recurring_schedule.is_(False),
                Tournament.status.in_([TournamentStatus.SCHEDULED, TournamentStatus.LIVE]),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def wallet_summary(self) -> dict[str, Decimal]:
        stmt = select(
            func.coalesce(func.sum(Wallet.available_balance), 0),
            func.coalesce(func.sum(Wallet.locked_balance), 0),
        ).where(Wallet.deleted_at.is_(None))
        available, locked = (await self.session.execute(stmt)).one()
        return {
            "total_available_balance": Decimal(available),
            "total_locked_balance": Decimal(locked),
            "total_balance": Decimal(available) + Decimal(locked),
        }

    async def prize_summary(self) -> dict[str, Any]:
        pool_stmt = select(func.coalesce(func.sum(PrizePool.total_amount), 0)).where(
            PrizePool.deleted_at.is_(None)
        )
        total_pool = Decimal((await self.session.execute(pool_stmt)).scalar_one())

        paid_stmt = select(func.coalesce(func.sum(PrizePayout.amount), 0)).where(
            PrizePayout.deleted_at.is_(None), PrizePayout.status == PrizePayoutStatus.PAID
        )
        total_paid = Decimal((await self.session.execute(paid_stmt)).scalar_one())

        pending_stmt = select(func.coalesce(func.sum(PrizePayout.amount), 0)).where(
            PrizePayout.deleted_at.is_(None),
            PrizePayout.status.in_([PrizePayoutStatus.PENDING, PrizePayoutStatus.PROCESSING]),
        )
        total_pending = Decimal((await self.session.execute(pending_stmt)).scalar_one())

        return {
            "total_prize_pool": total_pool,
            "total_paid_out": total_paid,
            "total_pending_payout": total_pending,
        }

    async def registration_summary(self) -> dict[str, int]:
        total_stmt = select(func.count()).select_from(Participant).where(Participant.deleted_at.is_(None))
        total = int((await self.session.execute(total_stmt)).scalar_one())
        return {"total_registrations": total}

    # ------------------------------------------------------------------
    # Time-bucketed series (daily/weekly/monthly/custom range)
    # ------------------------------------------------------------------
    @staticmethod
    def _bucket_expr(column, period_type: AnalyticsPeriodType):
        if period_type == AnalyticsPeriodType.WEEKLY:
            return func.date_trunc("week", column)
        if period_type == AnalyticsPeriodType.MONTHLY:
            return func.date_trunc("month", column)
        return func.date_trunc("day", column)

    async def user_registrations_series(
        self, start: datetime, end: datetime, period_type: AnalyticsPeriodType
    ) -> Sequence[tuple[Any, int]]:
        bucket = self._bucket_expr(User.created_at, period_type)
        stmt = (
            select(bucket.label("bucket"), func.count())
            .where(User.created_at >= start, User.created_at < end, User.deleted_at.is_(None))
            .group_by(bucket)
            .order_by(bucket)
        )
        result = await self.session.execute(stmt)
        return result.all()

    async def tournament_series(
        self, start: datetime, end: datetime, period_type: AnalyticsPeriodType
    ) -> Sequence[tuple[Any, int]]:
        bucket = self._bucket_expr(Tournament.created_at, period_type)
        stmt = (
            select(bucket.label("bucket"), func.count())
            .where(
                Tournament.created_at >= start,
                Tournament.created_at < end,
                Tournament.deleted_at.is_(None),
            )
            .group_by(bucket)
            .order_by(bucket)
        )
        result = await self.session.execute(stmt)
        return result.all()

    async def match_series(
        self, start: datetime, end: datetime, period_type: AnalyticsPeriodType
    ) -> Sequence[tuple[Any, int]]:
        bucket = self._bucket_expr(Tournament.created_at, period_type)
        stmt = (
            select(bucket.label("bucket"), func.count())
            .where(
                Tournament.created_at >= start,
                Tournament.created_at < end,
                Tournament.deleted_at.is_(None),
                Tournament.is_recurring_schedule.is_(False),
            )
            .group_by(bucket)
            .order_by(bucket)
        )
        result = await self.session.execute(stmt)
        return result.all()

    async def wallet_transaction_series(
        self, start: datetime, end: datetime, period_type: AnalyticsPeriodType
    ) -> Sequence[tuple[Any, int, Decimal]]:
        bucket = self._bucket_expr(WalletTransaction.created_at, period_type)
        stmt = (
            select(bucket.label("bucket"), func.count(), func.coalesce(func.sum(WalletTransaction.amount), 0))
            .where(
                WalletTransaction.created_at >= start,
                WalletTransaction.created_at < end,
                WalletTransaction.status == WalletTransactionStatus.SUCCESS,
            )
            .group_by(bucket)
            .order_by(bucket)
        )
        result = await self.session.execute(stmt)
        return result.all()

    async def revenue_series(
        self, start: datetime, end: datetime, period_type: AnalyticsPeriodType
    ) -> Sequence[tuple[Any, Decimal]]:
        """Revenue approximated as successful DEBIT (entry fee) transactions."""
        bucket = self._bucket_expr(WalletTransaction.created_at, period_type)
        stmt = (
            select(bucket.label("bucket"), func.coalesce(func.sum(WalletTransaction.amount), 0))
            .where(
                WalletTransaction.created_at >= start,
                WalletTransaction.created_at < end,
                WalletTransaction.status == WalletTransactionStatus.SUCCESS,
                WalletTransaction.type == WalletTransactionType.DEBIT,
            )
            .group_by(bucket)
            .order_by(bucket)
        )
        result = await self.session.execute(stmt)
        return result.all()

    async def prize_series(
        self, start: datetime, end: datetime, period_type: AnalyticsPeriodType
    ) -> Sequence[tuple[Any, Decimal]]:
        bucket = self._bucket_expr(PrizePayout.created_at, period_type)
        stmt = (
            select(bucket.label("bucket"), func.coalesce(func.sum(PrizePayout.amount), 0))
            .where(
                PrizePayout.created_at >= start,
                PrizePayout.created_at < end,
                PrizePayout.status == PrizePayoutStatus.PAID,
            )
            .group_by(bucket)
            .order_by(bucket)
        )
        result = await self.session.execute(stmt)
        return result.all()

    async def registration_series(
        self, start: datetime, end: datetime, period_type: AnalyticsPeriodType
    ) -> Sequence[tuple[Any, int]]:
        bucket = self._bucket_expr(Participant.created_at, period_type)
        stmt = (
            select(bucket.label("bucket"), func.count())
            .where(
                Participant.created_at >= start,
                Participant.created_at < end,
                Participant.deleted_at.is_(None),
            )
            .group_by(bucket)
            .order_by(bucket)
        )
        result = await self.session.execute(stmt)
        return result.all()

    # ------------------------------------------------------------------
    # Snapshot cache (dedupe repeated aggregation for the same period)
    # ------------------------------------------------------------------
    async def get_snapshot(
        self, metric_type: AnalyticsMetricType, period_type: AnalyticsPeriodType, period_start: date
    ) -> Optional[AnalyticsSnapshot]:
        stmt = select(AnalyticsSnapshot).where(
            AnalyticsSnapshot.metric_type == metric_type,
            AnalyticsSnapshot.period_type == period_type,
            AnalyticsSnapshot.period_start == period_start,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_snapshot(
        self,
        *,
        metric_type: AnalyticsMetricType,
        period_type: AnalyticsPeriodType,
        period_start: date,
        period_end: date,
        data: dict,
    ) -> AnalyticsSnapshot:
        stmt = (
            pg_insert(AnalyticsSnapshot)
            .values(
                metric_type=metric_type,
                period_type=period_type,
                period_start=period_start,
                period_end=period_end,
                data=data,
            )
            .on_conflict_do_update(
                constraint="uq_analytics_snapshots_metric_period",
                set_={"data": data, "period_end": period_end},
            )
            .returning(AnalyticsSnapshot)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one()
        await self.session.flush()
        return row
