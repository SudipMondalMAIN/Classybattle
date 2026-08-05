"""
Slot Generator Service -- recurring tournament-schedule support.

Match-refactor: Tournament itself is now the joinable/playable unit, so
generation no longer stamps out `Match` rows under a parent Tournament --
it stamps out plain `Tournament` rows (status=SCHEDULED) directly from a
template `Tournament` row (is_recurring_schedule=True).

A generated child is linked back to its template deterministically via
its slug: `<template_slug>-<YYYY-MM-DD>-<HHMM>`. This gives idempotent,
query-able generation (via TournamentRepository.list_generated_slots_for_template)
without needing a separate parent/template foreign key column.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationException
from app.models.tournament import Tournament, TournamentStatus
from app.repositories.tournament_repository import TournamentRepository

# Admin-entered daily_slot_times / daily_start_time / daily_end_time are
# IST wall-clock times (e.g. "18:00" means 6:00 PM in India), NOT UTC.
IST = timezone(timedelta(hours=5, minutes=30))


class SlotGeneratorService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tournament_repo = TournamentRepository(session)

    @staticmethod
    def _max_players_for(template: Tournament) -> int:
        if template.category is None or template.category.value == "solo":
            return template.max_players
        # Squad-style schedule: max_players is expressed in squads, so the
        # actual player capacity is squads * squad_size.
        return template.max_players * template.squad_size

    async def generate_for_day(
        self, template: Tournament, target_date: date
    ) -> list[Tournament]:
        """Generate all slots for one schedule template, for one day.

        Safe to call repeatedly for the same (template, target_date) --
        already-generated days are skipped.
        """
        if not template.is_recurring_schedule:
            raise ValidationException(
                "This tournament is not a recurring schedule -- cannot generate slots"
            )
        if not template.daily_slot_times:
            raise ValidationException(
                "Schedule is missing daily_slot_times"
            )

        date_iso = target_date.isoformat()
        existing = await self.tournament_repo.list_generated_slots_for_template(
            template.slug, date_iso
        )
        if existing:
            # Already generated for this day -- no-op, idempotent.
            return list(existing)

        created: list[Tournament] = []
        for time_str in template.daily_slot_times:
            hour, minute = (int(p) for p in time_str.split(":")[:2])
            slug_time = f"{hour:02d}{minute:02d}"
            slug = f"{template.slug}-{date_iso}-{slug_time}"
            if await self.tournament_repo.slug_exists(slug):
                continue

            tournament = await self.tournament_repo.create(
                title=f"{template.title} - {time_str} IST",
                slug=slug,
                description=template.description,
                rules=template.rules,
                game_id=template.game_id,
                mode_id=template.mode_id,
                map_id=template.map_id,
                banner_url=template.banner_url,
                cover_url=template.cover_url,
                organizer=template.organizer,
                entry_fee=template.entry_fee,
                prize_pool=template.prize_pool,
                max_players=self._max_players_for(template),
                current_players=0,
                status=TournamentStatus.SCHEDULED,
                visibility=template.visibility,
                is_featured=False,
                registration_mode=template.registration_mode,
                team_size=template.team_size,
                max_teams=template.max_teams,
                is_recurring_schedule=False,
                category=template.category,
                squad_size=template.squad_size,
                created_by=template.created_by,
            )
            created.append(tournament)

        template.last_generated_on = datetime.now(timezone.utc)
        await self.session.commit()
        for tournament in created:
            await self.session.refresh(tournament)

        return created

    async def top_up_completed_slots_for_next_day(
        self, template: Tournament
    ) -> list[Tournament]:
        """For the simplified daily_slot_times flow: for each of today's
        (IST) generated slots that has already finished (COMPLETED /
        CANCELLED), create that same time-slot for *tomorrow* if it
        doesn't already exist."""
        if not template.is_recurring_schedule or not template.daily_slot_times:
            return []

        now_ist = datetime.now(IST)
        today = now_ist.date()
        tomorrow = today + timedelta(days=1)

        todays = await self.tournament_repo.list_generated_slots_for_template(
            template.slug, today.isoformat()
        )
        tomorrows = await self.tournament_repo.list_generated_slots_for_template(
            template.slug, tomorrow.isoformat()
        )
        tomorrow_slugs = {t.slug for t in tomorrows}

        created: list[Tournament] = []
        for time_str in template.daily_slot_times:
            hour, minute = (int(p) for p in time_str.split(":")[:2])
            slug_time = f"{hour:02d}{minute:02d}"
            todays_slug = f"{template.slug}-{today.isoformat()}-{slug_time}"
            tomorrow_slug = f"{template.slug}-{tomorrow.isoformat()}-{slug_time}"

            today_slot = next((t for t in todays if t.slug == todays_slug), None)
            if today_slot is None:
                continue  # no slot generated for this time today
            if tomorrow_slug in tomorrow_slugs:
                continue  # already generated for tomorrow

            is_finished = today_slot.status in (
                TournamentStatus.COMPLETED,
                TournamentStatus.CANCELLED,
            )
            if not is_finished:
                continue  # today's slot hasn't finished yet

            new_tournament = await self.tournament_repo.create(
                title=f"{template.title} - {time_str} IST",
                slug=tomorrow_slug,
                description=template.description,
                rules=template.rules,
                game_id=template.game_id,
                mode_id=template.mode_id,
                map_id=template.map_id,
                organizer=template.organizer,
                entry_fee=template.entry_fee,
                prize_pool=template.prize_pool,
                max_players=self._max_players_for(template),
                current_players=0,
                status=TournamentStatus.SCHEDULED,
                visibility=template.visibility,
                is_featured=False,
                registration_mode=template.registration_mode,
                team_size=template.team_size,
                max_teams=template.max_teams,
                is_recurring_schedule=False,
                category=template.category,
                squad_size=template.squad_size,
                created_by=template.created_by,
            )
            created.append(new_tournament)
            tomorrow_slugs.add(tomorrow_slug)

        if created:
            template.last_generated_on = datetime.now(timezone.utc)
            await self.session.commit()
            for tournament in created:
                await self.session.refresh(tournament)

        return created

    async def generate_for_all_active_schedules(
        self, target_date: Optional[date] = None
    ) -> dict[UUID, list[Tournament]]:
        """Run generation for every active recurring schedule template.
        Intended to be called once a day by a cron job (just after
        midnight IST)."""
        target_date = target_date or datetime.now(IST).date()
        templates = await self.tournament_repo.list_active_recurring_schedules()

        results: dict[UUID, list[Tournament]] = {}
        for template in templates:
            results[template.id] = await self.generate_for_day(template, target_date)
        return results
