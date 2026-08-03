"""
Slot Join Service — user-facing "join a match slot" flow for recurring
schedules (Free Fire / BGMI style: no registration, just pick a time
slot and pay the entry fee).

Three join modes for team-format slots (Clash Squad 1v1/2v2/3v3/4v4):
- CREATE: start a new MatchTeam for this slot, share the invite code
  with friends.
- INVITE: join a friend's MatchTeam via their invite code.
- RANDOM: get paired into (or start) a MatchTeam flagged is_random=True
  — the next random-joiner for this same slot lands in the same team
  until it's full.

Solo-format slots (Free Fire Classic, BGMI Classic/Squad) skip teams
entirely and assign the user directly to the Match via a Participant
row.
"""
import enum
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.models.game_profile import UserGameProfile
from app.models.match import Match, MatchStatus
from app.models.match_participant import MatchAssignmentType, MatchCheckInStatus, MatchParticipant
from app.models.match_team import MatchTeam, MatchTeamMember, MatchTeamStatus
from app.models.participant import Participant, ParticipantPaymentStatus, ParticipantStatus, RegistrationType
from app.models.tournament import Tournament
from app.models.user import User
from app.repositories.base import BaseRepository
from app.repositories.match_participant_repository import MatchParticipantRepository
from app.repositories.match_repository import MatchRepository
from app.repositories.match_team_repository import MatchTeamRepository
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.tournament_repository import TournamentRepository
from app.services.wallet_service import WalletService

_WALLET_SLOT_ENTRY_REF_TYPE = "match_slot_entry_fee"


class SlotJoinMode(str, enum.Enum):
    CREATE = "create"
    INVITE = "invite"
    RANDOM = "random"


