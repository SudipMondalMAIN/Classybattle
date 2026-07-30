"""
Participant service — Tournament Registration & Participants (Phase 5).

Orchestrates registration validation, capacity management, status
transitions, and authorization between the repository layer and the
Tournament module.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.models.game_profile import UserGameProfile
from app.models.participant import (
    PARTICIPANT_STATUS_TRANSITIONS,
    Participant,
    ParticipantPaymentStatus,
    ParticipantStatus,
    RegistrationType,
)
from app.models.tournament import Tournament, TournamentStatus
from app.models.user import User, UserRole
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.tournament_repository import TournamentRepository
from app.schemas.participant import ParticipantRegister

_MANAGER_ROLES = {UserRole.ADMIN, UserRole.SUPER_ADMIN}

# Statuses that still "occupy" a capacity slot.
_ACTIVE_STATUSES = {
    ParticipantStatus.PENDING,
    ParticipantStatus.CONFIRMED,
    ParticipantStatus.CHECKED_IN,
}

# Statuses a participant may reach entirely on their own (self-service),
# as opposed to organizer/admin-only transitions (e.g. CONFIRMED, REJECTED).
_SELF_SERVICE_TARGETS = {ParticipantStatus.CANCELLED}


class ParticipantService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ParticipantRepository(session)
        self.tournament_repo = TournamentRepository(session)

    # ------------------------------------------------------------------
    # Authorization helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _is_admin(user: User) -> bool:
        return user.role in _MANAGER_ROLES

    def _is_organizer(self, tournament: Tournament, user: User) -> bool:
        return tournament.created_by is not None and tournament.created_by == user.id

    def _assert_can_manage_tournament(self, tournament: Tournament, user: User) -> None:
        if self._is_admin(user) or self._is_organizer(tournament, user):
            return
        raise ForbiddenException(
            "You do not have permission to manage participants for this tournament"
        )

    def _assert_can_view_participant(
        self, tournament: Tournament, participant: Participant, user: User
    ) -> None:
        if self._is_admin(user) or self._is_organizer(tournament, user):
            return
        if participant.user_id == user.id:
            return
        raise ForbiddenException("You do not have permission to view this participant")

    # ------------------------------------------------------------------
    # Fetch helpers
    # ------------------------------------------------------------------
    async def _get_tournament(self, tournament_id: UUID) -> Tournament:
        tournament = await self.tournament_repo.get_by_id(tournament_id)
        if tournament is None:
            raise NotFoundException("Tournament not found")
        return tournament

    async def get_participant(self, participant_id: UUID) -> Participant:
        participant = await self.repo.get_by_id(participant_id)
        if participant is None:
            raise NotFoundException("Participant not found")
        return participant

    async def get_participant_authorized(
        self, participant_id: UUID, current_user: User
    ) -> Participant:
        participant = await self.get_participant(participant_id)
        tournament = await self._get_tournament(participant.tournament_id)
        self._assert_can_view_participant(tournament, participant, current_user)
        return participant

    # ------------------------------------------------------------------
    # Registration validation
    # ------------------------------------------------------------------
    async def _validate_game_profile(
        self, game_profile_id: UUID, tournament: Tournament, user: User
    ) -> UserGameProfile:
        stmt = select(UserGameProfile).where(
            UserGameProfile.id == game_profile_id,
            UserGameProfile.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        game_profile = result.scalar_one_or_none()

        if game_profile is None:
            raise NotFoundException("Game profile not found")
        if game_profile.user_id != user.id:
            raise ForbiddenException("This game profile does not belong to you")
        if game_profile.game_id != tournament.game_id:
            raise ValidationException(
                "The selected game profile does not match this tournament's game"
            )
        return game_profile

    def _assert_registration_open(self, tournament: Tournament) -> None:
        if tournament.deleted_at is not None:
            raise NotFoundException("Tournament not found")

        if tournament.status != TournamentStatus.REGISTRATION_OPEN:
            raise ValidationException(
                f"Registration is not open for this tournament "
                f"(current status: '{tournament.status.value}')"
            )

        now = datetime.now(timezone.utc)
        if now < tournament.registration_start:
            raise ValidationException("Registration has not started yet")
        if now > tournament.registration_end:
            raise ValidationException("Registration window has closed")

    async def _assert_capacity_available(self, tournament: Tournament) -> None:
        active_count = await self.repo.count_active_for_tournament(tournament.id)
        if active_count >= tournament.max_players:
            raise ConflictException("Tournament has reached maximum participant capacity")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    async def register(
        self, tournament_id: UUID, payload: ParticipantRegister, current_user: User
    ) -> Participant:
        if current_user.deleted_at is not None or not current_user.is_active:
            raise ValidationException("Your account is not eligible to register")

        tournament = await self._get_tournament(tournament_id)
        self._assert_registration_open(tournament)

        existing = await self.repo.get_by_tournament_and_user(tournament_id, current_user.id)
        if existing is not None and existing.status in _ACTIVE_STATUSES:
            raise ConflictException("You are already registered for this tournament")

        if (
            payload.registration_type in (RegistrationType.DUO, RegistrationType.SQUAD, RegistrationType.TEAM)
            and not payload.team_name
        ):
            raise ValidationException("team_name is required for team-based registrations")

        game_profile = await self._validate_game_profile(
            payload.game_profile_id, tournament, current_user
        )

        await self._assert_capacity_available(tournament)

        payment_status = (
            ParticipantPaymentStatus.PENDING
            if tournament.entry_fee and tournament.entry_fee > 0
            else ParticipantPaymentStatus.NOT_REQUIRED
        )

        if existing is not None:
            # Re-registering after a prior cancellation/rejection re-activates
            # the same row instead of creating a duplicate.
            participant = await self.repo.update(
                existing,
                game_profile_id=game_profile.id,
                registration_type=payload.registration_type,
                team_name=payload.team_name,
                status=ParticipantStatus.PENDING,
                payment_status=payment_status,
                payment_reference=None,
                entry_fee_paid=0,
                cancelled_at=None,
                checked_in_at=None,
                joined_at=datetime.now(timezone.utc),
            )
        else:
            participant = await self.repo.create(
                tournament_id=tournament.id,
                user_id=current_user.id,
                game_profile_id=game_profile.id,
                registration_type=payload.registration_type,
                team_name=payload.team_name,
                status=ParticipantStatus.PENDING,
                payment_status=payment_status,
                entry_fee_paid=0,
            )

        await self._sync_capacity(tournament)
        await self.session.commit()
        await self.session.refresh(participant)
        return participant

    # ------------------------------------------------------------------
    # Cancel / Leave
    # ------------------------------------------------------------------
    async def cancel_registration(
        self, tournament_id: UUID, current_user: User
    ) -> Participant:
        tournament = await self._get_tournament(tournament_id)
        participant = await self.repo.get_by_tournament_and_user(
            tournament_id, current_user.id
        )
        if participant is None:
            raise NotFoundException("You are not registered for this tournament")

        return await self._cancel(tournament, participant)

    async def leave_tournament(self, participant_id: UUID, current_user: User) -> Participant:
        """Alias flow for a participant leaving via their participant record."""
        participant = await self.get_participant(participant_id)
        if participant.user_id != current_user.id and not self._is_admin(current_user):
            raise ForbiddenException("You can only leave your own registration")

        tournament = await self._get_tournament(participant.tournament_id)
        return await self._cancel(tournament, participant)

    async def _cancel(self, tournament: Tournament, participant: Participant) -> Participant:
        self._assert_valid_transition(participant.status, ParticipantStatus.CANCELLED)

        if tournament.status in (TournamentStatus.LIVE, TournamentStatus.COMPLETED):
            raise ValidationException(
                "Cannot cancel a registration once the tournament is live or completed"
            )

        was_active = participant.status in _ACTIVE_STATUSES
        participant = await self.repo.update(
            participant,
            status=ParticipantStatus.CANCELLED,
            cancelled_at=datetime.now(timezone.utc),
        )

        if was_active:
            await self._sync_capacity(tournament)

        await self.session.commit()
        await self.session.refresh(participant)
        return participant

    # ------------------------------------------------------------------
    # Status transitions (organizer/admin)
    # ------------------------------------------------------------------
    @staticmethod
    def _assert_valid_transition(
        current: ParticipantStatus, target: ParticipantStatus
    ) -> None:
        if current == target:
            return
        allowed = PARTICIPANT_STATUS_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValidationException(
                f"Cannot transition participant from '{current.value}' to '{target.value}'"
            )

    async def update_status(
        self,
        participant_id: UUID,
        target_status: ParticipantStatus,
        current_user: User,
    ) -> Participant:
        participant = await self.get_participant(participant_id)
        tournament = await self._get_tournament(participant.tournament_id)

        is_self = participant.user_id == current_user.id
        is_manager = self._is_admin(current_user) or self._is_organizer(
            tournament, current_user
        )

        if not is_manager:
            if not (is_self and target_status in _SELF_SERVICE_TARGETS):
                raise ForbiddenException(
                    "You do not have permission to update this participant's status"
                )

        self._assert_valid_transition(participant.status, target_status)

        if target_status == ParticipantStatus.CHECKED_IN and tournament.status not in (
            TournamentStatus.REGISTRATION_CLOSED,
            TournamentStatus.LIVE,
        ):
            raise ValidationException(
                "Participants can only be checked in once registration has closed"
            )

        was_active = participant.status in _ACTIVE_STATUSES
        will_be_active = target_status in _ACTIVE_STATUSES

        update_fields: dict = {"status": target_status}
        if target_status == ParticipantStatus.CANCELLED:
            update_fields["cancelled_at"] = datetime.now(timezone.utc)
        if target_status == ParticipantStatus.CHECKED_IN:
            update_fields["checked_in_at"] = datetime.now(timezone.utc)

        participant = await self.repo.update(participant, **update_fields)

        if was_active != will_be_active:
            await self._sync_capacity(tournament)

        await self.session.commit()
        await self.session.refresh(participant)
        return participant

    # ------------------------------------------------------------------
    # Capacity management
    # ------------------------------------------------------------------
    async def _sync_capacity(self, tournament: Tournament) -> None:
        """Recomputes current_players from the source of truth (active
        participant rows) rather than incrementing/decrementing blindly,
        which keeps the count correct under concurrent registrations."""
        active_count = await self.repo.count_active_for_tournament(tournament.id)
        if active_count > tournament.max_players:
            raise ConflictException("Tournament has reached maximum participant capacity")
        await self.tournament_repo.update(tournament, current_players=active_count)

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------
    async def get_registration(self, tournament_id: UUID, current_user: User) -> Participant:
        participant = await self.repo.get_by_tournament_and_user(
            tournament_id, current_user.id
        )
        if participant is None:
            raise NotFoundException("You are not registered for this tournament")
        return participant

    async def registration_history(
        self,
        current_user: User,
        *,
        page: int,
        page_size: int,
        status: Optional[ParticipantStatus],
        sort_by: str,
        sort_order: str,
    ):
        return await self.repo.list_for_user(
            current_user.id,
            page=page,
            page_size=page_size,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def list_participants_public(
        self,
        tournament_id: UUID,
        *,
        page: int,
        page_size: int,
        status: Optional[ParticipantStatus],
        search: Optional[str],
        sort_by: str,
        sort_order: str,
    ):
        await self._get_tournament(tournament_id)
        return await self.repo.list_for_tournament(
            tournament_id,
            page=page,
            page_size=page_size,
            status=status,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def list_participants_organizer(
        self,
        tournament_id: UUID,
        current_user: User,
        *,
        page: int,
        page_size: int,
        status: Optional[ParticipantStatus],
        search: Optional[str],
        sort_by: str,
        sort_order: str,
    ):
        tournament = await self._get_tournament(tournament_id)
        self._assert_can_manage_tournament(tournament, current_user)
        return await self.repo.list_for_tournament(
            tournament_id,
            page=page,
            page_size=page_size,
            status=status,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )
