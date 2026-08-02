"""
Moderation API routes — Phase 15C (Achievements & Moderation).
Player/Team/Match reports, Warning/Suspension/Ban enforcement, Appeals.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db_session
from app.dependencies.auth import get_current_active_verified_user, require_admin
from app.models.moderation import AppealStatus, ReportStatus, ReportTargetType
from app.models.user import User
from app.schemas.moderation import (
    AppealCreate,
    AppealRead,
    AppealReviewRequest,
    ModerationActionCreate,
    ModerationActionRead,
    ModerationActionRevokeRequest,
    PaginatedAppeals,
    PaginatedModerationActions,
    PaginatedReports,
    ReportCreate,
    ReportRead,
    ReportReviewRequest,
)
from app.services.moderation_service import ModerationService

router = APIRouter(tags=["Moderation"])


# ----------------------------------------------------------------------
# Reports (Player / Team / Match)
# ----------------------------------------------------------------------
@router.post("/reports", response_model=ReportRead, status_code=201)
async def submit_report(
    payload: ReportCreate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ModerationService(session)
    report = await service.submit_report(
        reporter=current_user,
        target_type=payload.target_type,
        target_id=payload.target_id,
        reason=payload.reason,
        description=payload.description,
        evidence_urls=payload.evidence_urls,
    )
    return ReportRead.model_validate(report)


@router.get("/reports/me", response_model=PaginatedReports)
async def list_my_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ModerationService(session)
    items, total = await service.list_reports(page=page, page_size=page_size, reporter_id=current_user.id)
    return PaginatedReports(
        items=[ReportRead.model_validate(r) for r in items], total=total, page=page, page_size=page_size
    )


@router.get("/admin/reports", response_model=PaginatedReports)
async def admin_list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    target_type: Optional[ReportTargetType] = Query(None),
    status: Optional[ReportStatus] = Query(None),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = ModerationService(session)
    items, total = await service.list_reports(
        page=page, page_size=page_size, target_type=target_type, status=status
    )
    return PaginatedReports(
        items=[ReportRead.model_validate(r) for r in items], total=total, page=page, page_size=page_size
    )


@router.get("/admin/reports/{report_id}", response_model=ReportRead)
async def admin_get_report(
    report_id: UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = ModerationService(session)
    report = await service.get_report(report_id)
    return ReportRead.model_validate(report)


@router.get("/admin/reports/{report_id}/shared-history")
async def admin_get_report_shared_history(
    report_id: UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Confirms whether the reporter and the reported player actually
    shared a tournament, so admins can sanity-check a report before
    taking action on it."""
    service = ModerationService(session)
    return await service.get_report_context(report_id)


@router.patch("/admin/reports/{report_id}/review", response_model=ReportRead)
async def admin_review_report(
    report_id: UUID,
    payload: ReportReviewRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = ModerationService(session)
    report = await service.review_report(
        admin=admin, report_id=report_id, status=payload.status, resolution_notes=payload.resolution_notes
    )
    return ReportRead.model_validate(report)


# ----------------------------------------------------------------------
# Warning / Suspension / Ban
# ----------------------------------------------------------------------
@router.post("/admin/moderation-actions", response_model=ModerationActionRead, status_code=201)
async def admin_issue_action(
    payload: ModerationActionCreate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = ModerationService(session)
    action = await service.issue_action(
        admin=admin,
        user_id=payload.user_id,
        action_type=payload.action_type,
        reason=payload.reason,
        report_id=payload.report_id,
        duration_hours=payload.duration_hours,
    )
    return ModerationActionRead.model_validate(action)


@router.patch("/admin/moderation-actions/{action_id}/revoke", response_model=ModerationActionRead)
async def admin_revoke_action(
    action_id: UUID,
    payload: ModerationActionRevokeRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = ModerationService(session)
    action = await service.revoke_action(admin=admin, action_id=action_id, reason=payload.reason)
    return ModerationActionRead.model_validate(action)


@router.get("/admin/moderation-actions", response_model=PaginatedModerationActions)
async def admin_list_actions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[UUID] = Query(None),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = ModerationService(session)
    items, total = await service.list_actions(page=page, page_size=page_size, user_id=user_id)
    return PaginatedModerationActions(
        items=[ModerationActionRead.model_validate(a) for a in items], total=total, page=page, page_size=page_size
    )


@router.get("/users/{user_id}/moderation-actions", response_model=list[ModerationActionRead])
async def list_user_actions(
    user_id: UUID,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ModerationService(session)
    items = await service.list_actions_for_user(user_id)
    return [ModerationActionRead.model_validate(a) for a in items]


# ----------------------------------------------------------------------
# Appeals
# ----------------------------------------------------------------------
@router.post("/appeals", response_model=AppealRead, status_code=201)
async def submit_appeal(
    payload: AppealCreate,
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ModerationService(session)
    appeal = await service.submit_appeal(
        user=current_user, moderation_action_id=payload.moderation_action_id, message=payload.message
    )
    return AppealRead.model_validate(appeal)


@router.get("/appeals/me", response_model=list[AppealRead])
async def list_my_appeals(
    current_user: User = Depends(get_current_active_verified_user),
    session: AsyncSession = Depends(get_db_session),
):
    service = ModerationService(session)
    items = await service.list_appeals_for_user(current_user.id)
    return [AppealRead.model_validate(a) for a in items]


@router.get("/admin/appeals", response_model=PaginatedAppeals)
async def admin_list_appeals(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[AppealStatus] = Query(None),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = ModerationService(session)
    items, total = await service.list_appeals(page=page, page_size=page_size, status=status)
    return PaginatedAppeals(
        items=[AppealRead.model_validate(a) for a in items], total=total, page=page, page_size=page_size
    )


@router.patch("/admin/appeals/{appeal_id}/review", response_model=AppealRead)
async def admin_review_appeal(
    appeal_id: UUID,
    payload: AppealReviewRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    service = ModerationService(session)
    appeal = await service.review_appeal(
        admin=admin, appeal_id=appeal_id, approve=payload.approve, review_notes=payload.review_notes
    )
    return AppealRead.model_validate(appeal)