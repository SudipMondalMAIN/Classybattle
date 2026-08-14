"""
Tournament service — validation, slug/status management, and orchestration
between the repository layer and Supabase-backed asset storage.
"""
from decimal import Decimal
from typing import Optional, Union
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.models.tournament import (
    TOURNAMENT_STATUS_TRANSITIONS,
    Tournament,
    TournamentStatus,
    TournamentVisibility,
)
from app.models.audit_log import AuditAction
from app.models.user import User, UserRole
from app.repositories.game_mode_repository import GameModeRepository
from app.repositories.game_repository import GameRepository, UserGameProfileRepository
from app.repositories.map_repository import MapRepository
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.tournament_repository import TournamentRepository
from app.schemas.tournament import TournamentCreate, TournamentCustomCreate, TournamentUpdate
from app.services.audit_service import AuditService
from app.services.slot_join_service import SlotJoinService
from app.storage.storage_service import StorageService
from app.utils.slug import generate_unique_suffix, slugify

# Asset upload constraints for banner/cover images.
_ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

_MANAGER_ROLES = {UserRole.ADMIN, UserRole.SUPER_ADMIN}

# Platform cut on user-created ("custom") tournaments. e.g. entry_fee=10,
# max_players=2 -> pool=20 -> prize_pool=16.50 (platform keeps 3.50).
PLATFORM_COMMISSION_RATE = Decimal("0.175")


class TournamentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TournamentRepository(session)
        self.game_repo = GameRepository(session)
        self.game_mode_repo = GameModeRepository(session)
        self.map_repo = MapRepository(session)
        self.storage = StorageService(bucket="tournament-assets")
        self.audit = AuditService(session)
        self.participant_repo = ParticipantRepository(session)
        self.game_profile_repo = UserGameProfileRepository(session)

    async def _notify_participants(
        self, tournament: Tournament, *, event_type, title: str, body: str, event_key_prefix: str
    ) -> None:
        try:
            from app.notifications.dispatch_service import NotificationDispatchService

            participants = await self.participant_repo.list_active_for_tournament_all(tournament.id)
            users = [p.user for p in participants if p.user is not None]
            if not users:
                return
            await NotificationDispatchService(self.session).dispatch_bulk(
                users=users,
                event_type=event_type,
                title=title,
                body=body,
                event_key_prefix=event_key_prefix,
                meta_data={"tournament_id": str(tournament.id)},
            )
        except Exception:  # noqa: BLE001 - notifications must never break tournament flows
            pass

    # ------------------------------------------------------------------
    # Authorization helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _is_admin(user: User) -> bool:
        return user.role in _MANAGER_ROLES

    def _assert_can_manage(self, tournament: Tournament, user: User) -> None:
        if self._is_admin(user):
            return
        if tournament.created_by is not None and tournament.created_by == user.id:
            return
        raise ForbiddenException("You do not have permission to manage this tournament")

    # ------------------------------------------------------------------
    # Slug helpers
    # ------------------------------------------------------------------
    async def _generate_unique_slug(self, title: str) -> str:
        base = slugify(title)
        candidate = base
        # A handful of attempts with random suffixes comfortably avoids
        # collisions without an unbounded loop.
        for _ in range(5):
            if not await self.repo.slug_exists(candidate):
                return candidate
            candidate = f"{base}-{generate_unique_suffix()}"
        # Extremely unlikely fallback: fully random suffix guarantees uniqueness.
        return f"{base}-{uuid4().hex[:10]}"

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------
    async def _assert_game_exists(self, game_id: UUID) -> None:
        game = await self.game_repo.get_by_id(game_id)
        if game is None or not game.is_active:
            raise NotFoundException("Game not found or inactive")

    async def _assert_mode_and_map_valid(
        self, game_id: UUID, mode_id: Optional[UUID], map_id: Optional[UUID]
    ) -> None:
        if mode_id is not None:
            mode = await self.game_mode_repo.get_by_id(mode_id)
            if mode is None or mode.game_id != game_id:
                raise ValidationException("mode_id does not belong to the selected game")
        if map_id is not None:
            map_ = await self.map_repo.get_by_id(map_id)
            if map_ is None or map_.game_id != game_id:
                raise ValidationException("map_id does not belong to the selected game")
            if mode_id is not None and map_.mode_id is not None and map_.mode_id != mode_id:
                raise ValidationException("map_id does not belong to the selected mode_id")

    @staticmethod
    def _assert_valid_status_transition(
        current: TournamentStatus, target: TournamentStatus
    ) -> None:
        if current == target:
            return
        allowed = TOURNAMENT_STATUS_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValidationException(
                f"Cannot transition tournament from '{current.value}' to '{target.value}'"
            )

    @staticmethod
    def _validate_asset(content_type: str, file_bytes: bytes) -> None:
        if content_type not in _ALLOWED_IMAGE_CONTENT_TYPES:
            raise ValidationException(
                "Unsupported file type. Allowed types: JPEG, PNG, WEBP"
            )
        if len(file_bytes) > _MAX_IMAGE_SIZE_BYTES:
            raise ValidationException("File is too large. Maximum size is 5 MB")
        if len(file_bytes) == 0:
            raise ValidationException("Uploaded file is empty")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    async def create_tournament(
        self, payload: TournamentCreate, current_user: User
    ) -> Tournament:
        await self._assert_game_exists(payload.game_id)
        await self._assert_mode_and_map_valid(payload.game_id, payload.mode_id, payload.map_id)

        if await self.repo.title_exists(payload.title, payload.game_id):
            raise ConflictException(
                "A tournament with this title already exists for this game"
            )

        slug = await self._generate_unique_slug(payload.title)

        tournament = await self.repo.create(
            title=payload.title,
            slug=slug,
            description=payload.description,
            rules=payload.rules,
            game_id=payload.game_id,
            mode_id=payload.mode_id,
            map_id=payload.map_id,
            organizer=payload.organizer,
            entry_fee=payload.entry_fee,
            prize_pool=payload.prize_pool,
            max_players=payload.max_players,
            current_players=0,
            visibility=payload.visibility,
            is_featured=payload.is_featured,
            registration_mode=payload.registration_mode,
            team_size=payload.team_size,
            max_teams=payload.max_teams,
            is_recurring_schedule=payload.is_recurring_schedule,
            daily_slot_times=payload.daily_slot_times,
            category=payload.category,
            squad_size=payload.squad_size,
            status=TournamentStatus.SCHEDULED,
            created_by=current_user.id,
        )
        await self.audit.record(
            entity="tournament",
            action=AuditAction.CREATE,
            entity_id=tournament.id,
            actor=current_user,
            new_values={
                "title": tournament.title,
                "game_id": tournament.game_id,
                "mode_id": tournament.mode_id,
                "map_id": tournament.map_id,
                "entry_fee": tournament.entry_fee,
                "prize_pool": tournament.prize_pool,
                "status": tournament.status,
            },
            description=f"Tournament '{tournament.title}' created",
        )
        await self.session.commit()

        try:
            from app.models.notification import NotificationEventType
            from app.notifications.dispatch_service import NotificationDispatchService

            await NotificationDispatchService(self.session).dispatch(
                user=current_user,
                event_type=NotificationEventType.TOURNAMENT_CREATED,
                title="Tournament created",
                body=f"Your tournament '{tournament.title}' has been created successfully.",
                event_key=f"tournament_created:{tournament.id}",
                meta_data={"tournament_id": str(tournament.id)},
            )
        except Exception:  # noqa: BLE001
            pass

        return tournament

    async def create_custom_tournament(
        self, payload: TournamentCustomCreate, current_user: User
    ) -> Tournament:
        """User-facing "Custom Tournament" creation flow (the box on the
        home screen). Any verified user can host one -- no admin approval,
        goes straight to SCHEDULED/PUBLIC and is instantly joinable, same
        as an admin-created tournament. prize_pool is always computed
        server-side from entry_fee * max_players, never accepted from the
        client, so a host cannot fake an inflated payout.

        The host is auto-joined into their own tournament (solo mode only
        -- squad/team custom tournaments still require the host to join
        explicitly and invite/organize their team afterward). This debits
        the host's wallet for the entry fee exactly like any other player,
        so require a saved game profile *before* creating the tournament
        row, to avoid creating an orphan tournament nobody is in.
        """
        await self._assert_game_exists(payload.game_id)
        await self._assert_mode_and_map_valid(payload.game_id, payload.mode_id, payload.map_id)

        auto_join = payload.registration_mode == TeamRegistrationMode.SOLO
        game_profile = None
        if auto_join:
            game_profile = await self.game_profile_repo.get_by_user_and_game(
                current_user.id, payload.game_id
            )
            if game_profile is None:
                raise ValidationException(
                    "GAME_PROFILE_REQUIRED: Save your in-game nickname + UID for this "
                    "game first (POST /games/profiles), then create the tournament again."
                )

        total_pool = payload.entry_fee * payload.max_players
        prize_pool = (total_pool * (Decimal("1") - PLATFORM_COMMISSION_RATE)).quantize(
            Decimal("0.01")
        )

        create_payload = TournamentCreate(
            title=payload.title,
            description=payload.description,
            rules=payload.rules,
            game_id=payload.game_id,
            mode_id=payload.mode_id,
            map_id=payload.map_id,
            organizer=current_user.full_name,
            entry_fee=payload.entry_fee,
            prize_pool=prize_pool,
            max_players=payload.max_players,
            visibility=TournamentVisibility.PUBLIC,
            is_featured=False,
            registration_mode=payload.registration_mode,
            team_size=payload.team_size,
            max_teams=payload.max_teams,
        )
        tournament = await self.create_tournament(create_payload, current_user)

        if auto_join:
            try:
                await SlotJoinService(self.session).join_solo(
                    tournament.id, current_user, game_profile
                )
            except Exception:
                # Tournament creation itself already succeeded and was
                # committed -- surface the join failure distinctly rather
                # than rolling back a tournament other players may already
                # be able to see, but let the caller know the host still
                # needs to join manually.
                raise ValidationException(
                    "Tournament created, but auto-join failed -- please join it manually."
                )
            await self.session.refresh(tournament)

        return tournament

    async def get_by_id(self, tournament_id: UUID, include_deleted: bool = False) -> Tournament:
        tournament = await self.repo.get_by_id(tournament_id, include_deleted=include_deleted)
        if tournament is None:
            raise NotFoundException("Tournament not found")
        return tournament

    async def get_by_slug(self, slug: str) -> Tournament:
        tournament = await self.repo.get_by_slug(slug)
        if tournament is None:
            raise NotFoundException("Tournament not found")
        return tournament

    async def get_by_short_id(self, short_id: int) -> Tournament:
        tournament = await self.repo.get_by_short_id(short_id)
        if tournament is None:
            raise NotFoundException("Tournament not found")
        return tournament

    async def list_tournaments(
        self,
        *,
        page: int,
        page_size: int,
        game_id: Optional[UUID],
        status: Optional[Union[TournamentStatus, list[TournamentStatus]]],
        visibility,
        is_featured: Optional[bool],
        category=None,
        is_custom: Optional[bool] = None,
        search: Optional[str],
        sort_by: str,
        sort_order: str,
        requesting_user: Optional[User],
    ):
        include_private = requesting_user is not None and self._is_admin(requesting_user)
        items, total = await self.repo.list_paginated(
            page=page,
            page_size=page_size,
            game_id=game_id,
            status=status,
            visibility=visibility,
            is_featured=is_featured,
            category=category,
            is_custom=is_custom,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            include_private=include_private,
        )
        return items, total

    async def update_tournament(
        self, tournament_id: UUID, payload: TournamentUpdate, current_user: User
    ) -> Tournament:
        tournament = await self.get_by_id(tournament_id)
        self._assert_can_manage(tournament, current_user)

        update_data = payload.model_dump(exclude_unset=True)

        if "title" in update_data and update_data["title"] != tournament.title:
            if await self.repo.title_exists(update_data["title"], tournament.game_id):
                raise ConflictException(
                    "A tournament with this title already exists for this game"
                )
            update_data["slug"] = await self._generate_unique_slug(update_data["title"])

        if "mode_id" in update_data or "map_id" in update_data:
            new_mode_id = update_data.get("mode_id", tournament.mode_id)
            new_map_id = update_data.get("map_id", tournament.map_id)
            await self._assert_mode_and_map_valid(tournament.game_id, new_mode_id, new_map_id)

        if "max_players" in update_data or "max_teams" in update_data:
            new_max_players = update_data.get("max_players", tournament.max_players)
            new_max_teams = update_data.get("max_teams", tournament.max_teams)
            TournamentCreate._validate_capacity(
                tournament.registration_mode,
                tournament.team_size,
                new_max_players,
                new_max_teams,
            )

        old_values = {key: getattr(tournament, key) for key in update_data}
        tournament = await self.repo.update(tournament, **update_data)
        await self.audit.record(
            entity="tournament",
            action=AuditAction.UPDATE,
            entity_id=tournament.id,
            actor=current_user,
            old_values=old_values,
            new_values=update_data,
            description=f"Tournament '{tournament.title}' updated",
        )
        await self.session.commit()

        from app.models.notification import NotificationEventType

        await self._notify_participants(
            tournament,
            event_type=NotificationEventType.TOURNAMENT_UPDATED,
            title="Tournament updated",
            body=f"Tournament '{tournament.title}' has been updated. Please review the latest details.",
            event_key_prefix=f"tournament_updated:{tournament.id}:{tournament.updated_at.isoformat()}",
        )

        return tournament

    async def update_status(
        self, tournament_id: UUID, target_status: TournamentStatus, current_user: User
    ) -> Tournament:
        tournament = await self.get_by_id(tournament_id)
        self._assert_can_manage(tournament, current_user)

        old_status = tournament.status
        self._assert_valid_status_transition(old_status, target_status)

        tournament = await self.repo.update(tournament, status=target_status)
        await self.audit.record(
            entity="tournament",
            action=AuditAction.STATUS_CHANGE,
            entity_id=tournament.id,
            actor=current_user,
            old_values={"status": old_status},
            new_values={"status": target_status},
            description=f"Tournament '{tournament.title}' status changed",
        )
        await self.session.commit()

        if target_status == TournamentStatus.CANCELLED:
            from app.models.notification import NotificationEventType

            await self._notify_participants(
                tournament,
                event_type=NotificationEventType.TOURNAMENT_CANCELLED,
                title="Tournament cancelled",
                body=f"Tournament '{tournament.title}' has been cancelled. Any paid entry fees will be refunded.",
                event_key_prefix=f"tournament_cancelled:{tournament.id}",
            )

            # Phase 9: cancelling a tournament cancels every active
            # registration and refunds any entry fee already paid via the
            # Wallet module. Local import avoids a circular import between
            # TournamentService and ParticipantService.
            from app.services.participant_service import ParticipantService

            participant_service = ParticipantService(self.session)
            await participant_service.cancel_all_for_tournament_cancellation(
                tournament, current_user
            )

        return tournament

    # ------------------------------------------------------------------
    # Room publish / auto-complete (folded in from LiveMatch/live_match_service)
    # ------------------------------------------------------------------
    async def publish_room(
        self, tournament_id: UUID, room_id: str, room_password: str, current_user: User
    ) -> Tournament:
        """Admin sets room_id/room_password -> tournament auto-flips to LIVE
        and is stamped to auto-complete 40 minutes later."""
        from datetime import datetime, timedelta, timezone

        tournament = await self.get_by_id(tournament_id)
        self._assert_can_manage(tournament, current_user)
        self._assert_valid_status_transition(tournament.status, TournamentStatus.LIVE)

        now = datetime.now(timezone.utc)
        tournament = await self.repo.update(
            tournament,
            room_id=room_id,
            room_password=room_password,
            status=TournamentStatus.LIVE,
            published_at=now,
            auto_complete_at=now + timedelta(minutes=40),
        )
        await self.audit.record(
            entity="tournament",
            action=AuditAction.STATUS_CHANGE,
            entity_id=tournament.id,
            actor=current_user,
            new_values={"status": TournamentStatus.LIVE, "room_id": room_id},
            description=f"Room published for tournament '{tournament.title}'",
        )
        await self.session.commit()

        from app.models.notification import NotificationEventType

        await self._notify_participants(
            tournament,
            event_type=NotificationEventType.ROOM_DETAILS_PUBLISHED,
            title="Room details published",
            body=f"Room ID and password for '{tournament.title}' are now available.",
            event_key_prefix=f"tournament_room_published:{tournament.id}",
        )
        return tournament

    async def can_view_room(
        self, tournament: Tournament, current_user: Optional[User]
    ) -> bool:
        """Room credentials are only visible to registered participants or admins."""
        if current_user is None:
            return False
        if self._is_admin(current_user):
            return True
        participant = await self.participant_repo.get_by_tournament_and_user(
            tournament.id, current_user.id
        )
        return participant is not None

    async def get_room_info(self, tournament_id: UUID, current_user: User) -> Tournament:
        """Only participants (or admins) may view room credentials."""
        tournament = await self.get_by_id(tournament_id)
        if not self._is_admin(current_user):
            participant = await self.participant_repo.get_by_tournament_and_user(
                tournament_id, current_user.id
            )
            if participant is None:
                raise ForbiddenException("You are not registered for this tournament")
        return tournament

    async def auto_complete_due_tournaments(self) -> int:
        """Scheduler tick: flips every LIVE tournament whose
        auto_complete_at has passed to COMPLETED. Returns the count
        completed."""
        due = await self.repo.list_live_past_auto_complete()
        for tournament in due:
            await self.repo.update(tournament, status=TournamentStatus.COMPLETED)
        if due:
            await self.session.commit()
        return len(due)

    async def soft_delete_tournament(self, tournament_id: UUID, current_user: User) -> None:
        tournament = await self.get_by_id(tournament_id)
        self._assert_can_manage(tournament, current_user)
        await self.repo.soft_delete(tournament)
        await self.session.commit()

    # ------------------------------------------------------------------
    # Asset uploads
    # ------------------------------------------------------------------
    async def upload_banner(
        self,
        tournament_id: UUID,
        file_bytes: bytes,
        content_type: str,
        current_user: User,
    ) -> Tournament:
        tournament = await self.get_by_id(tournament_id)
        self._assert_can_manage(tournament, current_user)
        self._validate_asset(content_type, file_bytes)

        extension = content_type.split("/")[-1]
        path = f"tournaments/{tournament.id}/banner-{uuid4().hex[:8]}.{extension}"
        url = await self.storage.upload_file(path, file_bytes, content_type)

        tournament = await self.repo.update(tournament, banner_url=url)
        await self.session.commit()
        return tournament

    async def upload_cover(
        self,
        tournament_id: UUID,
        file_bytes: bytes,
        content_type: str,
        current_user: User,
    ) -> Tournament:
        tournament = await self.get_by_id(tournament_id)
        self._assert_can_manage(tournament, current_user)
        self._validate_asset(content_type, file_bytes)

        extension = content_type.split("/")[-1]
        path = f"tournaments/{tournament.id}/cover-{uuid4().hex[:8]}.{extension}"
        url = await self.storage.upload_file(path, file_bytes, content_type)

        tournament = await self.repo.update(tournament, cover_url=url)
        await self.session.commit()
        return tournament