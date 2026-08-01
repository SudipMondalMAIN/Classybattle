"""
AnalyticsService — Phase 16 (Analytics & Admin Dashboard).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException
from app.models.security import AnalyticsMetricType, AnalyticsPeriodType
from app.repositories.analytics_repository import AnalyticsRepository
from app.schemas.analytics import (
    DashboardOverview,
    DashboardTotals,
    PrizeSummary,
    RegistrationSummary,
    WalletSummary,
)

_METRIC_SERIES_MAP = {
    "user": "user_registrations_series",
    "registration": "registration_series",
    "tournament": "tournament_series",
    "match": "match_series",
    "wallet": "wallet_transaction_series",
    "revenue": "revenue_series",
    "prize": "prize_series",
}


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AnalyticsRepository(session)

    # ------------------------------------------------------------------
    # Admin Dashboard
    # ------------------------------------------------------------------
    async def get_dashboard_overview(self) -> DashboardOverview:
        totals = DashboardTotals(
            total_users=await self.repo.count_total_users(),
            total_teams=await self.repo.count_total_teams(),
            total_tournaments=await self.repo.count_total_tournaments(),
            total_matches=await self.repo.count_total_matches(),
            active_tournaments=await self.repo.count_active_tournaments(),
            active_matches=await self.repo.count_active_matches(),
        )
        wallet_summary = WalletSummary(**await self.repo.wallet_summary())
        prize_summary = PrizeSummary(**await self.repo.prize_summary())
        registration_summary = RegistrationSummary(**await self.repo.registration_summary())

        return DashboardOverview(
            generated_at=datetime.now(timezone.utc),
            totals=totals,
            wallet_summary=wallet_summary,
            prize_summary=prize_summary,
            registration_summary=registration_summary,
        )

    async def get_daily_statistics(self, target_date: Optional[date] = None) -> dict:
        target_date = target_date or datetime.now(timezone.utc).date()
        start = combine_start(target_date)
        end = start + timedelta(days=1)
        return await self._period_snapshot(AnalyticsPeriodType.DAILY, start, end)

    async def get_weekly_statistics(self, week_start: Optional[date] = None) -> dict:
        today = datetime.now(timezone.utc).date()
        week_start = week_start or (today - timedelta(days=today.weekday()))
        start = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc)
        end = start + timedelta(days=7)
        return await self._period_snapshot(AnalyticsPeriodType.WEEKLY, start, end)

    async def get_monthly_statistics(self, year: Optional[int] = None, month: Optional[int] = None) -> dict:
        today = datetime.now(timezone.utc).date()
        year = year or today.year
        month = month or today.month
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 else datetime(
            year, month + 1, 1, tzinfo=timezone.utc
        )
        return await self._period_snapshot(AnalyticsPeriodType.MONTHLY, start, end)

    async def _period_snapshot(
        self, period_type: AnalyticsPeriodType, start: datetime, end: datetime
    ) -> dict:
        cached = await self.repo.get_snapshot(AnalyticsMetricType.DASHBOARD, period_type, start.date())
        if cached is not None and end <= datetime.now(timezone.utc):
            return cached.data

        data = {
            "new_users": len(await self.repo.user_registrations_series(start, end, period_type)),
            "new_tournaments": len(await self.repo.tournament_series(start, end, period_type)),
            "new_matches": len(await self.repo.match_series(start, end, period_type)),
            "new_registrations": len(await self.repo.registration_series(start, end, period_type)),
        }

        if end <= datetime.now(timezone.utc):
            # Only cache fully-elapsed periods so partial "today" data
            # never gets frozen into the snapshot cache.
            await self.repo.upsert_snapshot(
                metric_type=AnalyticsMetricType.DASHBOARD,
                period_type=period_type,
                period_start=start.date(),
                period_end=end.date(),
                data=data,
            )
            await self.session.commit()
        return data

    # ------------------------------------------------------------------
    # Generic analytics (metric + period type + optional custom range)
    # ------------------------------------------------------------------
    async def get_analytics(
        self,
        metric: str,
        period_type: AnalyticsPeriodType,
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> dict:
        if metric not in _METRIC_SERIES_MAP:
            raise BadRequestException(
                f"Unknown metric '{metric}'. Valid metrics: {', '.join(_METRIC_SERIES_MAP)}"
            )

        end = (
            datetime.combine(end_date, datetime.min.time(), tzinfo=timezone.utc)
            if end_date
            else datetime.now(timezone.utc)
        )
        if start_date:
            start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        else:
            default_days = {"daily": 30, "weekly": 90, "monthly": 365, "custom": 30}
            start = end - timedelta(days=default_days.get(period_type.value, 30))

        if start >= end:
            raise BadRequestException("start_date must be before end_date")

        method = getattr(self.repo, _METRIC_SERIES_MAP[metric])
        rows = await method(start, end, period_type)

        series = []
        for row in rows:
            if len(row) == 2:
                bucket, value = row
                series.append({"period_start": bucket.isoformat() if hasattr(bucket, "isoformat") else str(bucket), "value": int(value) if isinstance(value, int) else value})
            else:
                bucket, count, amount = row
                series.append(
                    {
                        "period_start": bucket.isoformat() if hasattr(bucket, "isoformat") else str(bucket),
                        "value": int(count),
                        "amount": str(amount),
                    }
                )

        return {
            "metric": metric,
            "period_type": period_type,
            "range_start": start.date(),
            "range_end": end.date(),
            "series": series,
        }


def combine_start(target_date: date) -> datetime:
    return datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
