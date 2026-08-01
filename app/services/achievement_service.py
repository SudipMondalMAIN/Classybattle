"""
AchievementService — Phase 15C (Achievements & Moderation).

Single reusable entry point every other service calls to evaluate and
automatically unlock achievements, mirroring how
`NotificationDispatchService.dispatch()` is the single reusable entry
point for notifications:

    await AchievementService(session).evaluate(
        user_id=user.id,
        trigger_type=AchievementTriggerType.MATCH_WIN,
        metric_value=stats.matches_won,
    )

Idempotency: unlocking is guarded by the unique (user_id, achievement_id)
constraint on UserAchievement, so a duplicate/concurrent evaluation of
the same trigger can never double-unlock the same achievement — same
approach as Notification.event_key / LeaderboardUpdateLog.

This service never raises for evaluation failures triggered from other
services' hot paths; callers wrap `evaluate()` in a best-effort manner
the same way notification dispatch is treated (business logic must never
break because an achievement failed to unlock).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence, Union
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.core.logging import get_logger
from app.models.achievement import (
    Achievement,
    AchievementComparison,
    AchievementTriggerType,
    Badge,
    UserAchievement,
)
from app.models.audit_log import AuditAction
from app.models.notification import NotificationEventType
from app.models.user import User
from app.repositories.achievement_repository import (
    AchievementRepository,
    BadgeRepository,
    UserAchievementRepository,
)
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService

logger = get_logger(__name__)


class AchievementService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.badge_repo = BadgeRepository(session)
        self.achievement_repo = AchievementRepository(session)
        self.user_achievement_repo = UserAchievementRepository(session)
        self.user_repo = UserRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------
    # Trigger evaluation (called from other services)
    # ------------------------------------------------------------------
    async def evaluate(
        self,
        *,
        user_id: UUID,
        trigger_type: AchievementTriggerType,
        metric_value: Union[int, float, Decimal],
        meta_data: Optional[dict] = None,
    ) -> list[UserAchievement]:
        """Evaluate every active achievement for `trigger_type` against
        `metric_value` and unlock any that the user has newly earned.
        Best-effort: exceptions are logged and swallowed so this can be
        safely called from any business-logic hot path without risking
        the caller's own transaction."""
        try:
            candidates = await self.achievement_repo.list_active_by_trigger(trigger_type)
            if not candidates:
                return []

            already_unlocked = await self.user_achievement_repo.unlocked_achievement_ids_for_user(user_id)
            metric_decimal = Decimal(str(metric_value))

            unlocked: list[UserAchievement] = []
            for achievement in candidates:
                if achievement.id in already_unlocked:
                    continue
                if self._condition_met(achievement, metric_decimal):
                    result = await self._unlock(
                        user_id=user_id,
                        achievement=achievement,
                        metric_value=metric_decimal,
                        meta_data=meta_data,
                    )
                    if result is not None:
                        unlocked.append(result)
            return unlocked
        except Exception as exc:  # noqa: BLE001 - must never break the caller's flow
            logger.error(
                "achievement_evaluation_failed",
                user_id=str(user_id),
                trigger_type=trigger_type.value,
                error=str(exc),
            )
            return []

    @staticmethod
    def _condition_met(achievement: Achievement, metric_value: Decimal) -> bool:
        threshold = Decimal(str(achievement.threshold))
        if achievement.comparison == AchievementComparison.LTE:
            return metric_value <= threshold
        return metric_value >= threshold

    async def _unlock(
        self,
        *,
        user_id: UUID,
        achievement: Achievement,
        metric_value: Decimal,
        meta_data: Optional[dict],
    ) -> Optional[UserAchievement]:
        try:
            record = await self.user_achievement_repo.create(
                user_id=user_id,
                achievement_id=achievement.id,
                unlocked_at=datetime.now(timezone.utc),
                metric_value=metric_value,
                meta_data=meta_data,
            )
        except IntegrityError:
            # Concurrent evaluation already unlocked it — safe no-op.
            await self.session.rollback()
            return None

        await self.audit.record(
            entity="achievement",
            action=AuditAction.CREATE,
            entity_id=achievement.id,
            actor=None,
            new_values={"user_id": str(user_id), "achievement_code": achievement.code},
            description=f"Achievement '{achievement.name}' unlocked",
        )

        user = await self.user_repo.get_by_id(user_id)
        if user is not None:
            try:
                from app.notifications.dispatch_service import NotificationDispatchService

                await NotificationDispatchService(self.session).dispatch(
                    user=user,
                    event_type=NotificationEventType.GENERAL,
                    title="Achievement unlocked!",
                    body=f"You've unlocked '{achievement.name}'.",
                    event_key=f"achievement_unlocked:{record.id}",
                )
            except Exception:  # noqa: BLE001
                pass

        await self.session.commit()
        await self.session.refresh(record)
        return record

    # ------------------------------------------------------------------
    # Read APIs
    # ------------------------------------------------------------------
    async def list_for_user(self, user_id: UUID) -> Sequence[UserAchievement]:
        return await self.user_achievement_repo.list_for_user(user_id)

    async def list_achievements(self) -> Sequence[Achievement]:
        return await self.achievement_repo.list_active()

    async def list_badges(self) -> Sequence[Badge]:
        return await self.badge_repo.list_active()

    # ------------------------------------------------------------------
    # Admin management
    # ------------------------------------------------------------------
    async def create_badge(self, *, admin: User, name: str, description: Optional[str], icon_url: Optional[str], tier) -> Badge:
        badge = await self.badge_repo.create(
            name=name, description=description, icon_url=icon_url, tier=tier
        )
        await self.audit.record(
            entity="badge", action=AuditAction.CREATE, entity_id=badge.id, actor=admin,
            new_values={"name": name}, description=f"Badge '{name}' created",
        )
        await self.session.commit()
        await self.session.refresh(badge)
        return badge

    async def create_achievement(
        self,
        *,
        admin: User,
        code: str,
        name: str,
        description: Optional[str],
        badge_id: UUID,
        trigger_type: AchievementTriggerType,
        comparison: AchievementComparison,
        threshold: Decimal,
    ) -> Achievement:
        badge = await self.badge_repo.get_by_id(badge_id)
        if badge is None:
            raise NotFoundException("Badge not found")
        existing = await self.achievement_repo.get_by_code(code)
        if existing is not None:
            raise ValidationException(f"An achievement with code '{code}' already exists")

        achievement = await self.achievement_repo.create(
            code=code,
            name=name,
            description=description,
            badge_id=badge_id,
            trigger_type=trigger_type,
            comparison=comparison,
            threshold=threshold,
        )
        await self.audit.record(
            entity="achievement", action=AuditAction.CREATE, entity_id=achievement.id, actor=admin,
            new_values={"code": code, "trigger_type": trigger_type.value},
            description=f"Achievement '{name}' created",
        )
        await self.session.commit()
        await self.session.refresh(achievement)
        return achievement
