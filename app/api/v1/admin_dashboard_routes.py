"""
Admin Dashboard & Analytics API routes — Phase 16.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import require_admin
from app.models.security import AnalyticsPeriodType
from app.models.user import User
from app.schemas.analytics import AnalyticsResponse, DashboardOverview
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/admin/dashboard", tags=["Admin Dashboard & Analytics"])


@router.get("/overview", response_model=DashboardOverview)
async def dashboard_overview(
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = AnalyticsService(session)
    return await service.get_dashboard_overview()


@router.get("/statistics/daily")
async def daily_statistics(
    target_date: Optional[date] = Query(None),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = AnalyticsService(session)
    return await service.get_daily_statistics(target_date)


@router.get("/statistics/weekly")
async def weekly_statistics(
    week_start: Optional[date] = Query(None),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = AnalyticsService(session)
    return await service.get_weekly_statistics(week_start)


@router.get("/statistics/monthly")
async def monthly_statistics(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None, ge=1, le=12),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = AnalyticsService(session)
    return await service.get_monthly_statistics(year, month)


@router.get("/analytics/{metric}", response_model=AnalyticsResponse)
async def get_analytics(
    metric: str,
    period_type: AnalyticsPeriodType = Query(AnalyticsPeriodType.DAILY),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Generic analytics endpoint. `metric` is one of:
    user, registration, tournament, match, wallet, revenue, prize.
    Supports daily / weekly / monthly / custom date ranges.
    """
    service = AnalyticsService(session)
    result = await service.get_analytics(metric, period_type, start_date, end_date)
    return AnalyticsResponse(**result)
