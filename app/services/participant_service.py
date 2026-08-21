"""
Participant service — Tournament Registration & Entry Fee System
(Phase 5 registration core, extended in Phase 9 with Wallet-backed entry
fee processing).

Orchestrates registration validation, capacity management, status
transitions, entry-fee payment/refunds via the Wallet module (Phase 8),
and authorization between the repository layer and the Tournament module.
"""
from datetime import datetime, timedelta, timezone
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
from app.models.audit_log import AuditAction
from app.models.game_profile import UserGameProfile
from app.models.participant import (
    PARTICIPANT_STATUS_TRANSITIONS,
    Participant,
    ParticipantPaymentStatus,
    ParticipantStatus,
    RegistrationType,
)
from app.models.tournament import Tournament, TournamentStatus
from app.models.tournament_participant import TournamentAssignmentType, TournamentCheckInStatus
from app.models.user import User, UserRole
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.team_member_repository import TeamMemberRepository
from app.repositories.tournament_participant_repository import TournamentParticipantRepository
from app.repositories.tournament_repository import TournamentRepository
from app.schemas.participant import ParticipantPublicView, ParticipantRegister
from app.services.audit_service import AuditService
from app.services.wallet_service import WalletService

_MANAGER_ROLES = {UserRole.ADMIN, UserRole.SUPER_ADMIN}

# Reference type used to correlate wallet transactions with the
# participant row that caused them. Kept as module-level constants so the
# debit at registration and the refund at cancellation always agree.
_WALLET_ENTRY_FEE_REF_TYPE = "tournament_entry"
_WALLET_ENTRY_FEE_REFUND_REF_TYPE = "tournament_entry_refund"

_TEAM_REGISTRATION_TYPES = {
    RegistrationType.DUO,
    RegistrationType.SQUAD,
    RegistrationType.TEAM,
}

# Statuses that still "occupy" a capacity slot.
_ACTIVE_STATUSES = {
    ParticipantStatus.PENDING,
    ParticipantStatus.CONFIRMED,
    ParticipantStatus.CHECKED_IN,
}

# Statuses a participant may reach entirely on their own (self-service),
# as opposed to organizer/admin-only transitions (e.g. CONFIRMED, REJECTED).
_SELF_SERVICE_TARGETS = {ParticipantStatus.CANCELLED}

# Custom tournaments are user-hosted with no fixed slot time; the host
# auto-joins on creation. The host may only cancel their own join (or
# delete the tournament -- see TournamentService.cancel_custom_tournament)
# once it's clear an opponent isn't coming: after this grace period with
# still nobody else joined. This stops a host yanking the tournament out
# from under someone who joined seconds ago.
CUSTOM_HOST_CANCEL_GRACE_MINUTES = 10


