"""
Schedule Service — admin management of the simplified daily match
config: pick a Game + category (SOLO/SQUAD), set entry fee, prize pool,
per-slot capacity and a list of match times. SlotGeneratorService turns
this into actual join-able Match rows every day.

A schedule is a `Tournament` row with `is_recurring_schedule=True`.
Legacy bracket-only columns (title, registration window, tournament
window, visibility, status) still exist on the model for backward
compatibility but are filled with harmless defaults here — the
simplified flow never surfaces them to Admin.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.models.match import Match
from app.models.tournament import ScheduleCategory, Tournament, TournamentStatus, TournamentVisibility
from app.models.user import User
from app.repositories.game_repository import GameRepository
from app.repositories.tournament_repository import TournamentRepository
from app.schemas.schedule import ScheduleCreate, ScheduleUpdate
from app.services.slot_generator_service import SlotGeneratorService
from app.utils.slug import slugify


class ScheduleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TournamentRepository(session)
        self.game_repo = GameRepository(session)
        self.slot_generator = SlotGeneratorService(session)

    async def _assert_game_exists(self, game_id: UUID):
        game = await self.game_repo.get_by_id(game_id)
        if game is None:
            raise ValidationException("game_id does not refer to an existing game")
        return game

    async def create_schedule(
        self, payload: ScheduleCreate, current_user: User
    ) -> Tournament:
        game = await self._assert_game_exists(payload.game_id)

        existing = await self.repo.get_active_schedule_for_game_category(
            payload.game_id, payload.category
        )
        if existing is not None:
            raise ConflictException(
                f"A {payload.category.value} schedule already exists for this game — "
                "edit it instead of creating a duplicate."
            )

        base_slug = slugify(f"{game.name}-{payload.category.value}")
        slug = base_slug
        suffix = 1
        while await self.repo.slug_exists(slug):
            suffix += 1
            slug = f"{base_slug}-{suffix}"

        now = datetime.now(timezone.utc)
        far_future = now + timedelta(days=3650)

        tournament = await self.repo.create(
            # Legacy bracket-only fields — meaningless here, wide/harmless defaults.
            title=f"{game.name} — {payload.category.value.title()}",
            slug=slug,
            organizer="System",
            current_players=0,
            registration_start=now,
            registration_end=far_future,
            tournament_start=now,
            tournament_end=far_future,
            visibility=TournamentVisibility.PUBLIC,
            status=TournamentStatus.PUBLISHED,
            is_recurring_schedule=True,
            # Real config Admin actually sets:
            game_id=payload.game_id,
            category=payload.category,
            squad_size=payload.squad_size,
            entry_fee=payload.entry_fee,
            prize_pool=payload.prize_pool,
            max_players=payload.max_players_per_slot,
            daily_slot_times=sorted(set(payload.daily_slot_times)),
            created_by=current_user.id,
        )
        await self.session.commit()
        await self.session.refresh(tournament)
        return tournament

    async def update_schedule(
        self, schedule_id: UUID, payload: ScheduleUpdate, current_user: User
    ) -> Tournament:
        schedule = await self._get_schedule(schedule_id)
        update_data = payload.model_dump(exclude_unset=True)
        if "daily_slot_times" in update_data and update_data["daily_slot_times"] is not None:
            update_data["daily_slot_times"] = sorted(set(update_data["daily_slot_times"]))
        schedule = await self.repo.update(schedule, **update_data)
        await self.session.commit()
        await self.session.refresh(schedule)
        return schedule

    async def _get_schedule(self, schedule_id: UUID) -> Tournament:
        schedule = await self.repo.get_by_id(schedule_id)
        if schedule is None or not schedule.is_recurring_schedule:
            raise NotFoundException("Schedule not found")
        return schedule

    async def get_schedule(self, schedule_id: UUID) -> Tournament:
        return await self._get_schedule(schedule_id)

    async def list_schedules(
        self, *, game_id: Optional[UUID] = None, active_only: bool = True
    ) -> Sequence[Tournament]:
        if active_only:
            schedules = await self.repo.list_active_recurring_schedules()
        else:
            items, _ = await self.repo.list_paginated(page=1, page_size=200)
            schedules = [t for t in items if t.is_recurring_schedule]
        if game_id is not None:
            schedules = [s for s in schedules if s.game_id == game_id]
        return schedules

    async def generate_slots(
        self, schedule_id: UUID, target_date: Optional[date] = None
    ) -> list[Match]:
        schedule = await self._get_schedule(schedule_id)
        target_date = target_date or datetime.now(timezone.utc).date()
        return await self.slot_generator.generate_for_day(schedule, target_date)

    async def generate_all_today(self) -> dict:
        """Meant to be hit by a daily cron shortly after midnight — generates
        today's matches for every active game schedule in one call."""
        return await self.slot_generator.generate_for_all_active_schedules()

    async def list_slots_for_day(
        self, schedule_id: UUID, target_date: Optional[date] = None
    ) -> Sequence[Match]:
        schedule = await self._get_schedule(schedule_id)
        target_date = target_date or datetime.now(timezone.utc).date()
        from app.repositories.match_repository import MatchRepository

        return await MatchRepository(self.session).list_for_tournament_on_date(
            schedule.id, target_date
        )
