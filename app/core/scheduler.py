"""
Slot Auto-Generation Scheduler.

Runs a lightweight background job (via APScheduler's AsyncIOScheduler)
inside the same event loop as the FastAPI app — no separate cron/worker
process needed. Every SLOT_SCHEDULER_INTERVAL_MINUTES (default 10, so a
10:00 AM match is picked up again at 10:10 AM), it generates slots for
TODAY and TOMORROW for every active recurring schedule
(`Tournament.is_recurring_schedule=True`).

Why both today AND tomorrow, every run (not just once after midnight):
- Idempotent — `SlotGeneratorService.generate_for_day` no-ops if a day
  is already generated, so re-running constantly is cheap and safe.
- Self-healing — if the app was down at midnight, or a new schedule was
  created mid-day, the very next tick (within 10 minutes) fixes it
  instead of waiting for the next day's midnight run.
- Always-a-day-ahead — a user can join tomorrow's 10:00 AM slot today,
  because tomorrow's Match rows already exist well before tomorrow
  starts.
"""
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.logging import get_logger
from app.database.session import AsyncSessionLocal
from app.services.slot_generator_service import SlotGeneratorService

logger = get_logger("slot_scheduler")

SLOT_SCHEDULER_INTERVAL_MINUTES = 10

_scheduler: AsyncIOScheduler | None = None


async def _generate_upcoming_slots() -> None:
    """One tick: generate today's + tomorrow's slots for every active
    recurring schedule. Any failure is logged and swallowed so a single
    bad schedule can't stop the whole tick (or crash the scheduler)."""
    today = datetime.now(timezone.utc).date()
    tomorrow = today + timedelta(days=1)

    async with AsyncSessionLocal() as session:
        try:
            generator = SlotGeneratorService(session)
            for target_date in (today, tomorrow):
                results = await generator.generate_for_all_active_schedules(target_date)
                total = sum(len(matches) for matches in results.values())
                logger.info(
                    "slot_auto_generate_tick",
                    target_date=str(target_date),
                    schedules=len(results),
                    matches=total,
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
