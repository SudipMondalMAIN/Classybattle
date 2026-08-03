"""
ModerationService — Phase 15C (Achievements & Moderation).

Player/Team/Match reporting, Warning/Suspension/Ban enforcement, and the
Appeal workflow. Reuses AuditService for every state-changing action
(mirrors TournamentService/WalletService), and reuses the existing
`User.status` (ACTIVE/SUSPENDED/BANNED) field already defined on the
User model so enforcement is immediately visible to auth/session checks
elsewhere in the app — no new user-status mechanism is introduced.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException, ValidationException
from app.models.audit_log import AuditAction
from app.models.moderation import (
    Appeal,
    AppealStatus,
    ModerationAction,
    ModerationActionStatus,
    ModerationActionType,
    Report,
    ReportReason,
    ReportStatus,
    ReportTargetType,
)
from app.models.notification import NotificationEventType
from app.models.user import User, UserStatus
from app.repositories.moderation_repository import (
    AppealRepository,
    ModerationActionRepository,
    ReportRepository,
)
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService

_STATUS_BY_ACTION = {
    ModerationActionType.SUSPENSION: UserStatus.SUSPENDED,
    ModerationActionType.BAN: UserStatus.BANNED,
}


class ModerationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.report_repo = ReportRepository(session)
        self.action_repo = ModerationActionRepository(session)
        self.appeal_repo = AppealRepository(session)
        self.user_repo = UserRepository(session)
        self.audit = AuditService(session)

    async def get_report_context(self, report_id: UUID) -> dict:
        """
        Admin-only helper: given a report, confirms whether the reporter
        and the reported player have actually shared a tournament (i.e.
        genuinely played together) — surfaced alongside the report so an
        admin can sanity-check the complaint before acting on it. Only
        meaningful for target_type == PLAYER; other target types return
        an empty list.
        """
        from app.models.moderation import ReportTargetType
        from app.repositories.participant_repository import ParticipantRepository

        report = await self.report_repo.get_by_id(report_id)
        if report is None:
            raise NotFoundException("Report not found")

        shared: list[dict] = []
        if report.target_type == ReportTargetType.PLAYER:
            pairs = await ParticipantRepository(self.session).list_shared_tournaments(
                report.reporter_id, report.target_id
            )
            for participant_a, participant_b in pairs:
                shared.append(
                    {
                        "tournament_id": participant_a.tournament_id,
                        "reporter_status": participant_a.status,
                        "target_status": participant_b.status,
                    }
                )

        return {
            "report_id": report.id,
            "target_type": report.target_type,
            "played_together": len(shared) > 0,
            "shared_tournaments": shared,
        }

    # ------------------------------------------------------------------
    # Reports (Player / Team / Match — unified, polymorphic target)
    # ------------------------------------------------------------------
    async def submit_report(
        self,
        *,
        reporter: User,
        target_type: ReportTargetType,
        target_id: UUID,
        reason: ReportReason,
        description: Optional[str],
        evidence_urls: Optional[list[str]] = None,
    ) -> Report:
        report = await self.report_repo.create(
            reporter_id=reporter.id,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            description=description,
            status=ReportStatus.PENDING,
            evidence_urls={"urls": evidence_urls} if evidence_urls else None,
        )
        await self.audit.record(
            entity="report",
            action=AuditAction.CREATE,
            entity_id=report.id,
            actor=reporter,
            new_values={"target_type": target_type.value, "target_id": str(target_id), "reason": reason.value},
            description=f"{target_type.value.capitalize()} report submitted",
        )
        await self.session.commit()
        await self.session.refresh(report)
        return report

    async def get_report(self, report_id: UUID) -> Report:
        report = await self.report_repo.get_by_id(report_id)
        if report is None:
            raise NotFoundException("Report not found")
        return report

    async def get_report_by_short_id(self, short_id: int) -> Report:
        report = await self.report_repo.get_by_short_id(short_id)
        if report is None:
            raise NotFoundException("Report not found")
        return report

    async def list_reports(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        target_type: Optional[ReportTargetType] = None,
        status: Optional[ReportStatus] = None,
        reporter_id: Optional[UUID] = None,
    ) -> tuple[Sequence[Report], int]:
        return await self.report_repo.list_paginated(
            page=page, page_size=page_size, target_type=target_type, status=status, reporter_id=reporter_id
        )

    async def review_report(
        self,
        *,
        admin: User,
        report_id: UUID,
        status: ReportStatus,
        resolution_notes: Optional[str],
    ) -> Report:
        report = await self.get_report(report_id)
        if status not in (ReportStatus.UNDER_REVIEW, ReportStatus.RESOLVED, ReportStatus.DISMISSED):
            raise ValidationException("Invalid report review status")

        old_status = report.status
        report = await self.report_repo.update(
            report,
            status=status,
            reviewed_by_id=admin.id,
            reviewed_at=datetime.now(timezone.utc),
            resolution_notes=resolution_notes,
        )
        await self.audit.record(
            entity="report",
            action=AuditAction.STATUS_CHANGE,
            entity_id=report.id,
            actor=admin,
            old_values={"status": old_status.value},
            new_values={"status": status.value},
            description=f"Report reviewed -> {status.value}",
        )
        await self.session.commit()
        await self.session.refresh(report)
        return report

    # ------------------------------------------------------------------
    # Warning / Suspension / Ban
    # ------------------------------------------------------------------
    async def issue_action(
        self,
        *,
        admin: User,
        user_id: UUID,
        action_type: ModerationActionType,
        reason: str,
        report_id: Optional[UUID] = None,
        duration_hours: Optional[int] = None,
    ) -> ModerationAction:
        target_user = await self.user_repo.get_by_id(user_id)
        if target_user is None:
            raise NotFoundException("User not found")

        expires_at = None
        if action_type == ModerationActionType.SUSPENSION:
            if not duration_hours or duration_hours <= 0:
                raise ValidationException("Suspension requires a positive duration_hours")
            expires_at = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
        elif action_type == ModerationActionType.BAN and duration_hours:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=duration_hours)

        action = await self.action_repo.create(
            user_id=user_id,
            action_type=action_type,
            status=ModerationActionStatus.ACTIVE,
            reason=reason,
            report_id=report_id,
            issued_by_id=admin.id,
            expires_at=expires_at,
        )

        new_status = _STATUS_BY_ACTION.get(action_type)
        if new_status is not None:
            await self.user_repo.update(target_user, status=new_status)

        await self.audit.record(
            entity="moderation_action",
            action=AuditAction.CREATE,
            entity_id=action.id,
            actor=admin,
            new_values={"user_id": str(user_id), "action_type": action_type.value, "reason": reason},
            description=f"{action_type.value.capitalize()} issued to user {user_id}",
        )
        await self.session.commit()
        await self.session.refresh(action)

        try:
            from app.notifications.dispatch_service import NotificationDispatchService

            await NotificationDispatchService(self.session).dispatch(
                user=target_user,
                event_type=NotificationEventType.GENERAL,
                title=f"Account {action_type.value}",
                body=f"Your account has received a {action_type.value}. Reason: {reason}",
                event_key=f"moderation_action:{action.id}",
            )
        except Exception:  # noqa: BLE001
            pass

        return action

    async def get_action_by_short_id(self, short_id: int) -> ModerationAction:
        action = await self.action_repo.get_by_short_id(short_id)
        if action is None:
            raise NotFoundException("Moderation action not found")
        return action

    async def revoke_action(self, *, admin: User, action_id: UUID, reason: Optional[str]) -> ModerationAction:
        action = await self.action_repo.get_by_id(action_id)
        if action is None:
            raise NotFoundException("Moderation action not found")
        if action.status != ModerationActionStatus.ACTIVE:
            raise BadRequestException("Only an active moderation action can be revoked")

        action = await self.action_repo.update(
            action,
            status=ModerationActionStatus.REVOKED,
            revoked_at=datetime.now(timezone.utc),
            revoked_reason=reason,
        )

        # Restore user's status if they have no other active enforcement.
        remaining = await self.action_repo.list_active_for_user(action.user_id)
        if not remaining:
            target_user = await self.user_repo.get_by_id(action.user_id)
            if target_user is not None:
                await self.user_repo.update(target_user, status=UserStatus.ACTIVE)

        await self.audit.record(
            entity="moderation_action",
            action=AuditAction.STATUS_CHANGE,
            entity_id=action.id,
            actor=admin,
            new_values={"status": "revoked"},
            description=f"Moderation action revoked: {reason or 'no reason given'}",
        )
        await self.session.commit()
        await self.session.refresh(action)
        return action

    async def list_actions_for_user(self, user_id: UUID) -> Sequence[ModerationAction]:
        return await self.action_repo.list_for_user(user_id)

    async def list_actions(
        self, *, page: int = 1, page_size: int = 20, user_id: Optional[UUID] = None
    ) -> tuple[Sequence[ModerationAction], int]:
        return await self.action_repo.list_paginated(page=page, page_size=page_size, user_id=user_id)

    async def expire_due_actions(self) -> int:
        """Best-effort sweep: flips ACTIVE actions past `expires_at` to
        EXPIRED and restores the user's status if nothing else is active.
        Mirrors the existing Celery sweep pattern used elsewhere
        (queue-stall / appointment-reminder sweeps)."""
        due = await self.action_repo.list_expired_active()
        count = 0
        for action in due:
            await self.action_repo.update(action, status=ModerationActionStatus.EXPIRED)
            remaining = await self.action_repo.list_active_for_user(action.user_id)
            if not remaining:
                target_user = await self.user_repo.get_by_id(action.user_id)
                if target_user is not None:
                    await self.user_repo.update(target_user, status=UserStatus.ACTIVE)
            count += 1
        if count:
            await self.session.commit()
        return count

    # ------------------------------------------------------------------
    # Appeals
    # ------------------------------------------------------------------
    async def submit_appeal(self, *, user: User, moderation_action_id: UUID, message: str) -> Appeal:
        action = await self.action_repo.get_by_id(moderation_action_id)
        if action is None:
            raise NotFoundException("Moderation action not found")
        if action.user_id != user.id:
            raise ForbiddenException("You can only appeal your own moderation action")
        if action.status != ModerationActionStatus.ACTIVE:
            raise BadRequestException("Only an active moderation action can be appealed")

        existing = await self.appeal_repo.get_pending_for_action(moderation_action_id)
        if existing is not None:
            raise BadRequestException("An appeal for this action is already pending review")

        appeal = await self.appeal_repo.create(
            moderation_action_id=moderation_action_id,
            user_id=user.id,
            message=message,
            status=AppealStatus.PENDING,
        )
        await self.audit.record(
            entity="appeal",
            action=AuditAction.CREATE,
            entity_id=appeal.id,
            actor=user,
            new_values={"moderation_action_id": str(moderation_action_id)},
            description="Appeal submitted",
        )
        await self.session.commit()
        await self.session.refresh(appeal)
        return appeal

    async def review_appeal(
        self, *, admin: User, appeal_id: UUID, approve: bool, review_notes: Optional[str]
    ) -> Appeal:
        appeal = await self.appeal_repo.get_by_id(appeal_id)
        if appeal is None:
            raise NotFoundException("Appeal not found")
        if appeal.status != AppealStatus.PENDING:
            raise BadRequestException("Appeal has already been reviewed")

        appeal = await self.appeal_repo.update(
            appeal,
            status=AppealStatus.APPROVED if approve else AppealStatus.REJECTED,
            reviewed_by_id=admin.id,
            reviewed_at=datetime.now(timezone.utc),
            review_notes=review_notes,
        )

        if approve:
            await self.revoke_action(
                admin=admin, action_id=appeal.moderation_action_id, reason="Appeal approved"
            )

        await self.audit.record(
            entity="appeal",
            action=AuditAction.STATUS_CHANGE,
            entity_id=appeal.id,
            actor=admin,
            new_values={"status": appeal.status.value},
            description=f"Appeal {'approved' if approve else 'rejected'}",
        )
        await self.session.commit()
        await self.session.refresh(appeal)
        return appeal

    async def list_appeals(
        self, *, page: int = 1, page_size: int = 20, status: Optional[AppealStatus] = None
    ) -> tuple[Sequence[Appeal], int]:
        return await self.appeal_repo.list_paginated(page=page, page_size=page_size, status=status)

    async def list_appeals_for_user(self, user_id: UUID) -> Sequence[Appeal]:
        return await self.appeal_repo.list_for_user(user_id)