class SlotJoinService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.match_repo = MatchRepository(session)
        self.tournament_repo = TournamentRepository(session)
        self.participant_repo = ParticipantRepository(session)
        self.slot_repo = MatchParticipantRepository(session)
        self.match_team_repo = MatchTeamRepository(session)
        self.wallet_service = WalletService(session)

    # ------------------------------------------------------------------
    # Shared checks
    # ------------------------------------------------------------------
    async def _get_joinable_match(self, match_id: UUID) -> tuple[Match, Tournament]:
        match = await self.match_repo.get_by_id(match_id)
        if match is None:
            raise NotFoundException("Match not found")
        tournament = await self.tournament_repo.get_by_id(match.tournament_id)
        if tournament is None or not tournament.is_recurring_schedule:
            raise ValidationException("This match is not part of a joinable schedule")
        if match.match_status not in (MatchStatus.SCHEDULED, MatchStatus.ROOM_PUBLISHED):
            raise ValidationException(
                f"This slot is no longer open to join (status: {match.match_status.value})"
            )
        if match.scheduled_start and datetime.now(timezone.utc) >= match.scheduled_start:
            raise ValidationException("This slot has already started — join a later slot")
        return match, tournament

    def _entry_fee(self, match: Match, tournament: Tournament):
        return match.entry_fee if match.entry_fee is not None else tournament.entry_fee

    async def _ensure_participant(
        self, tournament: Tournament, user: User, game_profile: UserGameProfile
    ) -> Participant:
        """One lightweight Participant row per (schedule, user) — created
        lazily on first join, reused for every subsequent slot join under
        the same schedule. No registration window / capacity gate here;
        capacity is enforced per-slot by MatchParticipant, not per-schedule."""
        existing = await self.participant_repo.get_by_tournament_and_user(
            tournament.id, user.id
        )
        if existing is not None:
            if existing.status in (ParticipantStatus.CANCELLED, ParticipantStatus.REJECTED):
                existing = await self.participant_repo.update(
                    existing, status=ParticipantStatus.CONFIRMED, cancelled_at=None
                )
            return existing
        return await self.participant_repo.create(
            tournament_id=tournament.id,
            user_id=user.id,
            game_profile_id=game_profile.id,
            registration_type=RegistrationType.SOLO,
            status=ParticipantStatus.CONFIRMED,
            payment_status=ParticipantPaymentStatus.NOT_REQUIRED,
            entry_fee_paid=0,
        )

    async def _charge_slot_entry_fee(self, match: Match, user: User, fee) -> None:
        if not fee or fee <= 0:
            return
        await self.wallet_service.debit(
            user,
            amount=fee,
            reference_type=_WALLET_SLOT_ENTRY_REF_TYPE,
            reference_id=str(match.id),
            description=f"Entry fee for match slot at {match.scheduled_start}",
            commit=False,
        )

    # ==================================================================
    # Solo join (Free Fire Classic, BGMI Classic/Squad — no team format)
    # ==================================================================
    async def join_solo(
        self, match_id: UUID, current_user: User, game_profile: UserGameProfile
    ) -> MatchParticipant:
        match, tournament = await self._get_joinable_match(match_id)

        participant = await self._ensure_participant(tournament, current_user, game_profile)

        already = await self.slot_repo.get_by_match_and_participant(match.id, participant.id)
        if already is not None:
            raise ConflictException("You have already joined this slot")

        current_count = await self.slot_repo.count_for_match(match.id)
        if current_count >= tournament.max_players:
            raise ConflictException("This slot is full")

        fee = self._entry_fee(match, tournament)
        await self._charge_slot_entry_fee(match, current_user, fee)

        slot_number = await self.slot_repo.next_slot_number(match.id)
        slot = await self.slot_repo.create(
            match_id=match.id,
            participant_id=participant.id,
            slot_number=slot_number,
            assignment_type=MatchAssignmentType.REGISTERED,
            assigned_by=current_user.id,
            check_in_status=MatchCheckInStatus.NOT_OPEN,
        )
        await self.session.commit()
        await self.session.refresh(slot)
        return slot

    async def _assert_team_slot_has_room(
        self, match: Match, tournament: Tournament, team_size: int
    ) -> None:
        """A slot's total capacity (tournament.max_players, e.g. 8 for
        Clash Squad) divided by the team_format's team_size gives the max
        number of teams allowed in this slot (e.g. 8 // 4 = 2 teams for
        4v4). Raise if that cap is already reached before a new team is
        started."""
        max_teams = max(tournament.max_players // team_size, 1)
        active_teams = await self.match_team_repo.count_teams_for_match(match.id)
        if active_teams >= max_teams:
            raise ConflictException("This slot is full — no more teams can join")

    # ==================================================================
    # Team join (Free Fire Clash Squad — 1v1/2v2/3v3/4v4)
    # ==================================================================
    async def join_team(
        self,
        match_id: UUID,
        current_user: User,
        game_profile: UserGameProfile,
        *,
        mode: SlotJoinMode,
        team_name: Optional[str] = None,
        invite_code: Optional[str] = None,
    ) -> MatchTeam:
        match, tournament = await self._get_joinable_match(match_id)
        if not match.team_format or match.team_format == "solo":
            raise ValidationException("This slot does not support team formats — use join_solo")

        team_size = {"1v1": 1, "2v2": 2, "3v3": 3, "4v4": 4}.get(match.team_format)
        if team_size is None:
            raise ValidationException(f"Unrecognized team_format '{match.team_format}'")

        participant = await self._ensure_participant(tournament, current_user, game_profile)

        # A user can only be in one team for this specific slot.
        existing_slots = await self.slot_repo.list_for_match(match.id)
        for s in existing_slots:
            if s.match_team_id:
                mt = await self.match_team_repo.get_by_id(s.match_team_id)
                if mt and any(m.user_id == current_user.id for m in mt.members):
                    raise ConflictException("You have already joined this slot")

        if mode == SlotJoinMode.INVITE:
            if not invite_code:
                raise ValidationException("invite_code is required to join a friend's team")
            match_team = await self.match_team_repo.get_by_invite_code(invite_code)
            if match_team is None or match_team.match_id != match.id:
                raise NotFoundException("Invalid invite code for this slot")
            if match_team.status != MatchTeamStatus.FORMING:
                raise ConflictException("This team is no longer accepting members")
            if match_team.current_members >= match_team.team_size:
                raise ConflictException("This team is already full")

        elif mode == SlotJoinMode.RANDOM:
            match_team = await self.match_team_repo.find_open_random_team(match.id)
            if match_team is None:
                # Starting a brand-new team occupies a fresh team-slot in
                # this match — enforce the per-slot team cap before doing so.
                await self._assert_team_slot_has_room(match, tournament, team_size)
                if team_size == 1:
                    # 1v1 random has no "waiting group" — just start a team
                    # of size 1, immediately locked, and let the match get
                    # paired against the next solo random opponent's team
                    # at check-in/room-assignment time (organizer/admin
                    # flow, reuses existing assign_team/auto_assign).
                    pass
                match_team = await self.match_team_repo.create(
                    match_id=match.id,
                    team_name=None,
                    captain_id=current_user.id,
                    team_format=match.team_format,
                    team_size=team_size,
                    current_members=0,
                    is_random=True,
                    status=MatchTeamStatus.FORMING,
                )

        else:  # CREATE
            await self._assert_team_slot_has_room(match, tournament, team_size)
            match_team = await self.match_team_repo.create(
                match_id=match.id,
                team_name=team_name,
                captain_id=current_user.id,
                team_format=match.team_format,
                team_size=team_size,
                current_members=0,
                is_random=False,
                status=MatchTeamStatus.FORMING,
            )

        # Charge the entry fee once the user is actually about to occupy a
        # seat in the team (after all validation above has passed).
        fee = self._entry_fee(match, tournament)
        await self._charge_slot_entry_fee(match, current_user, fee)

        member_repo = BaseRepository(self.session, MatchTeamMember)
        await member_repo.create(match_team_id=match_team.id, user_id=current_user.id)

        new_count = match_team.current_members + 1
        team_full = new_count >= match_team.team_size
        match_team = await self.match_team_repo.update(
            match_team,
            current_members=new_count,
            status=MatchTeamStatus.LOCKED if team_full else MatchTeamStatus.FORMING,
        )

        # Occupy a slot on the Match itself once the team is complete, so
        # capacity (max 2 teams per slot) and room-publish flows work the
        # same way they do for bracket tournaments.
        if team_full:
            teams_in_slot = await self.match_team_repo.count_teams_for_match(match.id)
            slot_number = await self.slot_repo.next_slot_number(match.id)
            await self.slot_repo.create(
                match_id=match.id,
                match_team_id=match_team.id,
                slot_number=slot_number,
                assignment_type=(
                    MatchAssignmentType.RANDOM if match_team.is_random else MatchAssignmentType.REGISTERED
                ),
                assigned_by=current_user.id,
                check_in_status=MatchCheckInStatus.NOT_OPEN,
            )

        await self.session.commit()
        await self.session.refresh(match_team)
        return match_team
