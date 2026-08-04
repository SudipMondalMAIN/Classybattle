"""
Slot Generator Service — recurring match-schedule support.

A `Tournament` with `is_recurring_schedule=True` is not a bracket event —
it's a daily template (e.g. "Free Fire Classic", 10:00 AM to 11:00 PM,
every 30 minutes). This service reads that template and stamps out one
`Match` row per slot for a given day. Each generated Match is a normal
Match record (reuses existing room/check-in/assignment infrastructure
in MatchService) with:

- round_number = 1, match_number = the slot's sequence number for the day
- scheduled_start / scheduled_end set from the template + slot index
- team_format copied from the template's allowed_team_formats (for
  Clash-Squad-style schedules with more than one format, one Match is
  generated per format per time slot)
- entry_fee copied from the template's entry_fee unless overridden

Generation is idempotent per (tournament, day): re-running it for a day
that's already been generated is a no-op, tracked via
`Tournament.last_generated_on`.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

# Admin-entered daily_slot_times / daily_start_time / daily_end_time are
# IST wall-clock times (e.g. "18:00" means 6:00 PM in India), NOT UTC.
# All Match.scheduled_start/end columns are stored in UTC, so every
# admin-entered time must be interpreted as IST first, then converted
# to UTC before it touches the database.
IST = timezone(timedelta(hours=5, minutes=30))
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationException
from app.models.match import Match, MatchStatus, RoomStatus
from app.models.tournament import Tournament
from app.repositories.match_repository import MatchRepository
from app.repositories.tournament_repository import TournamentRepository


class SlotGeneratorService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.match_repo = MatchRepository(session)
        self.tournament_repo = TournamentRepository(session)

    async def generate_for_day(
        self, tournament: Tournament, target_date: date
    ) -> list[Match]:
        """Generate all slots for one schedule template, for one day.

        Safe to call repeatedly for the same (tournament, target_date) —
        already-generated days are skipped.
        """
        if not tournament.is_recurring_schedule:
            raise ValidationException(
                "This tournament is not a recurring schedule — cannot generate slots"
            )

        if (
            tournament.last_generated_on is not None
            and tournament.last_generated_on.date() >= target_date
        ):
            # Already generated for this day (or later) — no-op.
            return await self.match_repo.list_for_tournament_on_date(
                tournament.id, target_date
            )

        created: list[Match] = []
        slot_number = await self.match_repo.next_match_number(tournament.id, round_number=1)

        if tournament.daily_slot_times:
            # ------------------------------------------------------------
            # Simplified flow: one Match per admin-configured "HH:MM"
            # entry in daily_slot_times. Number of matches/day = however
            # many entries Admin has configured (not locked to any fixed
            # number — 27, 28, 29, whatever). team_format is derived from
            # the schedule's category (solo -> "solo", squad -> "NvN"
            # from squad_size).
            # ------------------------------------------------------------
            team_format = (
                "solo"
                if tournament.category is None or tournament.category.value == "solo"
                else f"{tournament.squad_size}v{tournament.squad_size}"
            )
            for time_str in tournament.daily_slot_times:
                hour, minute = (int(p) for p in time_str.split(":")[:2])
                # Interpret the admin-entered HH:MM as IST wall-clock time,
                # then convert to UTC for storage.
                start_ist = datetime.combine(
                    target_date, datetime.min.time(), tzinfo=IST
                ).replace(hour=hour, minute=minute)
                start = start_ist.astimezone(timezone.utc)
                match = await self.match_repo.create(
                    tournament_id=tournament.id,
                    round_number=1,
                    match_number=slot_number,
                    scheduled_start=start,
                    scheduled_end=start + timedelta(minutes=30),
                    team_format=team_format,
                    entry_fee=tournament.entry_fee,
                    prize_pool=tournament.prize_pool,
                    match_status=MatchStatus.SCHEDULED,
                    room_status=RoomStatus.NOT_CREATED,
                    auto_disqualify_on_no_show=True,
                    created_by=tournament.created_by,
                )
                created.append(match)
                slot_number += 1
        elif tournament.daily_start_time and tournament.daily_end_time and tournament.slot_interval_minutes:
            # Legacy interval-based generation, kept for backward compatibility.
            formats = tournament.allowed_team_formats or ["solo"]
            interval = timedelta(minutes=tournament.slot_interval_minutes)
            # Same IST -> UTC fix as above for the legacy fields.
            start_dt = datetime.combine(
                target_date, tournament.daily_start_time, tzinfo=IST
            ).astimezone(timezone.utc)
            end_dt = datetime.combine(
                target_date, tournament.daily_end_time, tzinfo=IST
            ).astimezone(timezone.utc)
            cursor = start_dt
            while cursor < end_dt:
                slot_end = min(cursor + interval, end_dt)
                for team_format in formats:
                    match = await self.match_repo.create(
                        tournament_id=tournament.id,
                        round_number=1,
                        match_number=slot_number,
                        scheduled_start=cursor,
                        scheduled_end=slot_end,
                        team_format=team_format,
                        entry_fee=tournament.entry_fee,
                        prize_pool=tournament.prize_pool,
                        match_status=MatchStatus.SCHEDULED,
                        room_status=RoomStatus.NOT_CREATED,
                        auto_disqualify_on_no_show=True,
                        created_by=tournament.created_by,
                    )
                    created.append(match)
                    slot_number += 1
                cursor += interval
        else:
            raise ValidationException(
                "Schedule is missing daily_slot_times (or legacy daily_start_time/daily_end_time/slot_interval_minutes)"
            )

        tournament.last_generated_on = datetime.now(timezone.utc)
        await self.session.commit()
        for match in created:
            await self.session.refresh(match)

        return created

    async def top_up_completed_slots_for_next_day(self, tournament: Tournament) -> list[Match]:
        """Per-slot generation for the simplified daily_slot_times flow.

        Instead of bulk-regenerating the whole day's schedule on every
        scheduler tick, this looks only at *today's* (IST) slots for this
        schedule and, for each one whose match has already finished
        (COMPLETED/CANCELLED, or its scheduled_end has passed), creates
        that same time-slot for *tomorrow* — one Match at a time, only
        once per slot (skipped if tomorrow's slot already exists).
        """
        if not tournament.is_recurring_schedule or not tournament.daily_slot_times:
            return []

        now_ist = datetime.now(IST)
        today = now_ist.date()
        tomorrow = today + timedelta(days=1)

        def ist_day_bounds_utc(day: date):
            start_ist = datetime.combine(day, datetime.min.time(), tzinfo=IST)
            return start_ist.astimezone(timezone.utc), (start_ist + timedelta(days=1)).astimezone(
                timezone.utc
            )

        today_start_utc, today_end_utc = ist_day_bounds_utc(today)
        tomorrow_start_utc, tomorrow_end_utc = ist_day_bounds_utc(tomorrow)

        todays_matches = await self.match_repo.list_for_tournament_between(
            tournament.id, today_start_utc, today_end_utc
        )
        tomorrows_matches = await self.match_repo.list_for_tournament_between(
            tournament.id, tomorrow_start_utc, tomorrow_end_utc
        )
        tomorrow_slot_times = {
            m.scheduled_start.astimezone(IST).strftime("%H:%M") for m in tomorrows_matches
        }

        team_format = (
            "solo"
            if tournament.category is None or tournament.category.value == "solo"
            else f"{tournament.squad_size}v{tournament.squad_size}"
        )

        created: list[Match] = []
        for match in todays_matches:
            slot_time = match.scheduled_start.astimezone(IST).strftime("%H:%M")

            if slot_time not in tournament.daily_slot_times:
                continue  # slot removed from the template — don't recreate it
            if slot_time in tomorrow_slot_times:
                continue  # already generated for tomorrow

            is_finished = match.match_status in (MatchStatus.COMPLETED, MatchStatus.CANCELLED)
            is_past = match.scheduled_end is not None and now_ist >= match.scheduled_end.astimezone(IST)
            if not (is_finished or is_past):
                continue  # today's match for this slot hasn't happened yet

            hour, minute = (int(p) for p in slot_time.split(":")[:2])
            start_ist = datetime.combine(tomorrow, datetime.min.time(), tzinfo=IST).replace(
                hour=hour, minute=minute
            )
            start = start_ist.astimezone(timezone.utc)
            slot_number = await self.match_repo.next_match_number(tournament.id, round_number=1)
            new_match = await self.match_repo.create(
                tournament_id=tournament.id,
                round_number=1,
                match_number=slot_number,
                scheduled_start=start,
                scheduled_end=start + timedelta(minutes=30),
                team_format=team_format,
                entry_fee=tournament.entry_fee,
                prize_pool=tournament.prize_pool,
                match_status=MatchStatus.SCHEDULED,
                room_status=RoomStatus.NOT_CREATED,
                auto_disqualify_on_no_show=True,
                created_by=tournament.created_by,
            )
            created.append(new_match)
            tomorrow_slot_times.add(slot_time)

        if created:
            tournament.last_generated_on = datetime.now(timezone.utc)
            await self.session.commit()
            for match in created:
                await self.session.refresh(match)

        return created

    async def generate_for_all_active_schedules(
        self, target_date: Optional[date] = None
    ) -> dict[UUID, list[Match]]:
        """Run generation for every active recurring schedule. Intended to
        be called once a day by a cron job / scheduled task (e.g. just
        after midnight, to generate today's Free Fire and BGMI slots)."""
        # "Today" for this cron is the IST calendar date, not UTC — the
        # job is meant to run just after midnight IST, and using UTC's
        # date here would keep generating "yesterday's" slots until
        # 5:30 AM UTC.
        target_date = target_date or datetime.now(IST).date()
        schedules = await self.tournament_repo.list_active_recurring_schedules()

        results: dict[UUID, list[Match]] = {}
        for schedule in schedules:
            results[schedule.id] = await self.generate_for_day(schedule, target_date)
        return results