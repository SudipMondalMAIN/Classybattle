"""
Schemas for Analytics & Admin Dashboard — Phase 16.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel

from app.models.security import AnalyticsPeriodType


class DashboardTotals(BaseModel):
    total_users: int
    total_teams: int
    total_tournaments: int
    total_matches: int
    active_tournaments: int
    active_matches: int


class WalletSummary(BaseModel):
    total_available_balance: Decimal
    total_locked_balance: Decimal
    total_balance: Decimal


class PrizeSummary(BaseModel):
    total_prize_pool: Decimal
    total_paid_out: Decimal
    total_pending_payout: Decimal


class RegistrationSummary(BaseModel):
    total_registrations: int


class DashboardOverview(BaseModel):
    generated_at: datetime
    totals: DashboardTotals
    wallet_summary: WalletSummary
    prize_summary: PrizeSummary
    registration_summary: RegistrationSummary


class PeriodStatPoint(BaseModel):
    period_start: str
    value: int
    amount: Optional[Decimal] = None


class PeriodStatistics(BaseModel):
    period_type: AnalyticsPeriodType
    range_start: date
    range_end: date
    points: list[PeriodStatPoint]


class AnalyticsQueryParams(BaseModel):
    period_type: AnalyticsPeriodType = AnalyticsPeriodType.DAILY
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class AnalyticsResponse(BaseModel):
    metric: str
    period_type: AnalyticsPeriodType
    range_start: date
    range_end: date
    series: list[dict[str, Any]]
