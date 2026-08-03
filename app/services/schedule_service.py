"""
Schedule Service — admin management of recurring match schedules
(the "which game/mode runs, when" config that SlotGeneratorService
turns into join-able Match slots).

A schedule is a `Tournament` row with `is_recurring_schedule=True`.
Bracket-only fields (registration window, tournament window,
max_players) are still present on the model but are filled with wide
defaults here since they're meaningless for a recurring schedule —
join eligibility for slot mode is governed entirely by
`daily_start_time` / `daily_end_time` / per-slot capacity instead.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.models.match import Match
from app.models.tournament import Tournament, TournamentStatus, TournamentVisibility
from app.models.user import User
from app.repositories.game_mode_repository import GameModeRepository
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
        self.mode_repo = GameModeRepository(session)
        self.slot_generator = SlotGeneratorService(session)

    async def _assert_game_and_mode_exist(self, game_id: UUID, mode_id: Optional[UUID]) -> None:
        game = await self.game_repo.get_by_id(game_id)
        if game is None:
            raise ValidationException("game_id does not refer to an existing game")
        if mode_id is not None:
            mode = await self.mode_repo.get_by_id(mode_id)
            if mode is None or mode.game_id != game_id:
                raise ValidationException("mode_id does not belong to the given game")

    async def create_schedule(
        self, payload: ScheduleCreate, current_user: User
    ) -> Tournament:
        await self._assert_game_and_mode_exist(payload.game_id, payload.mode_id)
        if payload.daily_end_time <= payload.daily_start_time:
            raise ValidationException("daily_end_time must be after daily_start_time")

        base_slug = slugify(payload.title)
        slug = base_slug
        suffix = 1
        while await self.repo.slug_exists(slug):
            suffix += 1
            slug = f"{base_slug}-{suffix}"

        now = datetime.now(timezone.utc)
        far_future = now + timedelta(days=3650)

        tournament = await self.repo.create(
            title=payload.title,
            slug=slug,
            description=payload.description,
            game_id=payload.game_id,
            mode_id=payload.mode_id,
            organizer=payload.organizer,
            entry_fee=payload.entry_fee,
            prize_pool=0,
            # Bracket-only fields: not meaningful for a recurring schedule,
            # filled wide so the NOT NULL / check constraints are satisfied.
            max_players=payload.max_players_per_slot,
            current_players=0,
            registration_start=now,
            registration_end=far_future,
            tournament_start=now,
            tournament_end=far_future,
            visibility=TournamentVisibility.PUBLIC,
            status=TournamentStatus.PUBLISHED,
            is_recurring_schedule=True,
            daily_start_time=payload.daily_start_time,
            daily_end_time=payload.daily_end_time,
            slot_interval_minutes=payload.slot_interval_minutes,
            allowed_team_formats=payload.allowed_team_formats,
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

    async def list_schedules(self, *, active_only: bool = True) -> Sequence[Tournament]:
        if active_only:
            return await self.repo.list_active_recurring_schedules()
        items, _ = await self.repo.list_paginated(page=1, page_size=200)
        return [t for t in items if t.is_recurring_schedule]

    async def generate_slots(
        self, schedule_id: UUID, target_date: Optional[date] = None
    ) -> list[Match]:
        schedule = await self._get_schedule(schedule_id)
        target_date = target_date or datetime.now(timezone.utc).date()
        return await self.slot_generator.generate_for_day(schedule, target_date)

    async def list_slots_for_day(
        self, schedule_id: UUID, target_date: Optional[date] = None
    ) -> Sequence[Match]:
        schedule = await self._get_schedule(schedule_id)
        target_date = target_date or datetime.now(timezone.utc).date()
        from app.repositories.match_repository import MatchRepository

        return await MatchRepository(self.session).list_for_tournament_on_date(
            schedule.id, target_date
        )
