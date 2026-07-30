"""
Automatic Random Team Assignment — Team System (Phase 6).

For AUTO_RANDOM tournaments, players register individually as solo
participants (Phase 5 `ParticipantService.register`, no invite code, no
captain). After registration closes, an organizer/admin runs this service
to shuffle all active participants into balanced teams of the tournament's
configured `team_size`.

The algorithm is intentionally simple and reusable for any team size:
1. Collect all active (pending/confirmed) participants without a team yet.
2. Shuffle them (optionally with a deterministic seed for reproducibility/
   testing).
3. Chunk them into groups of `team_size`. Any remainder that can't fill a
   full team is left unassigned and reported back so the organizer can
   decide (merge into existing teams manually, refund, etc.) rather than
   silently creating an undersized team.
4. Create one Team + TeamMember rows per group, marking the first member as
   captain and locking the team immediately since AUTO_RANDOM teams are
   final by construction.
"""
import random
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, NotFoundException, ValidationException
from app.models.participant import Participant, ParticipantStatus
from app.models.team import Team, TeamStatus, generate_invite_code
from app.models.team_member import TeamMember, TeamMemberRole
from app.models.tournament import TeamRegistrationMode, Tournament, TournamentStatus
from app.models.user import User, UserRole
from app.repositories.team_member_repository import TeamMemberRepository
from app.repositories.team_repository import TeamRepository
from app.repositories.tournament_repository import TournamentRepository

_MANAGER_ROLES = {UserRole.ADMIN, UserRole.SUPER_ADMIN}
_ACTIVE_STATUSES = (ParticipantStatus.PENDING, ParticipantStatus.CONFIRMED)


class AutoTeamAssignmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.team_repo = TeamRepository(session)
        self.member_repo = TeamMemberRepository(session)
        self.tournament_repo = TournamentRepository(session)

    @staticmethod
    def _is_admin(user: User) -> bool:
        return user.role in _MANAGER_ROLES

    def _assert_can_manage(self, tournament: Tournament, user: User) -> None:
        if self._is_admin(user):
            return
        if tournament.created_by is not None and tournament.created_by == user.id:
            return
        raise ForbiddenException("You do not have permission to manage this tournament")

    async def _unassigned_participants(self, tournament_id: UUID) -> list[Participant]:
        """Active participants for this tournament who are not yet linked to
        any (non-disbanded) team's membership."""
        stmt = select(Participant).where(
            Participant.tournament_id == tournament_id,
            Participant.deleted_at.is_(None),
            Participant.status.in_(_ACTIVE_STATUSES),
        )
        result = await self.session.execute(stmt)
        all_active = list(result.scalars().all())

        assigned_stmt = (
            select(TeamMember.user_id)
            .join(Team, Team.id == TeamMember.team_id)
            .where(
                Team.tournament_id == tournament_id,
                Team.deleted_at.is_(None),
                Team.status != TeamStatus.DISBANDED,
                TeamMember.deleted_at.is_(None),
            )
        )
        assigned_result = await self.session.execute(assigned_stmt)
        assigned_user_ids = {row[0] for row in assigned_result.all()}

        return [p for p in all_active if p.user_id not in assigned_user_ids]

    async def _generate_unique_invite_code(self) -> str:
        for _ in range(10):
            candidate = generate_invite_code()
            if not await self.team_repo.invite_code_exists(candidate):
                return candidate
        # Astronomically unlikely with an 8-char, 32-symbol alphabet, but
        # guarantee termination regardless.
        return generate_invite_code()

    async def assign_teams(
        self,
        tournament_id: UUID,
        current_user: User,
        *,
        team_size: int | None = None,
        seed: int | None = None,
    ) -> dict:
        tournament = await self.tournament_repo.get_by_id(tournament_id)
        if tournament is None:
            raise NotFoundException("Tournament not found")
        self._assert_can_manage(tournament, current_user)

        if tournament.registration_mode != TeamRegistrationMode.AUTO_RANDOM:
            raise ValidationException(
                "Automatic team assignment is only available for 'auto_random' tournaments"
            )
        if tournament.status not in (
            TournamentStatus.REGISTRATION_CLOSED,
            TournamentStatus.LIVE,
        ):
            raise ValidationException(
                "Automatic team assignment can only run after registration has closed"
            )

        effective_team_size = team_size or tournament.team_size
        if effective_team_size < 1:
            raise ValidationException("team_size must be at least 1")

        candidates = await self._unassigned_participants(tournament.id)

        rng = random.Random(seed) if seed is not None else random.Random()
        rng.shuffle(candidates)

        teams_created: list[Team] = []
        full_groups = len(candidates) // effective_team_size
        assigned_count = full_groups * effective_team_size
        unassigned_count = len(candidates) - assigned_count

        for i in range(full_groups):
            group = candidates[i * effective_team_size : (i + 1) * effective_team_size]
            invite_code = await self._generate_unique_invite_code()
            team = await self.team_repo.create(
                tournament_id=tournament.id,
                team_name=f"Auto Team {i + 1}",
                captain_id=group[0].user_id,
                invite_code=invite_code,
                team_size=effective_team_size,
                current_members=len(group),
                status=TeamStatus.LOCKED,
                is_locked=True,
            )
            for idx, participant in enumerate(group):
                role = TeamMemberRole.CAPTAIN if idx == 0 else TeamMemberRole.MEMBER
                await self.member_repo.create(
                    team_id=team.id,
                    user_id=participant.user_id,
                    participant_id=participant.id,
                    role=role,
                )
            teams_created.append(team)

        await self.session.commit()
        for team in teams_created:
            await self.session.refresh(team)

        return {
            "teams_created": len(teams_created),
            "players_assigned": assigned_count,
            "unassigned_players": unassigned_count,
            "teams": teams_created,
        }

    async def manual_assign(
        self,
        tournament_id: UUID,
        assignments: dict[str, list[UUID]],
        current_user: User,
    ) -> list[Team]:
        """Organizer-driven manual override: explicit ``{team_name: [user_id, ...]}``
        groupings, used when the balanced shuffle needs a human correction
        (e.g. placing friends together, handling the leftover remainder)."""
        tournament = await self.tournament_repo.get_by_id(tournament_id)
        if tournament is None:
            raise NotFoundException("Tournament not found")
        self._assert_can_manage(tournament, current_user)

        candidates = {p.user_id: p for p in await self._unassigned_participants(tournament.id)}

        teams: list[Team] = []
        for team_name, user_ids in assignments.items():
            group = []
            for uid in user_ids:
                participant = candidates.get(uid)
                if participant is None:
                    raise ValidationException(
                        f"User {uid} is not an unassigned active participant in this tournament"
                    )
                group.append(participant)

            invite_code = await self._generate_unique_invite_code()
            team = await self.team_repo.create(
                tournament_id=tournament.id,
                team_name=team_name,
                captain_id=group[0].user_id if group else None,
                invite_code=invite_code,
                team_size=tournament.team_size,
                current_members=len(group),
                status=TeamStatus.LOCKED if len(group) >= tournament.team_size else TeamStatus.FORMING,
                is_locked=len(group) >= tournament.team_size,
            )
            for idx, participant in enumerate(group):
                role = TeamMemberRole.CAPTAIN if idx == 0 else TeamMemberRole.MEMBER
                await self.member_repo.create(
                    team_id=team.id,
                    user_id=participant.user_id,
                    participant_id=participant.id,
                    role=role,
                )
            teams.append(team)

        await self.session.commit()
        for team in teams:
            await self.session.refresh(team)
        return teams
