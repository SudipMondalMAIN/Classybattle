"""
Team service — Team System & Invite Management (Phase 6).

Orchestrates team creation, invite-code based joining, membership
management, captain transfer, locking, and organizer-level moderation
between the repository layer and the Tournament / Participant modules.

Design notes
------------
- Works for any team size (Solo=1, Duo=2, Trio=3, Squad=4, 5v5, 6v6, ...)
  driven entirely by ``Tournament.team_size`` / ``Tournament.registration_mode``.
- A Team's ``current_members`` is always resynced from the source of truth
  (active TeamMember rows) rather than incremented/decremented blindly, the
  same pattern used by ParticipantService for tournament capacity.
- Joining/leaving a team also creates/cancels the underlying Participant
  record for the tournament, so existing capacity tracking, payment status,
  and check-in flows (Phase 5) keep working unmodified.
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
from app.models.participant import (
    ParticipantPaymentStatus,
    ParticipantStatus,
    RegistrationType,
)
from app.models.game_profile import UserGameProfile
from app.models.team import (
    TEAM_STATUS_TRANSITIONS,
    Team,
    TeamStatus,
    generate_invite_code,
    generate_team_name,
)
from app.models.team_member import TeamMember, TeamMemberRole
from app.models.tournament import TeamRegistrationMode, Tournament, TournamentStatus
from app.models.user import User, UserRole
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.team_member_repository import TeamMemberRepository
from app.repositories.team_repository import TeamRepository
from app.repositories.tournament_repository import TournamentRepository
from app.schemas.team import TeamCreate, TeamUpdate
from app.services.wallet_service import WalletService

_MANAGER_ROLES = {UserRole.ADMIN, UserRole.SUPER_ADMIN}
_WALLET_TEAM_ENTRY_REF_TYPE = "team_tournament_entry_fee"


class TeamService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TeamRepository(session)
        self.member_repo = TeamMemberRepository(session)
        self.tournament_repo = TournamentRepository(session)
        self.participant_repo = ParticipantRepository(session)
        self.wallet_service = WalletService(session)

    async def _charge_entry_fee(self, tournament: Tournament, user: User) -> None:
        """Debit the entry fee from the user's wallet before they're turned
        into a Participant. Mirrors SlotJoinService._charge_entry_fee so
        squad-invite / squad-random / solo all pay the same way."""
        fee = tournament.entry_fee
        if not fee or fee <= 0:
            return
        await self.wallet_service.debit(
            user,
            amount=fee,
            reference_type=_WALLET_TEAM_ENTRY_REF_TYPE,
            reference_id=str(tournament.id),
            description=f"Entry fee for '{tournament.title}'",
            commit=False,
        )

    # ------------------------------------------------------------------
    # Authorization helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _is_admin(user: User) -> bool:
        return user.role in _MANAGER_ROLES

    def _is_organizer(self, tournament: Tournament, user: User) -> bool:
        return tournament.created_by is not None and tournament.created_by == user.id

    def _assert_can_manage_tournament_teams(self, tournament: Tournament, user: User) -> None:
        if self._is_admin(user) or self._is_organizer(tournament, user):
            return
        raise ForbiddenException(
            "You do not have permission to manage teams for this tournament"
        )

    def _assert_is_captain_or_manager(
        self, tournament: Tournament, team: Team, user: User
    ) -> None:
        if self._is_admin(user) or self._is_organizer(tournament, user):
            return
        if team.captain_id == user.id:
            return
        raise ForbiddenException("Only the team captain or an organizer/admin can do this")

    # ------------------------------------------------------------------
    # Fetch helpers
    # ------------------------------------------------------------------
    async def _get_tournament(self, tournament_id: UUID) -> Tournament:
        tournament = await self.tournament_repo.get_by_id(tournament_id)
        if tournament is None:
            raise NotFoundException("Tournament not found")
        return tournament

    async def get_team(self, team_id: UUID) -> Team:
        team = await self.repo.get_by_id(team_id)
        if team is None:
            raise NotFoundException("Team not found")
        return team

    async def get_team_details(self, team_id: UUID) -> Team:
        return await self.get_team(team_id)

    async def can_view_invite_code(self, team: Team, user: Optional[User]) -> bool:
        """Only the team's own captain/members, the tournament organizer, or
        an admin may see a team's invite code — anyone else scanning the
        public teams list must not be able to read (and thus join) a team
        they weren't invited to."""
        if user is None:
            return False
        if self._is_admin(user):
            return True
        if team.captain_id == user.id:
            return True
        tournament = await self._get_tournament(team.tournament_id)
        if self._is_organizer(tournament, user):
            return True
        membership = await self.member_repo.get_by_team_and_user(team.id, user.id)
        return membership is not None

    async def get_team_by_short_id(self, short_id: int) -> Team:
        team = await self.repo.get_by_short_id(short_id)
        if team is None:
            raise NotFoundException("Team not found")
        return team

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------
    def _assert_team_mode_tournament(self, tournament: Tournament) -> None:
        if tournament.registration_mode != TeamRegistrationMode.TEAM_INVITE:
            raise ValidationException(
                "This tournament does not use invite-based team registration"
            )

    def _assert_registration_open(self, tournament: Tournament) -> None:
        if tournament.deleted_at is not None:
            raise NotFoundException("Tournament not found")
        if tournament.status != TournamentStatus.SCHEDULED:
            raise ValidationException(
                f"This tournament is not open to join "
                f"(current status: '{tournament.status.value}')"
            )

    async def _assert_max_teams_not_reached(self, tournament: Tournament) -> None:
        if tournament.max_teams is None:
            return
        active_count = await self.repo.count_active_for_tournament(tournament.id)
        if active_count >= tournament.max_teams:
            raise ConflictException("Maximum number of teams for this tournament has been reached")

    async def _generate_unique_invite_code(self) -> str:
        for _ in range(10):
            candidate = generate_invite_code()
            if not await self.repo.invite_code_exists(candidate):
                return candidate
        raise ConflictException("Could not generate a unique invite code, please retry")

    async def _resolve_team_name(
        self, tournament_id: UUID, requested_name: Optional[str]
    ) -> str:
        """Uses the requester's custom name if given (checked for uniqueness
        within the tournament); otherwise auto-generates a random, unique
        default name."""
        if requested_name and requested_name.strip():
            name = requested_name.strip()
            if await self.repo.name_exists_in_tournament(tournament_id, name):
                raise ConflictException(
                    "A team with this name already exists in this tournament"
                )
            return name

        for _ in range(10):
            candidate = generate_team_name()
            if not await self.repo.name_exists_in_tournament(tournament_id, candidate):
                return candidate
        raise ConflictException("Could not generate a unique team name, please retry")

    async def _assert_user_not_already_teamed(
        self, tournament_id: UUID, user_id: UUID
    ) -> None:
        existing = await self.member_repo.get_for_user_in_tournament(tournament_id, user_id)
        if existing is not None:
            raise ConflictException(
                "You are already a member of a team in this tournament"
            )

    # ------------------------------------------------------------------
    # Game profile resolution (needed to actually register a Participant)
    # ------------------------------------------------------------------
    async def _resolve_game_profile_id(
        self, tournament: Tournament, user: User, requested_id: Optional[UUID]
    ) -> UUID:
        """Resolves which of the user's game profiles backs this team
        membership. If the caller supplied one, it's validated (must belong
        to the user and match the tournament's game). Otherwise we fall
        back to the user's existing profile for that game, if there's
        exactly one — ambiguous/missing cases raise so the client can
        prompt the user to pick or create one."""
        if requested_id is not None:
            stmt = select(UserGameProfile).where(
                UserGameProfile.id == requested_id,
                UserGameProfile.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            profile = result.scalar_one_or_none()
            if profile is None:
                raise NotFoundException("Game profile not found")
            if profile.user_id != user.id:
                raise ForbiddenException("This game profile does not belong to you")
            if profile.game_id != tournament.game_id:
                raise ValidationException(
                    "The selected game profile does not match this tournament's game"
                )
            return profile.id

        stmt = select(UserGameProfile).where(
            UserGameProfile.user_id == user.id,
            UserGameProfile.game_id == tournament.game_id,
            UserGameProfile.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        profiles = result.scalars().all()
        if not profiles:
            raise ValidationException(
                "You need a game profile for this tournament's game before "
                "joining a team. Add one in your profile first."
            )
        if len(profiles) > 1:
            raise ValidationException(
                "You have multiple game profiles for this game — specify "
                "which one to use with game_profile_id."
            )
        return profiles[0].id

    # ------------------------------------------------------------------
    # Participant sync (keeps Phase 5 capacity/payment tracking correct)
    # ------------------------------------------------------------------
    async def _ensure_participant_for_member(
        self, tournament: Tournament, team: Team, user: User, game_profile_id: UUID
    ) -> UUID:
        """Creates (or reactivates) the Participant row backing this team
        membership so tournament capacity, payment, and check-in continue to
        work exactly as they do for solo registrations."""
        existing = await self.participant_repo.get_by_tournament_and_user(
            tournament.id, user.id
        )

        if existing is not None and existing.status not in (
            ParticipantStatus.CANCELLED,
            ParticipantStatus.REJECTED,
        ):
            raise ConflictException("You are already registered for this tournament")

        # Charge the entry fee up front — the user only becomes a
        # participant (and only then can they create/share an invite code)
        # once payment has actually gone through, same as solo registration.
        await self._charge_entry_fee(tournament, user)
        has_fee = bool(tournament.entry_fee and tournament.entry_fee > 0)
        payment_status = (
            ParticipantPaymentStatus.PAID if has_fee else ParticipantPaymentStatus.NOT_REQUIRED
        )
        entry_fee_paid = tournament.entry_fee if has_fee else 0

        if existing is not None:
            participant = await self.participant_repo.update(
                existing,
                game_profile_id=game_profile_id,
                registration_type=RegistrationType.TEAM,
                team_name=team.team_name,
                status=ParticipantStatus.CONFIRMED,
                payment_status=payment_status,
                payment_reference=None,
                entry_fee_paid=entry_fee_paid,
                cancelled_at=None,
                checked_in_at=None,
                joined_at=datetime.now(timezone.utc),
            )
        else:
            participant = await self.participant_repo.create(
                tournament_id=tournament.id,
                user_id=user.id,
                game_profile_id=game_profile_id,
                registration_type=RegistrationType.TEAM,
                team_name=team.team_name,
                status=ParticipantStatus.CONFIRMED,
                payment_status=payment_status,
                entry_fee_paid=entry_fee_paid,
            )

        active_count = await self.participant_repo.count_active_for_tournament(tournament.id)
        if active_count > tournament.max_players:
            raise ConflictException("Tournament has reached maximum participant capacity")
        await self.tournament_repo.update(tournament, current_players=active_count)
        return participant.id

    async def _release_participant_for_member(
        self, tournament: Tournament, user: User
    ) -> None:
        participant = await self.participant_repo.get_by_tournament_and_user(
            tournament.id, user.id
        )
        if participant is None or participant.status in (
            ParticipantStatus.CANCELLED,
            ParticipantStatus.REJECTED,
        ):
            return
        await self.participant_repo.update(
            participant,
            status=ParticipantStatus.CANCELLED,
            cancelled_at=datetime.now(timezone.utc),
        )
        active_count = await self.participant_repo.count_active_for_tournament(tournament.id)
        await self.tournament_repo.update(tournament, current_players=active_count)

    # ------------------------------------------------------------------
    # Team capacity / lock sync
    # ------------------------------------------------------------------
    async def _sync_team_capacity(self, team: Team) -> Team:
        member_count = await self.member_repo.count_for_team(team.id)
        update_fields: dict = {"current_members": member_count}
        if member_count >= team.team_size and team.status == TeamStatus.FORMING:
            update_fields["status"] = TeamStatus.LOCKED
            update_fields["is_locked"] = True
        team = await self.repo.update(team, **update_fields)
        return team

    # ------------------------------------------------------------------
    # Create / Update / Delete
    # ------------------------------------------------------------------
    async def create_team(
        self, tournament_id: UUID, payload: TeamCreate, current_user: User
    ) -> Team:
        tournament = await self._get_tournament(tournament_id)
        self._assert_team_mode_tournament(tournament)
        self._assert_registration_open(tournament)
        await self._assert_max_teams_not_reached(tournament)
        await self._assert_user_not_already_teamed(tournament.id, current_user.id)

        game_profile_id = await self._resolve_game_profile_id(
            tournament, current_user, payload.game_profile_id
        )

        team_name = await self._resolve_team_name(tournament.id, payload.team_name)
        invite_code = await self._generate_unique_invite_code()

        team = await self.repo.create(
            tournament_id=tournament.id,
            team_name=team_name,
            captain_id=current_user.id,
            invite_code=invite_code,
            team_size=tournament.team_size,
            current_members=0,
            status=TeamStatus.FORMING,
            is_locked=False,
        )

        participant_id = await self._ensure_participant_for_member(
            tournament, team, current_user, game_profile_id
        )
        await self.member_repo.create(
            team_id=team.id,
            user_id=current_user.id,
            participant_id=participant_id,
            role=TeamMemberRole.CAPTAIN,
        )
        team = await self._sync_team_capacity(team)

        await self.session.commit()
        await self.session.refresh(team)
        return team

    async def update_team(
        self, team_id: UUID, payload: TeamUpdate, current_user: User
    ) -> Team:
        team = await self.get_team(team_id)
        tournament = await self._get_tournament(team.tournament_id)
        self._assert_is_captain_or_manager(tournament, team, current_user)

        if team.status == TeamStatus.DISBANDED:
            raise ValidationException("Cannot update a disbanded team")

        update_data = payload.model_dump(exclude_unset=True)
        if "team_name" in update_data:
            new_name = update_data["team_name"].strip()
            if await self.repo.name_exists_in_tournament(
                team.tournament_id, new_name, exclude_team_id=team.id
            ):
                raise ConflictException(
                    "A team with this name already exists in this tournament"
                )
            update_data["team_name"] = new_name

        team = await self.repo.update(team, **update_data)
        await self.session.commit()
        await self.session.refresh(team)
        return team

    async def delete_team(self, team_id: UUID, current_user: User) -> None:
        team = await self.get_team(team_id)
        tournament = await self._get_tournament(team.tournament_id)
        self._assert_is_captain_or_manager(tournament, team, current_user)

        members = await self.member_repo.list_for_team(team.id)
        for member in members:
            await self._release_participant_for_member(tournament, member.user)
            await self.member_repo.soft_delete(member)

        await self.repo.update(team, status=TeamStatus.DISBANDED, is_locked=False)
        await self.repo.soft_delete(team)
        await self.session.commit()

    # ------------------------------------------------------------------
    # Join / Leave / Remove / Transfer
    # ------------------------------------------------------------------
    async def join_team(
        self, tournament_id: UUID, invite_code: str, current_user: User, game_profile_id: Optional[UUID] = None
    ) -> Team:
        tournament = await self._get_tournament(tournament_id)
        self._assert_team_mode_tournament(tournament)
        self._assert_registration_open(tournament)

        team = await self.repo.get_by_invite_code(invite_code.strip().upper())
        if team is None or team.tournament_id != tournament.id:
            raise NotFoundException("Invalid invite code")

        if team.status == TeamStatus.DISBANDED:
            raise ValidationException("This team no longer exists")
        if team.is_locked or team.status == TeamStatus.LOCKED:
            raise ConflictException("This team is locked and not accepting new members")

        existing_member = await self.member_repo.get_by_team_and_user(
            team.id, current_user.id
        )
        if existing_member is not None:
            raise ConflictException("You are already a member of this team")

        await self._assert_user_not_already_teamed(tournament.id, current_user.id)

        if team.current_members >= team.team_size:
            raise ConflictException("This team has reached its maximum size")

        resolved_game_profile_id = await self._resolve_game_profile_id(
            tournament, current_user, game_profile_id
        )

        participant_id = await self._ensure_participant_for_member(
            tournament, team, current_user, resolved_game_profile_id
        )
        await self.member_repo.create(
            team_id=team.id,
            user_id=current_user.id,
            participant_id=participant_id,
            role=TeamMemberRole.MEMBER,
        )
        team = await self._sync_team_capacity(team)

        await self.session.commit()
        await self.session.refresh(team)
        return team

    async def leave_team(self, team_id: UUID, current_user: User) -> Team:
        team = await self.get_team(team_id)
        tournament = await self._get_tournament(team.tournament_id)

        member = await self.member_repo.get_by_team_and_user(team.id, current_user.id)
        if member is None:
            raise NotFoundException("You are not a member of this team")

        if member.role == TeamMemberRole.CAPTAIN:
            other_members = [
                m for m in await self.member_repo.list_for_team(team.id) if m.id != member.id
            ]
            if other_members:
                raise ValidationException(
                    "Captain must transfer captaincy to another member before leaving"
                )

        if tournament.status in (TournamentStatus.LIVE, TournamentStatus.COMPLETED):
            raise ValidationException(
                "Cannot leave a team once the tournament is live or completed"
            )

        await self._release_participant_for_member(tournament, current_user)
        await self.member_repo.soft_delete(member)

        remaining = await self.member_repo.count_for_team(team.id)
        update_fields: dict = {"current_members": remaining}
        if remaining == 0:
            update_fields["status"] = TeamStatus.DISBANDED
            update_fields["captain_id"] = None
        elif member.role == TeamMemberRole.CAPTAIN:
            update_fields["captain_id"] = None
        if team.status == TeamStatus.LOCKED and remaining < team.team_size:
            update_fields["status"] = TeamStatus.FORMING
            update_fields["is_locked"] = False

        team = await self.repo.update(team, **update_fields)
        if remaining == 0:
            await self.repo.soft_delete(team)

        await self.session.commit()
        await self.session.refresh(team)
        return team

    async def remove_member(
        self, team_id: UUID, target_user_id: UUID, current_user: User
    ) -> Team:
        team = await self.get_team(team_id)
        tournament = await self._get_tournament(team.tournament_id)
        self._assert_is_captain_or_manager(tournament, team, current_user)

        if target_user_id == team.captain_id:
            raise ValidationException(
                "The captain cannot be removed directly; transfer captaincy first"
            )

        member = await self.member_repo.get_by_team_and_user(team.id, target_user_id)
        if member is None:
            raise NotFoundException("This user is not a member of this team")

        await self._release_participant_for_member_by_user_id(tournament, target_user_id)
        await self.member_repo.soft_delete(member)

        remaining = await self.member_repo.count_for_team(team.id)
        update_fields: dict = {"current_members": remaining}
        if team.status == TeamStatus.LOCKED and remaining < team.team_size:
            update_fields["status"] = TeamStatus.FORMING
            update_fields["is_locked"] = False

        team = await self.repo.update(team, **update_fields)
        await self.session.commit()
        await self.session.refresh(team)
        return team

    async def _release_participant_for_member_by_user_id(
        self, tournament: Tournament, user_id: UUID
    ) -> None:
        participant = await self.participant_repo.get_by_tournament_and_user(
            tournament.id, user_id
        )
        if participant is None or participant.status in (
            ParticipantStatus.CANCELLED,
            ParticipantStatus.REJECTED,
        ):
            return
        await self.participant_repo.update(
            participant,
            status=ParticipantStatus.CANCELLED,
            cancelled_at=datetime.now(timezone.utc),
        )
        active_count = await self.participant_repo.count_active_for_tournament(tournament.id)
        await self.tournament_repo.update(tournament, current_players=active_count)

    async def transfer_captain(
        self, team_id: UUID, new_captain_user_id: UUID, current_user: User
    ) -> Team:
        team = await self.get_team(team_id)
        tournament = await self._get_tournament(team.tournament_id)
        self._assert_is_captain_or_manager(tournament, team, current_user)

        new_captain_member = await self.member_repo.get_by_team_and_user(
            team.id, new_captain_user_id
        )
        if new_captain_member is None:
            raise ValidationException("The new captain must already be a member of this team")

        if team.captain_id is not None:
            old_captain_member = await self.member_repo.get_by_team_and_user(
                team.id, team.captain_id
            )
            if old_captain_member is not None:
                await self.member_repo.update(old_captain_member, role=TeamMemberRole.MEMBER)

        await self.member_repo.update(new_captain_member, role=TeamMemberRole.CAPTAIN)
        team = await self.repo.update(team, captain_id=new_captain_user_id)

        await self.session.commit()
        await self.session.refresh(team)
        return team

    # ------------------------------------------------------------------
    # Locking
    # ------------------------------------------------------------------
    @staticmethod
    def _assert_valid_transition(current: TeamStatus, target: TeamStatus) -> None:
        if current == target:
            return
        allowed = TEAM_STATUS_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValidationException(
                f"Cannot transition team from '{current.value}' to '{target.value}'"
            )

    async def set_lock(self, team_id: UUID, is_locked: bool, current_user: User) -> Team:
        """Manual lock/unlock — captains and organizers/admins may lock or
        unlock a team before registration closes."""
        team = await self.get_team(team_id)
        tournament = await self._get_tournament(team.tournament_id)
        self._assert_is_captain_or_manager(tournament, team, current_user)

        if tournament.status != TournamentStatus.SCHEDULED:
            raise ValidationException(
                "Teams can only be locked or unlocked before the tournament goes live"
            )

        target_status = TeamStatus.LOCKED if is_locked else TeamStatus.FORMING
        self._assert_valid_transition(team.status, target_status)

        team = await self.repo.update(team, is_locked=is_locked, status=target_status)
        await self.session.commit()
        await self.session.refresh(team)
        return team

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------
    async def list_teams_public(
        self,
        tournament_id: UUID,
        *,
        page: int,
        page_size: int,
        status: Optional[TeamStatus],
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

    async def list_teams_organizer(
        self,
        tournament_id: UUID,
        current_user: User,
        *,
        page: int,
        page_size: int,
        status: Optional[TeamStatus],
        search: Optional[str],
        sort_by: str,
        sort_order: str,
    ):
        tournament = await self._get_tournament(tournament_id)
        self._assert_can_manage_tournament_teams(tournament, current_user)
        return await self.repo.list_for_tournament(
            tournament_id,
            page=page,
            page_size=page_size,
            status=status,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            include_deleted=True,
        )

    async def list_teams_admin(
        self,
        *,
        page: int,
        page_size: int,
        status: Optional[TeamStatus],
        search: Optional[str],
        sort_by: str,
        sort_order: str,
    ):
        """Cross-tournament team listing for platform admins -- no
        tournament_id required. Caller must already be admin-gated at the
        route level (require_admin)."""
        return await self.repo.list_all(
            page=page,
            page_size=page_size,
            status=status,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            include_deleted=True,
        )

    async def get_team_members(self, team_id: UUID) -> list[TeamMember]:
        team = await self.get_team(team_id)
        return await self.member_repo.list_for_team(team.id)

    # ------------------------------------------------------------------
    # Organizer moderation
    # ------------------------------------------------------------------
    async def organizer_remove_team(self, team_id: UUID, current_user: User) -> None:
        team = await self.get_team(team_id)
        tournament = await self._get_tournament(team.tournament_id)
        self._assert_can_manage_tournament_teams(tournament, current_user)

        members = await self.member_repo.list_for_team(team.id)
        for member in members:
            await self._release_participant_for_member(tournament, member.user)
            await self.member_repo.soft_delete(member)

        await self.repo.update(team, status=TeamStatus.DISBANDED, is_locked=False)
        await self.repo.soft_delete(team)
        await self.session.commit()

    async def organizer_remove_player(
        self, tournament_id: UUID, target_user_id: UUID, current_user: User
    ) -> None:
        tournament = await self._get_tournament(tournament_id)
        self._assert_can_manage_tournament_teams(tournament, current_user)

        member = await self.member_repo.get_for_user_in_tournament(
            tournament.id, target_user_id
        )
        if member is None:
            raise NotFoundException("This player is not on a team in this tournament")

        team = await self.get_team(member.team_id)
        await self._release_participant_for_member_by_user_id(tournament, target_user_id)
        await self.member_repo.soft_delete(member)

        remaining = await self.member_repo.count_for_team(team.id)
        update_fields: dict = {"current_members": remaining}
        if target_user_id == team.captain_id:
            update_fields["captain_id"] = None
        if remaining == 0:
            update_fields["status"] = TeamStatus.DISBANDED
        elif team.status == TeamStatus.LOCKED and remaining < team.team_size:
            update_fields["status"] = TeamStatus.FORMING
            update_fields["is_locked"] = False

        team = await self.repo.update(team, **update_fields)
        if remaining == 0:
            await self.repo.soft_delete(team)

        await self.session.commit()