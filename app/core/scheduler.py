"""
Slot Auto-Generation Scheduler.

Runs a lightweight background job (via APScheduler's AsyncIOScheduler)
inside the same event loop as the FastAPI app — no separate cron/worker
process needed. Every SLOT_SCHEDULER_INTERVAL_MINUTES (default 10), for
every active recurring schedule (`Tournament.is_recurring_schedule=True`):

- If today (IST) has no slots generated yet at all (brand-new schedule,
  or the app was down at midnight), it bootstraps the full day once.
- Otherwise, it does NOT touch today or regenerate anything in bulk. It
  only looks at today's slots whose match has already finished (played
  out / COMPLETED, CANCELLED, or scheduled_end has passed) and creates
  *that same slot* for tomorrow — one match at a time, and only once
  per slot (skipped if tomorrow's slot already exists). So e.g. after
  today's 2:00 PM match is done, tomorrow's 2:00 PM slot gets created;
  the other 26 slots for tomorrow are left alone until their own
  today's match finishes.
"""
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.logging import get_logger
from app.database.session import AsyncSessionLocal
from app.repositories.tournament_repository import TournamentRepository
from app.services.slot_generator_service import IST, SlotGeneratorService
from app.services.tournament_service import TournamentService

logger = get_logger("slot_scheduler")

SLOT_SCHEDULER_INTERVAL_MINUTES = 10

_scheduler: AsyncIOScheduler | None = None


async def _generate_upcoming_slots() -> None:
    """One tick, per active recurring schedule: bootstrap today if it has
    no slots yet, otherwise top up tomorrow one slot at a time for
    whichever of today's matches have already finished. Any failure is
    logged and swallowed so a single bad schedule can't stop the whole
    tick (or crash the scheduler)."""
    today = datetime.now(IST).date()
    # Explicit UTC bounds for "today (IST)" — matches list_for_tournament_on_date's
    # naive func.date(scheduled_start) comparison for slots between IST
    # 05:30 and 23:59, but is also correct for the 00:00-05:29 IST slots
    # that func.date() would otherwise place on the previous UTC day.
    today_start_utc = datetime.combine(today, datetime.min.time(), tzinfo=IST).astimezone(
        timezone.utc
    )
    today_end_utc = today_start_utc + timedelta(days=1)

    async with AsyncSessionLocal() as session:
        try:
            tournament_service = TournamentService(session)
            completed_count = await tournament_service.auto_complete_due_tournaments()
            if completed_count:
                logger.info("slot_auto_complete", tournaments=completed_count)
        except Exception:  # noqa: BLE001 - never let the scheduler die
            logger.exception("slot_auto_complete_failed")
            await session.rollback()

    async with AsyncSessionLocal() as session:
        try:
            generator = SlotGeneratorService(session)
            tournament_repo = TournamentRepository(session)
            schedules = await tournament_repo.list_active_recurring_schedules()

            for schedule in schedules:
                todays_matches = await tournament_repo.list_generated_slots_for_template(
                    schedule.slug, today.isoformat()
                )
                if not todays_matches:
                    created = await generator.generate_for_day(schedule, today)
                    logger.info(
                        "slot_bootstrap_today",
                        tournament_id=str(schedule.id),
                        matches=len(created),
                    )
                    continue

                created = await generator.top_up_completed_slots_for_next_day(schedule)
                if created:
                    logger.info(
                        "slot_next_day_topup",
                        tournament_id=str(schedule.id),
                        matches=len(created),
                        slots=[m.scheduled_start.isoformat() for m in created],
                    )
        except Exception:  # noqa: BLE001 - never let the scheduler die
            logger.exception("slot_auto_generate_failed")
            await session.rollback()


def start_slot_scheduler() -> None:
    """Called once from the app's lifespan startup."""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        _generate_upcoming_slots,
        "interval",
        minutes=SLOT_SCHEDULER_INTERVAL_MINUTES,
        id="slot_auto_generate",
        next_run_time=datetime.now(timezone.utc),  # also run once immediately on startup
        coalesce=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info("slot_scheduler_started", interval_minutes=SLOT_SCHEDULER_INTERVAL_MINUTES)


def stop_slot_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("slot_scheduler_stopped")