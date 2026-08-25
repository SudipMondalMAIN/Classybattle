"""
Slot Auto-Generation Scheduler.

Runs two lightweight background jobs (via APScheduler's AsyncIOScheduler)
inside the same event loop as the FastAPI app — no separate cron/worker
process needed.

1. `_auto_complete_live_tournaments` — every LIVE_AUTO_COMPLETE_INTERVAL_
   MINUTES (default 10). Unrelated to the daily rollover below: this just
   flips a tournament LIVE -> COMPLETED once its room has been published
   for 40+ minutes (`auto_complete_at` passed). Kept frequent because it's
   about a single live room ending promptly, not about the daily slot
   calendar.

2. `_daily_slot_rollover` — once a day, at 01:00 IST. For every active
   recurring schedule (`Tournament.is_recurring_schedule=True`):
     a. Archives *yesterday's* (IST) generated slots: any that are still
        SCHEDULED or LIVE (i.e. never got played/completed) are force-
        flipped to COMPLETED. This is deliberate — a slot whose date has
        passed is done, played or not. It stays in the DB and remains
        visible to admins via match history, it just drops out of the
        public "active tournaments" listing.
     b. Generates the full set of today's slots in one shot (idempotent —
        a day that's already generated is skipped, so re-running this on
        every app startup is safe).
   Also runs once immediately on startup, so a restart that missed the
   01:00 IST tick (app was down, redeploy, etc.) self-heals on boot.
"""
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.cache import cache_delete_prefix
from app.core.logging import get_logger
from app.database.session import AsyncSessionLocal
from app.models.tournament import TournamentStatus
from app.repositories.tournament_repository import TournamentRepository
from app.services.slot_generator_service import IST, SlotGeneratorService
from app.services.tournament_service import TournamentService

logger = get_logger("slot_scheduler")

LIVE_AUTO_COMPLETE_INTERVAL_MINUTES = 10

_scheduler: AsyncIOScheduler | None = None


async def _auto_complete_live_tournaments() -> None:
    """Frequent tick: flips LIVE tournaments whose auto_complete_at has
    passed (room published 40+ minutes ago) to COMPLETED. Independent of
    the daily slot rollover below."""
    async with AsyncSessionLocal() as session:
        try:
            tournament_service = TournamentService(session)
            completed_count = await tournament_service.auto_complete_due_tournaments()
            if completed_count:
                logger.info("live_auto_complete", tournaments=completed_count)
                # Status changed under the route layer's back -- wipe the
                # tournament cache namespace so clients don't keep polling
                # a stale LIVE status after this flips to COMPLETED.
                await cache_delete_prefix("tournament:")
        except Exception:  # noqa: BLE001 - never let the scheduler die
            logger.exception("live_auto_complete_failed")
            await session.rollback()


async def _daily_slot_rollover() -> None:
    """Runs once a day at 01:00 IST (and once on startup as a safety net).

    Archives yesterday's (IST) generated slots — win, lose, played or
    never touched, a slot whose day has passed is done — then generates
    today's full slot list per active recurring schedule. Any failure is
    logged and swallowed so a single bad schedule can't crash the
    scheduler.
    """
    today = datetime.now(IST).date()
    yesterday = today - timedelta(days=1)

    async with AsyncSessionLocal() as session:
        try:
            tournament_repo = TournamentRepository(session)
            generator = SlotGeneratorService(session)
            schedules = await tournament_repo.list_active_recurring_schedules()

            for schedule in schedules:
                stale_slots = await tournament_repo.list_generated_slots_for_template(
                    schedule.slug, yesterday.isoformat()
                )
                archived = 0
                for slot in stale_slots:
                    if slot.status in (TournamentStatus.COMPLETED, TournamentStatus.CANCELLED):
                        continue
                    await tournament_repo.update(slot, status=TournamentStatus.COMPLETED)
                    archived += 1
                if archived:
                    logger.info(
                        "daily_slot_archive",
                        tournament_id=str(schedule.id),
                        archived=archived,
                    )

                created = await generator.generate_for_day(schedule, today)
                if created:
                    logger.info(
                        "daily_slot_generate",
                        tournament_id=str(schedule.id),
                        matches=len(created),
                    )

            await session.commit()
            # New slots created / old ones archived outside the route
            # layer -- wipe the tournament cache namespace.
            await cache_delete_prefix("tournament:")
        except Exception:  # noqa: BLE001 - never let the scheduler die
            logger.exception("daily_slot_rollover_failed")
            await session.rollback()


def start_slot_scheduler() -> None:
    """Called once from the app's lifespan startup."""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        _auto_complete_live_tournaments,
        "interval",
        minutes=LIVE_AUTO_COMPLETE_INTERVAL_MINUTES,
        id="live_auto_complete",
        next_run_time=datetime.now(timezone.utc),  # also run once immediately on startup
        coalesce=True,
        max_instances=1,
    )
    _scheduler.add_job(
        _daily_slot_rollover,
        CronTrigger(hour=1, minute=0, timezone=IST),
        id="daily_slot_rollover",
        next_run_time=datetime.now(timezone.utc),  # also run once immediately on startup
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info(
        "slot_scheduler_started",
        live_auto_complete_interval_minutes=LIVE_AUTO_COMPLETE_INTERVAL_MINUTES,
        daily_rollover="01:00 IST",
    )


def stop_slot_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("slot_scheduler_stopped")