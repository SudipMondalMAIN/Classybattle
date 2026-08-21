"""
Schedule Service -- admin management of the simplified daily tournament
config: pick a Game + category (SOLO/SQUAD), set entry fee, prize pool,
per-slot capacity and a list of slot times. SlotGeneratorService turns
this into actual join-able `Tournament` slot rows every day.

A schedule is a `Tournament` row with `is_recurring_schedule=True`. The
template row itself is never joined directly -- it just holds config.
"""
from datetime import date, datetime
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.models.tournament import (
    ScheduleCategory,
    TeamRegistrationMode,
    Tournament,
    TournamentStatus,
    TournamentVisibility,
)
from app.models.user import User
from app.repositories.game_repository import GameRepository
from app.repositories.tournament_repository import TournamentRepository
from app.schemas.schedule import ScheduleCreate, ScheduleUpdate
from app.services.slot_generator_service import IST, SlotGeneratorService
from app.utils.slug import slugify

# Fixed rules text applied to every schedule automatically -- Admin never
# types this in. Only the "Game Mode" line changes, based on the
# schedule's category (Squad / Solo), so every generated slot under this
# schedule inherits the correct rules with no manual per-schedule setup.
_RULES_TEMPLATE = """1. GENERAL RULES
\u2022 Eligibility: Players must use official Free Fire Max accounts (Level 35+).
\u2022 Profile Data: Game ID (UID) and In-Game Name (IGN) must match registration details.
\u2022 Roster Lock: No player changes are allowed after registration closes.

2. MATCH SETTINGS
\u2022 Game Mode: {mode}.
\u2022 Gun Skins: Gun attributes/extra powers will be turned ON.
\u2022 Room Details: Room ID and Password will be shared 10 minutes before the match.

3. FAIR PLAY & BANS
\u2022 Zero Tolerance: Use of hacks, scripts, or glitches will result in a permanent ban.
\u2022 No Teaming: Teaming up with enemies will lead to instant disqualification.
\u2022 Technical Issues: No rematch for personal internet issues or device crashes."""


def _build_rules(category: ScheduleCategory) -> str:
    return _RULES_TEMPLATE.format(mode=category.value.title())


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

    @staticmethod
    def _registration_mode_for_category(
        category: ScheduleCategory, squad_size: int
    ) -> tuple[TeamRegistrationMode, int]:
        """SQUAD schedules must generate tournaments where players are
        auto-grouped into fixed-size squads -- never left as
        registration_mode=SOLO (the Tournament model's default), which
        would silently show every generated match as solo-mode while the
        title/icon still say Squad. SOLO schedules stay solo, team_size=1.
        """
        if category == ScheduleCategory.SQUAD:
            return TeamRegistrationMode.AUTO_RANDOM, squad_size
        return TeamRegistrationMode.SOLO, 1

    async def create_schedule(
        self, payload: ScheduleCreate, current_user: User
    ) -> Tournament:
        game = await self._assert_game_exists(payload.game_id)

        existing = await self.repo.get_active_schedule_for_game_category(
            payload.game_id, payload.category
        )
        if existing is not None:
            raise ConflictException(
                f"A {payload.category.value} schedule already exists for this game -- "
                "edit it instead of creating a duplicate."
            )

        base_slug = slugify(f"{game.name}-{payload.category.value}")
        slug = base_slug
        suffix = 1
        while await self.repo.slug_exists(slug):
            suffix += 1
            slug = f"{base_slug}-{suffix}"

        registration_mode, team_size = self._registration_mode_for_category(
            payload.category, payload.squad_size
        )

        tournament = await self.repo.create(
            # Template row -- never joined directly, so status/visibility
            # here are just harmless defaults.
            title=f"{game.name} - {payload.category.value.title()}",
            # Auto-filled, fixed rules -- Admin doesn't add these manually;
            # every generated slot inherits this via template.rules.
            rules=_build_rules(payload.category),
            slug=slug,
            organizer="System",
            current_players=0,
            visibility=TournamentVisibility.PUBLIC,
            status=TournamentStatus.SCHEDULED,
            is_recurring_schedule=True,
            # Real config Admin actually sets:
            game_id=payload.game_id,
            category=payload.category,
            squad_size=payload.squad_size,
            entry_fee=payload.entry_fee,
            prize_pool=payload.prize_pool,
            max_players=payload.max_players_per_slot,
            banner_url=payload.banner_url,
            cover_url=payload.cover_url,
            daily_slot_times=sorted(set(payload.daily_slot_times)),
            prize_type=payload.prize_type,
            rank_prize_rules=(
                [r.model_dump(mode="json") for r in payload.rank_prize_rules]
                if payload.rank_prize_rules
                else None
            ),
            per_kill_amount=payload.per_kill_amount,
            win_amount=payload.win_amount,
            created_by=current_user.id,
            # Derived from category so generated matches never end up
            # mislabeled solo under a Squad title (see
            # _registration_mode_for_category).
            registration_mode=registration_mode,
            team_size=team_size,
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
        if "rank_prize_rules" in update_data and update_data["rank_prize_rules"] is not None:
            # JSON-mode dump so Decimal amounts store as JSONB-safe values.
            update_data["rank_prize_rules"] = [
                r.model_dump(mode="json") if hasattr(r, "model_dump") else r
                for r in payload.rank_prize_rules
            ]
        if "squad_size" in update_data and update_data["squad_size"] is not None:
            # Keep team_size in sync so future generated matches still
            # match the schedule's category/squad_size correctly.
            _, team_size = self._registration_mode_for_category(
                schedule.category, update_data["squad_size"]
            )
            update_data["team_size"] = team_size
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
            items, _ = await self.repo.list_paginated(
                page=1, page_size=200, include_schedule_templates=True
            )
            schedules = [t for t in items if t.is_recurring_schedule]
        if game_id is not None:
            schedules = [s for s in schedules if s.game_id == game_id]
        return schedules

    async def generate_slots(
        self, schedule_id: UUID, target_date: Optional[date] = None
    ) -> list[Tournament]:
        schedule = await self._get_schedule(schedule_id)
        # Must match the IST calendar date used everywhere else this is
        # generated (scheduler tick, generate_all_today) -- otherwise this
        # manual trigger disagrees with them near IST midnight and causes
        # duplicate slot generation.
        target_date = target_date or datetime.now(IST).date()
        return await self.slot_generator.generate_for_day(schedule, target_date)

    async def generate_all_today(self) -> dict:
        """Meant to be hit by a daily cron shortly after midnight -- generates
        today's slots for every active game schedule in one call."""
        return await self.slot_generator.generate_for_all_active_schedules()

    async def list_slots_for_day(
        self, schedule_id: UUID, target_date: Optional[date] = None
    ) -> Sequence[Tournament]:
        schedule = await self._get_schedule(schedule_id)
        target_date = target_date or datetime.now(IST).date()
        return await self.repo.list_generated_slots_for_template(
            schedule.slug, target_date.isoformat()
        )