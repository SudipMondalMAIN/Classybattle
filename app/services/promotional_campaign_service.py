"""
PromotionalCampaignService — admin CRUD for scheduled promotional
notifications, plus the "is this campaign due right now?" + "send it"
logic that `app.core.scheduler` calls on a tick.

Kept deliberately simple: due-check runs in whatever process calls
`send_due_campaigns()` (the app's own APScheduler tick, see
app/core/scheduler.py), no separate worker needed, consistent with how
the rest of this repo's automation (slot rollover, live auto-complete)
already works.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.core.logging import get_logger
from app.models.notification import NotificationEventType
from app.models.promotional_campaign import PromotionalCampaign, PromotionalScheduleType
from app.models.user import User
from app.notifications.dispatch_service import NotificationDispatchService
from app.repositories.promotional_campaign_repository import PromotionalCampaignRepository
from app.repositories.user_repository import UserRepository

logger = get_logger("promotional_campaign_service")

# IST wall-clock, same fixed-offset convention as app/services/slot_generator_service.py
IST = timezone(timedelta(hours=5, minutes=30))


class PromotionalCampaignService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PromotionalCampaignRepository(session)
        self.user_repo = UserRepository(session)
        self.dispatch_service = NotificationDispatchService(session)

    # ------------------------------------------------------------------
    # Admin CRUD
    # ------------------------------------------------------------------
    async def create(
        self,
        *,
        admin: User,
        title: str,
        body: str,
        schedule_type: PromotionalScheduleType,
        scheduled_at: Optional[datetime] = None,
        send_hour: Optional[int] = None,
        send_minute: Optional[int] = None,
        interval_hours: Optional[int] = None,
        send_push: bool = True,
        send_email: bool = False,
    ) -> PromotionalCampaign:
        if schedule_type == PromotionalScheduleType.ONCE and scheduled_at is None:
            raise ValidationException("scheduled_at is required for a one-time campaign")
        if schedule_type == PromotionalScheduleType.DAILY and (send_hour is None or send_minute is None):
            raise ValidationException("send_hour and send_minute are required for a daily campaign")
        if schedule_type == PromotionalScheduleType.INTERVAL_HOURS and not interval_hours:
            raise ValidationException("interval_hours is required for an interval campaign")
        if schedule_type == PromotionalScheduleType.DAILY and not (0 <= send_hour <= 23 and 0 <= send_minute <= 59):
            raise ValidationException("send_hour must be 0-23 and send_minute 0-59")
        if schedule_type == PromotionalScheduleType.INTERVAL_HOURS and interval_hours < 1:
            raise ValidationException("interval_hours must be at least 1")

        campaign = PromotionalCampaign(
            title=title,
            body=body,
            schedule_type=schedule_type,
            scheduled_at=scheduled_at,
            send_hour=send_hour,
            send_minute=send_minute,
            interval_hours=interval_hours,
            send_push=send_push,
            send_email=send_email,
            created_by_admin_id=admin.id,
        )
        self.session.add(campaign)
        await self.session.commit()
        await self.session.refresh(campaign)
        return campaign

    async def list_for_admin(self):
        return await self.repo.list_for_admin()

    async def _get_owned(self, campaign_id: UUID) -> PromotionalCampaign:
        campaign = await self.repo.get_by_id(campaign_id)
        if campaign is None:
            raise NotFoundException("Promotional campaign not found")
        return campaign

    async def set_active(self, campaign_id: UUID, is_active: bool) -> PromotionalCampaign:
        campaign = await self._get_owned(campaign_id)
        campaign.is_active = is_active
        await self.session.commit()
        await self.session.refresh(campaign)
        return campaign

    async def delete(self, campaign_id: UUID) -> None:
        campaign = await self._get_owned(campaign_id)
        campaign.deleted_at = datetime.now(timezone.utc)
        campaign.is_active = False
        await self.session.commit()

    # ------------------------------------------------------------------
    # Scheduler entry point
    # ------------------------------------------------------------------
    def _is_due(self, campaign: PromotionalCampaign, now_utc: datetime) -> bool:
        if campaign.schedule_type == PromotionalScheduleType.ONCE:
            return campaign.last_sent_at is None and campaign.scheduled_at is not None and campaign.scheduled_at <= now_utc

        if campaign.schedule_type == PromotionalScheduleType.DAILY:
            now_ist = now_utc.astimezone(IST)
            if campaign.last_sent_at is not None:
                last_ist = campaign.last_sent_at.astimezone(IST)
                if last_ist.date() == now_ist.date():
                    return False  # already sent today
            else:
                # Never sent yet. If the campaign was created *after* today's
                # target time (e.g. admin activates a "Good Morning" 8 AM
                # campaign at 7 PM), don't fire it right away — that reads as
                # the campaign going off at a random/wrong time. Wait for the
                # next real occurrence of the target time instead.
                created_ist = campaign.created_at.astimezone(IST)
                if created_ist.date() == now_ist.date():
                    created_minutes = created_ist.hour * 60 + created_ist.minute
                    target_minutes = campaign.send_hour * 60 + campaign.send_minute
                    if created_minutes > target_minutes:
                        return False  # wait for tomorrow's occurrence
            target_minutes = campaign.send_hour * 60 + campaign.send_minute
            now_minutes = now_ist.hour * 60 + now_ist.minute
            # Fire once we're at/past the target time today. Combined with
            # the "already sent today" guard above this behaves like a
            # daily cron even though the scheduler tick interval (see
            # app/core/scheduler.py) isn't exactly aligned to the minute.
            return now_minutes >= target_minutes

        if campaign.schedule_type == PromotionalScheduleType.INTERVAL_HOURS:
            if campaign.last_sent_at is None:
                return True
            next_due = campaign.last_sent_at + timedelta(hours=campaign.interval_hours)
            return now_utc >= next_due

        return False

    async def send_due_campaigns(self) -> int:
        """Called from the scheduler on every tick. Sends every active
        campaign whose schedule is due, to every user. Returns how many
        campaigns were actually sent this tick (not recipient count)."""
        now_utc = datetime.now(timezone.utc)
        campaigns = await self.repo.list_active()
        sent_count = 0

        for campaign in campaigns:
            try:
                if not self._is_due(campaign, now_utc):
                    continue

                users = await self.user_repo.list_all(skip=0, limit=100000)
                # ONCE campaigns are one-shot: fold uniqueness into the
                # event_key so a scheduler restart mid-send can't double-
                # fire for a user who already got it, and daily/interval
                # campaigns naturally get a fresh key each run (":<iso ts>")
                # instead of colliding with their own previous send.
                event_key_prefix = f"promo:{campaign.id}:{now_utc.date().isoformat()}"
                recipients = await self.dispatch_service.dispatch_bulk(
                    users=users,
                    event_type=NotificationEventType.PROMOTIONAL,
                    title=campaign.title,
                    body=campaign.body,
                    event_key_prefix=event_key_prefix,
                    send_push=campaign.send_push,
                    send_email=campaign.send_email,
                )

                campaign.last_sent_at = now_utc
                campaign.last_recipient_count = recipients
                if campaign.schedule_type == PromotionalScheduleType.ONCE:
                    campaign.is_active = False
                await self.session.commit()

                sent_count += 1
                logger.info(
                    "promotional_campaign_sent",
                    campaign_id=str(campaign.id),
                    title=campaign.title,
                    recipients=recipients,
                    schedule_type=campaign.schedule_type.value,
                )
            except Exception:  # noqa: BLE001 - one bad campaign must not block the rest
                logger.exception("promotional_campaign_send_failed", campaign_id=str(campaign.id))
                await self.session.rollback()

        return sent_count