class ParticipantService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ParticipantRepository(session)
        self.tournament_repo = TournamentRepository(session)
        self.team_member_repo = TeamMemberRepository(session)
        self.slot_repo = TournamentParticipantRepository(session)
        self.wallet_service = WalletService(session)
        self.audit_service = AuditService(session)

    # ------------------------------------------------------------------
    # Authorization helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _is_admin(user: User) -> bool:
        return user.role in _MANAGER_ROLES

    def _is_organizer(self, tournament: Tournament, user: User) -> bool:
        return tournament.created_by is not None and tournament.created_by == user.id

    @staticmethod
    def _assert_custom_host_cancel_allowed(tournament: Tournament) -> None:
        """Shared gate for a Custom Tournament host cancelling their own
        join or deleting the tournament: only once an opponent still
        hasn't joined after the grace period."""
        if tournament.current_players > 1:
            raise ValidationException(
                "An opponent has already joined -- you can no longer cancel or "
                "delete this tournament."
            )
        created_at = tournament.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - created_at
        if elapsed < timedelta(minutes=CUSTOM_HOST_CANCEL_GRACE_MINUTES):
            remaining = CUSTOM_HOST_CANCEL_GRACE_MINUTES - int(elapsed.total_seconds() // 60)
            raise ValidationException(
                "CUSTOM_CANCEL_TOO_EARLY: Give it a bit longer for an opponent to "
                f"join -- you can cancel or delete in about {max(remaining, 1)} more "
                "minute(s) if nobody has joined yet."
            )

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

    async def get_participant_by_short_id(self, short_id: int) -> Participant:
        participant = await self.repo.get_by_short_id(short_id)
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

        # Match-refactor: no registration window -- join is instant any
        # time the tournament is SCHEDULED (gated only by capacity, see
        # _assert_capacity_available).
        if tournament.status != TournamentStatus.SCHEDULED:
            raise ValidationException(
                f"This tournament is not open to join "
                f"(current status: '{tournament.status.value}')"
            )

    async def _assert_capacity_available(self, tournament: Tournament) -> None:
        active_count = await self.repo.count_active_for_tournament(tournament.id)
        if active_count >= tournament.max_players:
            raise ConflictException("Tournament has reached maximum participant capacity")

    async def _assert_team_eligible(
        self, tournament: Tournament, payload: ParticipantRegister, user: User
    ) -> None:
        """Validates team-based registrations.

        Squad/duo/team registrations must go through the real Team system
        (create-team / join-with-invite-code) first — a bare `team_name`
        string with no backing Team row is no longer accepted, since that
        let people "register" for a squad slot without ever forming an
        actual team (no invite code, no teammates, nothing to check in
        together).
        """
        if payload.registration_type not in _TEAM_REGISTRATION_TYPES:
            return
        if not payload.team_name:
            raise ValidationException(
                "team_name is required for team-based registrations. "
                "Create or join a team first, then register."
            )

        from app.models.team import Team, TeamStatus  # local import avoids a circular import

        stmt = select(Team).where(
            Team.tournament_id == tournament.id,
            Team.deleted_at.is_(None),
            Team.team_name == payload.team_name,
        )
        result = await self.session.execute(stmt)
        team = result.scalar_one_or_none()
        if team is None:
            raise ValidationException(
                "No team with this name exists for this tournament. "
                "Create a team or join one with an invite code first — "
                "ad-hoc team names are no longer accepted."
            )

        if team.status == TeamStatus.DISBANDED:
            raise ValidationException("This team has been disbanded and cannot register")

        membership = await self.team_member_repo.get_by_team_and_user(team.id, user.id)
        if membership is None:
            raise ForbiddenException("You are not a member of this team")

    # ------------------------------------------------------------------
    # Entry fee (Wallet integration — Phase 9)
    # ------------------------------------------------------------------
    async def _charge_entry_fee(
        self, tournament: Tournament, participant: Participant, user: User
    ) -> None:
        """Debits the tournament's entry fee from the user's wallet and
        marks the participant as paid. Raises (propagating a wallet-layer
        exception, e.g. insufficient balance) if the charge cannot be
        completed — the caller's transaction is rolled back as a whole by
        the DB-session dependency, so no partial registration is left
        behind (atomic registration + payment)."""
        txn = await self.wallet_service.debit_entry_fee(
            user,
            amount=tournament.entry_fee,
            reference_type=_WALLET_ENTRY_FEE_REF_TYPE,
            reference_id=str(participant.id),
            description=f"Entry fee for tournament '{tournament.title}'",
            commit=False,
        )
        await self.repo.update(
            participant,
            payment_status=ParticipantPaymentStatus.PAID,
            payment_reference=str(txn.id),
            entry_fee_paid=tournament.entry_fee,
        )

    async def _refund_entry_fee(
        self, tournament: Tournament, participant: Participant, *, reason: str
    ) -> None:
        """Refunds a previously-paid entry fee back to the participant's
        wallet and marks the participant record as refunded. No-op if no
        fee was ever paid (idempotent with respect to repeated cancel
        attempts on the same participant)."""
        if participant.payment_status != ParticipantPaymentStatus.PAID:
            return
        if not participant.entry_fee_paid or participant.entry_fee_paid <= 0:
            return
        if not participant.payment_reference:
            return

        from uuid import UUID as _UUID

        await self.wallet_service.refund_entry_fee(
            participant.user,
            original_transaction_id=_UUID(participant.payment_reference),
            reference_type=_WALLET_ENTRY_FEE_REFUND_REF_TYPE,
            reference_id=str(participant.id),
            description=reason,
            commit=False,
        )
        await self.repo.update(
            participant, payment_status=ParticipantPaymentStatus.REFUNDED
        )

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    async def _ensure_slot(self, tournament: Tournament, participant: Participant) -> None:
        """Make sure a TournamentParticipant "slot" row exists for this
        registration -- idempotent, safe to call on every register() call
        (including re-registration after a cancellation)."""
        existing_slot = await self.slot_repo.get_by_match_and_participant(
            tournament.id, participant.id
        )
        if existing_slot is not None:
            return
        slot_number = await self.slot_repo.next_slot_number(tournament.id)
        await self.slot_repo.create(
            tournament_id=tournament.id,
            participant_id=participant.id,
            slot_number=slot_number,
            assignment_type=TournamentAssignmentType.REGISTERED,
            check_in_status=TournamentCheckInStatus.NOT_OPEN,
        )
        await self.session.commit()

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

        await self._assert_team_eligible(tournament, payload, current_user)

        game_profile = await self._validate_game_profile(
            payload.game_profile_id, tournament, current_user
        )

        await self._assert_capacity_available(tournament)

        entry_fee_required = bool(tournament.entry_fee and tournament.entry_fee > 0)
        payment_status = (
            ParticipantPaymentStatus.PENDING
            if entry_fee_required
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

        # Entry fee payment: automatic wallet deduction, atomic with the
        # registration itself — both are flushed in this same transaction
        # and committed together below. If the debit fails (insufficient
        # balance, frozen wallet, ...) the exception propagates and the
        # DB-session dependency rolls back everything, so no participant
        # row is left half-registered / unpaid.
        if entry_fee_required:
            await self._charge_entry_fee(tournament, participant, current_user)

        await self._sync_capacity(tournament)

        await self.audit_service.record(
            entity="participant",
            action=AuditAction.CREATE,
            entity_id=participant.id,
            actor=current_user,
            new_values={
                "tournament_id": str(tournament.id),
                "registration_type": payload.registration_type.value,
                "payment_status": participant.payment_status.value,
                "entry_fee": str(tournament.entry_fee) if entry_fee_required else "0",
            },
            description=f"User registered for tournament '{tournament.title}'",
        )

        await self.session.commit()
        await self.session.refresh(participant)

        # A "slot" row is what the admin Players/Results panel, check-in and
        # room-publish flow read from -- registering here without one meant
        # players who joined via /register never showed up as joined even
        # though their Participant row (and payment) existed correctly.
        await self._ensure_slot(tournament, participant)

        try:
            from app.models.notification import NotificationEventType
            from app.notifications.dispatch_service import NotificationDispatchService

            await NotificationDispatchService(self.session).dispatch(
                user=current_user,
                event_type=NotificationEventType.REGISTRATION_SUCCESSFUL,
                title="Registration successful",
                body=f"You're registered for '{tournament.title}'. Good luck!",
                event_key=f"registration_successful:{participant.id}:{participant.joined_at.isoformat()}",
                meta_data={"tournament_id": str(tournament.id)},
            )
        except Exception:  # noqa: BLE001
            pass

        return participant
    async def cancel_registration(
        self, tournament_id: UUID, current_user: User
    ) -> Participant:
        tournament = await self._get_tournament(tournament_id)
        participant = await self.repo.get_by_tournament_and_user(
            tournament_id, current_user.id
        )
        if participant is None:
            raise NotFoundException("You are not registered for this tournament")

        return await self._cancel(tournament, participant, actor=current_user)

    async def leave_tournament(self, participant_id: UUID, current_user: User) -> Participant:
        """Alias flow for a participant leaving via their participant record."""
        participant = await self.get_participant(participant_id)
        if participant.user_id != current_user.id and not self._is_admin(current_user):
            raise ForbiddenException("You can only leave your own registration")

        tournament = await self._get_tournament(participant.tournament_id)
        return await self._cancel(tournament, participant, actor=current_user)

    async def _cancel(
        self, tournament: Tournament, participant: Participant, actor: Optional[User] = None
    ) -> Participant:
        self._assert_valid_transition(participant.status, ParticipantStatus.CANCELLED)

        if tournament.status in (TournamentStatus.LIVE, TournamentStatus.COMPLETED):
            raise ValidationException(
                "Cannot cancel a registration once the tournament is live or completed"
            )

        # Extra gate: the host of a user-hosted Custom Tournament cancelling
        # their own auto-join. Admins and non-host participants are
        # unaffected -- this only fires when the actor is the tournament's
        # creator on their own registration for a Custom Tournament
        # (category is None => custom, as opposed to admin/schedule slots).
        if (
            actor is not None
            and not self._is_admin(actor)
            and tournament.category is None
            and self._is_organizer(tournament, actor)
            and participant.user_id == actor.id
        ):
            self._assert_custom_host_cancel_allowed(tournament)

        was_active = participant.status in _ACTIVE_STATUSES
        was_paid = participant.payment_status == ParticipantPaymentStatus.PAID

        participant = await self.repo.update(
            participant,
            status=ParticipantStatus.CANCELLED,
            cancelled_at=datetime.now(timezone.utc),
        )

        if was_paid:
            await self._refund_entry_fee(
                tournament,
                participant,
                reason=f"Refund: registration cancelled for tournament '{tournament.title}'",
            )

        if was_active:
            await self._sync_capacity(tournament)

        await self.audit_service.record(
            entity="participant",
            action=AuditAction.STATUS_CHANGE,
            entity_id=participant.id,
            actor=actor,
            old_values={"status": "active"},
            new_values={"status": ParticipantStatus.CANCELLED.value, "refunded": was_paid},
            description=f"Registration cancelled for tournament '{tournament.title}'",
        )

        await self.session.commit()
        await self.session.refresh(participant)

        try:
            from app.models.notification import NotificationEventType
            from app.notifications.dispatch_service import NotificationDispatchService

            await NotificationDispatchService(self.session).dispatch(
                user=participant.user,
                event_type=NotificationEventType.REGISTRATION_CANCELLED,
                title="Registration cancelled",
                body=f"Your registration for '{tournament.title}' has been cancelled."
                + (" Your entry fee was refunded." if was_paid else ""),
                event_key=f"registration_cancelled:{participant.id}:{participant.cancelled_at.isoformat()}",
                meta_data={"tournament_id": str(tournament.id)},
            )
        except Exception:  # noqa: BLE001
            pass

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

        if target_status == ParticipantStatus.CHECKED_IN and tournament.status != TournamentStatus.LIVE:
            raise ValidationException(
                "Participants can only be checked in once the tournament is live"
            )

        was_active = participant.status in _ACTIVE_STATUSES
        will_be_active = target_status in _ACTIVE_STATUSES

        old_status = participant.status
        was_paid = participant.payment_status == ParticipantPaymentStatus.PAID
        refund_applicable = target_status in (
            ParticipantStatus.CANCELLED,
            ParticipantStatus.REJECTED,
        )

        update_fields: dict = {"status": target_status}
        if target_status == ParticipantStatus.CANCELLED:
            update_fields["cancelled_at"] = datetime.now(timezone.utc)
        if target_status == ParticipantStatus.CHECKED_IN:
            update_fields["checked_in_at"] = datetime.now(timezone.utc)

        participant = await self.repo.update(participant, **update_fields)

        refunded = False
        if refund_applicable and was_paid:
            await self._refund_entry_fee(
                tournament,
                participant,
                reason=(
                    f"Refund: registration {target_status.value} by "
                    f"{'admin' if is_manager else 'user'} for tournament '{tournament.title}'"
                ),
            )
            refunded = True

        if was_active != will_be_active:
            await self._sync_capacity(tournament)

        await self.audit_service.record(
            entity="participant",
            action=AuditAction.STATUS_CHANGE,
            entity_id=participant.id,
            actor=current_user,
            old_values={"status": old_status.value},
            new_values={"status": target_status.value, "refunded": refunded},
            description=f"Participant status changed to '{target_status.value}'",
        )

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
    # Bulk operations (Phase 9 — triggered by TournamentService)
    # ------------------------------------------------------------------
    async def cancel_all_for_tournament_cancellation(
        self, tournament: Tournament, actor: Optional[User]
    ) -> int:
        """Cancels every active participant of a tournament and refunds any
        entry fee already paid. Called by TournamentService when a
        tournament transitions to CANCELLED. Commits once at the end so the
        whole batch is one unit of work."""
        participants = await self.repo.list_active_for_tournament_all(tournament.id)

        refunded_count = 0
        for participant in participants:
            was_paid = participant.payment_status == ParticipantPaymentStatus.PAID
            await self.repo.update(
                participant,
                status=ParticipantStatus.CANCELLED,
                cancelled_at=datetime.now(timezone.utc),
            )
            if was_paid:
                await self._refund_entry_fee(
                    tournament,
                    participant,
                    reason=f"Refund: tournament '{tournament.title}' was cancelled",
                )
                refunded_count += 1

        if participants:
            await self.tournament_repo.update(tournament, current_players=0)

        await self.audit_service.record(
            entity="tournament",
            action=AuditAction.UPDATE,
            entity_id=tournament.id,
            actor=actor,
            new_values={
                "participants_cancelled": len(participants),
                "participants_refunded": refunded_count,
            },
            description=(
                f"All participants cancelled and refunded due to cancellation of "
                f"tournament '{tournament.title}'"
            ),
        )

        await self.session.commit()
        return len(participants)

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

    async def list_participants_public_view(
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
        """Like list_participants_public, but enriched with each
        participant's public user identity, in-game nickname/uid for the
        tournament's game, and — once available — their result
        (kills/rank/is_winner/winning_amount). Used by the tournament
        details screen so every participant, and everyone's result once
        the tournament completes, is visible to all viewers.
        """
        tournament = await self._get_tournament(tournament_id)
        participants, total = await self.repo.list_for_tournament(
            tournament_id,
            page=page,
            page_size=page_size,
            status=status,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        # Pull result slots (kills/rank/is_winner/winning_amount) for this
        # tournament and index by participant_id so we can attach them
        # below without N+1 queries.
        tp_repo = TournamentParticipantRepository(self.session)
        result_slots = await tp_repo.list_for_tournament(tournament_id)
        results_by_participant = {
            slot.participant_id: slot
            for slot in result_slots
            if slot.participant_id is not None
        }

        views: list[ParticipantPublicView] = []
        for p in participants:
            game_profile = p.game_profile
            data = (game_profile.data if game_profile else None) or {}
            slot = results_by_participant.get(p.id)
            views.append(
                ParticipantPublicView(
                    id=p.id,
                    participant_uid=p.participant_uid,
                    tournament_id=p.tournament_id,
                    registration_type=p.registration_type,
                    team_name=p.team_name,
                    status=p.status,
                    joined_at=p.joined_at,
                    user_id=p.user_id,
                    full_name=p.user.full_name,
                    avatar_id=p.user.avatar_id,
                    player_uid=p.user.player_uid,
                    ingame_nickname=data.get("nickname"),
                    ingame_uid=data.get("uid"),
                    kills=slot.kills if slot else None,
                    is_winner=slot.is_winner if slot else False,
                    rank=slot.rank if slot else None,
                    winning_amount=slot.winning_amount if slot else None,
                )
            )
        return views, total

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