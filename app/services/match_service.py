"""
Match service — Room Management & Match Lifecycle (Phase 7).

Orchestrates match scheduling, room publication, team/player assignment,
check-in and no-show handling on top of the existing Tournament / Team /
Participant modules (Phases 2, 5, 6).

Design notes
------------
- Works uniformly for Solo, Duo, Trio, Squad and future formats: a match
  "slot" (MatchParticipant) points at either a Team (team-based
  tournaments) or a Participant (solo tournaments), decided by the
  parent Tournament's ``registration_mode`` / ``team_size``.
- Room credentials (room_id/room_password) are only ever surfaced by
  ``get_match_room`` once ``room_status == PUBLISHED`` — and only to
  organizers/admins or to a caller who is part of an assigned slot.
- Status transitions for both the match and each check-in slot are
  validated against explicit transition tables (mirrors the pattern used
  by TournamentService/TeamService), never scattered ``if`` chains.
"""
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
from app.models.match import MATCH_STATUS_TRANSITIONS, Match, MatchStatus, RoomStatus
from app.models.match_participant import (
    MATCH_CHECKIN_TRANSITIONS,
    MatchAssignmentType,
    MatchCheckInStatus,
    MatchParticipant,
)
from app.models.participant import ParticipantStatus
from app.models.team import TeamStatus
from app.models.tournament import TeamRegistrationMode, Tournament
from app.models.user import User, UserRole
from app.repositories.match_participant_repository import MatchParticipantRepository
from app.repositories.match_repository import MatchRepository
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.team_repository import TeamRepository
from app.repositories.tournament_repository import TournamentRepository
from app.schemas.match import (
    MatchCreate,
    MatchResultUpdate,
    MatchSchedule,
    MatchUpdate,
    RoomCreate,
    RoomUpdate,
)

_MANAGER_ROLES = {UserRole.ADMIN, UserRole.SUPER_ADMIN}

# A match is still "editable" (schedule/room/assignment changes allowed)
# up until it goes LIVE.
_PRE_LIVE_STATUSES = {
    MatchStatus.DRAFT,
    MatchStatus.SCHEDULED,
    MatchStatus.ROOM_PUBLISHED,
    MatchStatus.CHECK_IN_OPEN,
    MatchStatus.READY,
}


class MatchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = MatchRepository(session)
        self.slot_repo = MatchParticipantRepository(session)
        self.tournament_repo = TournamentRepository(session)
        self.team_repo = TeamRepository(session)
        self.participant_repo = ParticipantRepository(session)

    # ------------------------------------------------------------------
    # Authorization helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _is_admin(user: User) -> bool:
        return user.role in _MANAGER_ROLES

    def _is_organizer(self, tournament: Tournament, user: User) -> bool:
        return tournament.created_by is not None and tournament.created_by == user.id

    def _assert_can_manage(self, tournament: Tournament, user: User) -> None:
        if self._is_admin(user) or self._is_organizer(tournament, user):
            return
        raise ForbiddenException(
            "You do not have permission to manage matches for this tournament"
        )

    # ------------------------------------------------------------------
    # Fetch helpers
    # ------------------------------------------------------------------
    async def _get_tournament(self, tournament_id: UUID) -> Tournament:
        tournament = await self.tournament_repo.get_by_id(tournament_id)
        if tournament is None:
            raise NotFoundException("Tournament not found")
        return tournament

    async def get_match(self, match_id: UUID) -> Match:
        match = await self.repo.get_by_id(match_id)
        if match is None:
            raise NotFoundException("Match not found")
        return match

    async def _get_match_and_tournament(self, match_id: UUID) -> tuple[Match, Tournament]:
        match = await self.get_match(match_id)
        tournament = await self._get_tournament(match.tournament_id)
        return match, tournament

    def _is_team_based(self, tournament: Tournament) -> bool:
        return tournament.registration_mode in (
            TeamRegistrationMode.TEAM_INVITE,
            TeamRegistrationMode.AUTO_RANDOM,
        )

    # ==================================================================
    # 1. Match CRUD
    # ==================================================================
    async def create_match(
        self, tournament_id: UUID, payload: MatchCreate, current_user: User
    ) -> Match:
        tournament = await self._get_tournament(tournament_id)
        self._assert_can_manage(tournament, current_user)

        match_number = payload.match_number
        if match_number is None:
            match_number = await self.repo.next_match_number(
                tournament.id, payload.round_number
            )
        elif await self.repo.exists_round_match_number(
            tournament.id, payload.round_number, match_number
        ):
            raise ConflictException(
                "A match with this round/match number already exists for this tournament"
            )

        match = await self.repo.create(
            tournament_id=tournament.id,
            round_number=payload.round_number,
            match_number=match_number,
            scheduled_start=payload.scheduled_start,
            scheduled_end=payload.scheduled_end,
            check_in_opens_at=payload.check_in_opens_at,
            check_in_deadline=payload.check_in_deadline,
            auto_disqualify_on_no_show=payload.auto_disqualify_on_no_show,
            notes=payload.notes,
            match_status=(
                MatchStatus.SCHEDULED if payload.scheduled_start else MatchStatus.DRAFT
            ),
            room_status=RoomStatus.NOT_CREATED,
            created_by=current_user.id,
        )
        await self.session.commit()
        await self.session.refresh(match)

        try:
            from app.models.notification import NotificationEventType
            from app.notifications.dispatch_service import NotificationDispatchService
            from app.repositories.participant_repository import ParticipantRepository

            participants = await ParticipantRepository(self.session).list_active_for_tournament_all(
                tournament.id
            )
            users = [p.user for p in participants if p.user is not None]
            if users:
                await NotificationDispatchService(self.session).dispatch_bulk(
                    users=users,
                    event_type=NotificationEventType.MATCH_CREATED,
                    title="New match scheduled",
                    body=f"Match {match.match_number} (round {match.round_number}) has been scheduled for '{tournament.title}'.",
                    event_key_prefix=f"match_created:{match.id}",
                )
        except Exception:  # noqa: BLE001
            pass

        return match

    async def update_match(
        self, match_id: UUID, payload: MatchUpdate, current_user: User
    ) -> Match:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        if match.match_status in (MatchStatus.COMPLETED, MatchStatus.CANCELLED):
            raise ValidationException("Cannot update a completed or cancelled match")

        update_data = payload.model_dump(exclude_unset=True)
        match = await self.repo.update(match, **update_data)
        await self.session.commit()
        await self.session.refresh(match)
        return match

    async def remove_match(self, match_id: UUID, current_user: User) -> None:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        if match.match_status == MatchStatus.LIVE:
            raise ValidationException("Cannot remove a match that is currently live")

        await self.repo.update(match, match_status=MatchStatus.CANCELLED)
        await self.repo.soft_delete(match)
        await self.session.commit()

    async def list_matches_public(
        self,
        tournament_id: UUID,
        *,
        page: int,
        page_size: int,
        round_number: Optional[int],
        match_status: Optional[MatchStatus],
        sort_by: str,
        sort_order: str,
    ):
        await self._get_tournament(tournament_id)
        return await self.repo.list_for_tournament(
            tournament_id,
            page=page,
            page_size=page_size,
            round_number=round_number,
            match_status=match_status,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def list_matches_organizer(
        self,
        tournament_id: UUID,
        current_user: User,
        *,
        page: int,
        page_size: int,
        round_number: Optional[int],
        match_status: Optional[MatchStatus],
        sort_by: str,
        sort_order: str,
    ):
        tournament = await self._get_tournament(tournament_id)
        self._assert_can_manage(tournament, current_user)
        return await self.repo.list_for_tournament(
            tournament_id,
            page=page,
            page_size=page_size,
            round_number=round_number,
            match_status=match_status,
            sort_by=sort_by,
            sort_order=sort_order,
            include_deleted=True,
        )

    # ==================================================================
    # 4. Match Schedule
    # ==================================================================
    @staticmethod
    def _assert_valid_match_transition(current: MatchStatus, target: MatchStatus) -> None:
        if current == target:
            return
        allowed = MATCH_STATUS_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValidationException(
                f"Cannot transition match from '{current.value}' to '{target.value}'"
            )

    async def schedule_match(
        self, match_id: UUID, payload: MatchSchedule, current_user: User
    ) -> Match:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        if match.match_status not in (MatchStatus.DRAFT, MatchStatus.SCHEDULED):
            raise ValidationException(
                "Match can only be scheduled while in 'draft' or 'scheduled' status"
            )

        target_status = MatchStatus.SCHEDULED
        self._assert_valid_match_transition(match.match_status, target_status)

        match = await self.repo.update(
            match,
            scheduled_start=payload.scheduled_start,
            scheduled_end=payload.scheduled_end,
            check_in_opens_at=payload.check_in_opens_at or match.check_in_opens_at,
            check_in_deadline=payload.check_in_deadline or match.check_in_deadline,
            match_status=target_status,
        )
        await self.session.commit()
        await self.session.refresh(match)
        return match

    async def reschedule_match(
        self, match_id: UUID, payload: MatchSchedule, current_user: User
    ) -> Match:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        if match.match_status not in (
            MatchStatus.SCHEDULED,
            MatchStatus.ROOM_PUBLISHED,
            MatchStatus.CHECK_IN_OPEN,
            MatchStatus.READY,
        ):
            raise ValidationException(
                "Match cannot be rescheduled once it is live, completed or cancelled"
            )

        match = await self.repo.update(
            match,
            scheduled_start=payload.scheduled_start,
            scheduled_end=payload.scheduled_end,
            check_in_opens_at=payload.check_in_opens_at or match.check_in_opens_at,
            check_in_deadline=payload.check_in_deadline or match.check_in_deadline,
            match_status=MatchStatus.SCHEDULED,
            room_status=RoomStatus.HIDDEN
            if match.room_status == RoomStatus.PUBLISHED
            else match.room_status,
        )
        await self.session.commit()
        await self.session.refresh(match)
        return match

    # ==================================================================
    # 5. Match Status
    # ==================================================================
    async def update_match_status(
        self, match_id: UUID, target_status: MatchStatus, current_user: User
    ) -> Match:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        self._assert_valid_match_transition(match.match_status, target_status)

        update_fields: dict = {"match_status": target_status}
        now = datetime.now(timezone.utc)

        if target_status == MatchStatus.CHECK_IN_OPEN:
            await self._open_check_in_for_slots(match.id)
        elif target_status == MatchStatus.READY:
            await self._process_no_shows(match)
        elif target_status == MatchStatus.LIVE:
            update_fields["actual_start"] = match.actual_start or now
        elif target_status == MatchStatus.COMPLETED:
            update_fields["actual_end"] = match.actual_end or now
            if match.actual_start is None:
                update_fields["actual_start"] = now

        match = await self.repo.update(match, **update_fields)
        await self.session.commit()
        await self.session.refresh(match)

        if target_status in (MatchStatus.LIVE, MatchStatus.COMPLETED):
            try:
                from app.models.notification import NotificationEventType
                from app.notifications.dispatch_service import NotificationDispatchService
                from app.repositories.participant_repository import ParticipantRepository

                event_type = (
                    NotificationEventType.MATCH_STARTED
                    if target_status == MatchStatus.LIVE
                    else NotificationEventType.MATCH_COMPLETED
                )
                title = "Match started" if target_status == MatchStatus.LIVE else "Match completed"
                body = (
                    f"Match {match.match_number} (round {match.round_number}) has started."
                    if target_status == MatchStatus.LIVE
                    else f"Match {match.match_number} (round {match.round_number}) has finished."
                )
                participants = await ParticipantRepository(
                    self.session
                ).list_active_for_tournament_all(tournament.id)
                users = [p.user for p in participants if p.user is not None]
                if users:
                    await NotificationDispatchService(self.session).dispatch_bulk(
                        users=users,
                        event_type=event_type,
                        title=title,
                        body=body,
                        event_key_prefix=f"{event_type.value}:{match.id}",
                    )
            except Exception:  # noqa: BLE001
                pass

        return match

    async def update_match_result(
        self, match_id: UUID, payload: MatchResultUpdate, current_user: User
    ) -> Match:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        if match.match_status != MatchStatus.COMPLETED:
            raise ValidationException("Match result can only be set once the match is completed")

        update_data: dict = {}
        if payload.winner_team_id is not None:
            slot = await self.slot_repo.get_by_match_and_team(match.id, payload.winner_team_id)
            if slot is None:
                raise ValidationException("Winner team must be assigned to this match")
            update_data["winner_team_id"] = payload.winner_team_id
        if payload.notes is not None:
            update_data["notes"] = payload.notes

        match = await self.repo.update(match, **update_data)
        await self.session.commit()
        await self.session.refresh(match)
        return match

    # ==================================================================
    # 3. Room Management
    # ==================================================================
    async def create_room(
        self, match_id: UUID, payload: RoomCreate, current_user: User
    ) -> Match:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        if match.match_status not in _PRE_LIVE_STATUSES:
            raise ValidationException("Room can only be created before the match goes live")

        match = await self.repo.update(
            match,
            room_name=payload.room_name,
            room_id=payload.room_id,
            room_password=payload.room_password,
            room_status=RoomStatus.HIDDEN,
        )
        await self.session.commit()
        await self.session.refresh(match)
        return match

    async def update_room(
        self, match_id: UUID, payload: RoomUpdate, current_user: User
    ) -> Match:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        if match.room_status == RoomStatus.NOT_CREATED:
            raise ValidationException("Room has not been created for this match yet")
        if match.match_status in (MatchStatus.COMPLETED, MatchStatus.CANCELLED):
            raise ValidationException("Cannot edit the room of a completed or cancelled match")

        update_data = payload.model_dump(exclude_unset=True)
        was_published = match.room_status == RoomStatus.PUBLISHED
        if was_published:
            update_data["room_status"] = RoomStatus.EDITED

        match = await self.repo.update(match, **update_data)
        await self.session.commit()
        await self.session.refresh(match)
        return match

    async def publish_room(self, match_id: UUID, current_user: User) -> Match:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        if match.room_status == RoomStatus.NOT_CREATED:
            raise ValidationException("Create the room before publishing it")
        if not match.room_id or not match.room_password:
            raise ValidationException("Room ID and password must be set before publishing")
        if match.match_status not in (
            MatchStatus.SCHEDULED,
            MatchStatus.ROOM_PUBLISHED,
        ):
            raise ValidationException(
                "Room can only be published once the match is scheduled"
            )

        target_match_status = (
            MatchStatus.ROOM_PUBLISHED
            if match.match_status == MatchStatus.SCHEDULED
            else match.match_status
        )
        self._assert_valid_match_transition(match.match_status, target_match_status)

        match = await self.repo.update(
            match,
            room_status=RoomStatus.PUBLISHED,
            room_published_at=datetime.now(timezone.utc),
            match_status=target_match_status,
        )
        await self.session.commit()
        await self.session.refresh(match)

        try:
            from app.models.notification import NotificationEventType
            from app.notifications.dispatch_service import NotificationDispatchService
            from app.repositories.participant_repository import ParticipantRepository

            participants = await ParticipantRepository(
                self.session
            ).list_active_for_tournament_all(tournament.id)
            users = [p.user for p in participants if p.user is not None]
            if users:
                await NotificationDispatchService(self.session).dispatch_bulk(
                    users=users,
                    event_type=NotificationEventType.ROOM_DETAILS_PUBLISHED,
                    title="Room ID & Password ready",
                    body=(
                        f"Room details for match {match.match_number} "
                        f"(round {match.round_number}) are now available. Check the app to join."
                    ),
                    event_key_prefix=f"room_published:{match.id}",
                )
        except Exception:  # noqa: BLE001 - never block room publishing
            pass

        return match

    async def hide_room(self, match_id: UUID, current_user: User) -> Match:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        if match.room_status == RoomStatus.NOT_CREATED:
            raise ValidationException("Room has not been created for this match yet")

        match = await self.repo.update(match, room_status=RoomStatus.HIDDEN)
        await self.session.commit()
        await self.session.refresh(match)
        return match

    async def delete_room(self, match_id: UUID, current_user: User) -> Match:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)

        match = await self.repo.update(
            match,
            room_name=None,
            room_id=None,
            room_password=None,
            room_status=RoomStatus.NOT_CREATED,
            room_published_at=None,
        )
        await self.session.commit()
        await self.session.refresh(match)
        return match

    async def get_match_room(self, match_id: UUID, current_user: Optional[User]) -> Match:
        """Returns the match with room credentials visible only when the
        room is published AND the caller is authorized (organizer/admin,
        or an assigned participant of this match)."""
        match, tournament = await self._get_match_and_tournament(match_id)

        can_see_credentials = match.room_status == RoomStatus.PUBLISHED and (
            current_user is not None
            and (
                self._is_admin(current_user)
                or self._is_organizer(tournament, current_user)
                or await self._is_assigned_to_match(match.id, current_user)
            )
        )
        if not can_see_credentials:
            match.room_id = None
            match.room_password = None
        return match

    async def _is_assigned_to_match(self, match_id: UUID, user: User) -> bool:
        slots = await self.slot_repo.list_for_match(match_id)
        for slot in slots:
            if slot.participant is not None and slot.participant.user_id == user.id:
                return True
            if slot.team is not None:
                if slot.team.captain_id == user.id:
                    return True
                for member in slot.team.members:
                    if member.user_id == user.id and member.deleted_at is None:
                        return True
        return False

    # ==================================================================
    # 2. Match Team / Player Assignment
    # ==================================================================
    async def assign_team(
        self,
        match_id: UUID,
        team_id: UUID,
        current_user: User,
        *,
        slot_number: Optional[int] = None,
        assignment_type: MatchAssignmentType = MatchAssignmentType.MANUAL,
    ) -> MatchParticipant:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        if not self._is_team_based(tournament):
            raise ValidationException(
                "This tournament is not team-based; assign participants instead"
            )
        if match.match_status in (MatchStatus.LIVE, MatchStatus.COMPLETED, MatchStatus.CANCELLED):
            raise ValidationException("Cannot assign teams once the match has started")

        team = await self.team_repo.get_by_id(team_id)
        if team is None or team.tournament_id != tournament.id:
            raise NotFoundException("Team not found in this tournament")
        if team.status == TeamStatus.DISBANDED:
            raise ValidationException("Cannot assign a disbanded team")

        existing = await self.slot_repo.get_by_match_and_team(match.id, team_id)
        if existing is not None:
            raise ConflictException("This team is already assigned to this match")

        resolved_slot = slot_number or await self.slot_repo.next_slot_number(match.id)
        slot = await self.slot_repo.create(
            match_id=match.id,
            team_id=team_id,
            slot_number=resolved_slot,
            assignment_type=assignment_type,
            assigned_by=current_user.id,
            check_in_status=(
                MatchCheckInStatus.PENDING
                if match.match_status
                in (MatchStatus.CHECK_IN_OPEN, MatchStatus.READY)
                else MatchCheckInStatus.NOT_OPEN
            ),
        )
        await self.session.commit()
        await self.session.refresh(slot)
        return slot

    async def assign_participant(
        self,
        match_id: UUID,
        participant_id: UUID,
        current_user: User,
        *,
        slot_number: Optional[int] = None,
        assignment_type: MatchAssignmentType = MatchAssignmentType.MANUAL,
    ) -> MatchParticipant:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        if self._is_team_based(tournament):
            raise ValidationException(
                "This tournament is team-based; assign teams instead"
            )
        if match.match_status in (MatchStatus.LIVE, MatchStatus.COMPLETED, MatchStatus.CANCELLED):
            raise ValidationException("Cannot assign players once the match has started")

        participant = await self.participant_repo.get_by_id(participant_id)
        if participant is None or participant.tournament_id != tournament.id:
            raise NotFoundException("Participant not found in this tournament")
        if participant.status in (ParticipantStatus.CANCELLED, ParticipantStatus.REJECTED):
            raise ValidationException("Cannot assign a cancelled/rejected participant")

        existing = await self.slot_repo.get_by_match_and_participant(match.id, participant_id)
        if existing is not None:
            raise ConflictException("This player is already assigned to this match")

        resolved_slot = slot_number or await self.slot_repo.next_slot_number(match.id)
        slot = await self.slot_repo.create(
            match_id=match.id,
            participant_id=participant_id,
            slot_number=resolved_slot,
            assignment_type=assignment_type,
            assigned_by=current_user.id,
            check_in_status=(
                MatchCheckInStatus.PENDING
                if match.match_status
                in (MatchStatus.CHECK_IN_OPEN, MatchStatus.READY)
                else MatchCheckInStatus.NOT_OPEN
            ),
        )
        await self.session.commit()
        await self.session.refresh(slot)
        return slot

    async def auto_assign(
        self, match_id: UUID, current_user: User, *, seed: Optional[int] = None
    ) -> list[MatchParticipant]:
        """Randomly assigns every remaining active team/participant of the
        tournament that isn't already in this match into open slots."""
        import random

        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        if match.match_status in (MatchStatus.LIVE, MatchStatus.COMPLETED, MatchStatus.CANCELLED):
            raise ValidationException("Cannot auto-assign once the match has started")

        existing_slots = await self.slot_repo.list_for_match(match.id)
        assigned_team_ids = {s.team_id for s in existing_slots if s.team_id}
        assigned_participant_ids = {
            s.participant_id for s in existing_slots if s.participant_id
        }
        next_slot = (max((s.slot_number for s in existing_slots), default=0)) + 1

        rng = random.Random(seed)
        created: list[MatchParticipant] = []

        if self._is_team_based(tournament):
            candidates = [
                t
                for t in await self.team_repo.list_all_active_for_tournament(tournament.id)
                if t.id not in assigned_team_ids
            ]
            rng.shuffle(candidates)
            for team in candidates:
                slot = await self.slot_repo.create(
                    match_id=match.id,
                    team_id=team.id,
                    slot_number=next_slot,
                    assignment_type=MatchAssignmentType.RANDOM,
                    assigned_by=current_user.id,
                    check_in_status=MatchCheckInStatus.NOT_OPEN,
                )
                created.append(slot)
                next_slot += 1
        else:
            items, _ = await self.participant_repo.list_for_tournament(
                tournament.id, page=1, page_size=10_000
            )
            candidates = [
                p
                for p in items
                if p.id not in assigned_participant_ids
                and p.status
                in (ParticipantStatus.PENDING, ParticipantStatus.CONFIRMED)
            ]
            rng.shuffle(candidates)
            for participant in candidates:
                slot = await self.slot_repo.create(
                    match_id=match.id,
                    participant_id=participant.id,
                    slot_number=next_slot,
                    assignment_type=MatchAssignmentType.RANDOM,
                    assigned_by=current_user.id,
                    check_in_status=MatchCheckInStatus.NOT_OPEN,
                )
                created.append(slot)
                next_slot += 1

        await self.session.commit()
        for slot in created:
            await self.session.refresh(slot)
        return created

    async def replace_slot(
        self,
        match_id: UUID,
        slot_id: UUID,
        current_user: User,
        *,
        new_team_id: Optional[UUID] = None,
        new_participant_id: Optional[UUID] = None,
    ) -> MatchParticipant:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        if match.match_status in (MatchStatus.LIVE, MatchStatus.COMPLETED, MatchStatus.CANCELLED):
            raise ValidationException(
                "Team/player can only be replaced before the match starts"
            )

        slot = await self.slot_repo.get_by_id(slot_id)
        if slot is None or slot.match_id != match.id:
            raise NotFoundException("Match slot not found")

        if new_team_id is not None:
            team = await self.team_repo.get_by_id(new_team_id)
            if team is None or team.tournament_id != tournament.id:
                raise NotFoundException("Replacement team not found in this tournament")
            existing = await self.slot_repo.get_by_match_and_team(match.id, new_team_id)
            if existing is not None:
                raise ConflictException("Replacement team is already assigned to this match")
            slot = await self.slot_repo.update(
                slot,
                team_id=new_team_id,
                participant_id=None,
                assignment_type=MatchAssignmentType.MANUAL,
                assigned_by=current_user.id,
                replaced_at=datetime.now(timezone.utc),
                check_in_status=MatchCheckInStatus.NOT_OPEN,
                checked_in_at=None,
                is_disqualified=False,
                disqualified_reason=None,
            )
        else:
            participant = await self.participant_repo.get_by_id(new_participant_id)
            if participant is None or participant.tournament_id != tournament.id:
                raise NotFoundException("Replacement participant not found in this tournament")
            existing = await self.slot_repo.get_by_match_and_participant(
                match.id, new_participant_id
            )
            if existing is not None:
                raise ConflictException(
                    "Replacement player is already assigned to this match"
                )
            slot = await self.slot_repo.update(
                slot,
                participant_id=new_participant_id,
                team_id=None,
                assignment_type=MatchAssignmentType.MANUAL,
                assigned_by=current_user.id,
                replaced_at=datetime.now(timezone.utc),
                check_in_status=MatchCheckInStatus.NOT_OPEN,
                checked_in_at=None,
                is_disqualified=False,
                disqualified_reason=None,
            )

        await self.session.commit()
        await self.session.refresh(slot)
        return slot

    async def unassign_slot(self, match_id: UUID, slot_id: UUID, current_user: User) -> None:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        if match.match_status in (MatchStatus.LIVE, MatchStatus.COMPLETED):
            raise ValidationException("Cannot unassign once the match is live or completed")

        slot = await self.slot_repo.get_by_id(slot_id)
        if slot is None or slot.match_id != match.id:
            raise NotFoundException("Match slot not found")

        await self.slot_repo.soft_delete(slot)
        await self.session.commit()

    async def list_match_slots(self, match_id: UUID) -> list[MatchParticipant]:
        await self.get_match(match_id)
        return list(await self.slot_repo.list_for_match(match_id))

    # ==================================================================
    # 6. Check-in System
    # ==================================================================
    async def _open_check_in_for_slots(self, match_id: UUID) -> None:
        slots = await self.slot_repo.list_for_match(match_id)
        for slot in slots:
            if slot.check_in_status == MatchCheckInStatus.NOT_OPEN:
                await self.slot_repo.update(slot, check_in_status=MatchCheckInStatus.PENDING)

    def _slot_belongs_to_user(self, slot: MatchParticipant, user: User) -> bool:
        if slot.participant is not None:
            return slot.participant.user_id == user.id
        if slot.team is not None:
            if slot.team.captain_id == user.id:
                return True
            return any(
                m.user_id == user.id and m.deleted_at is None for m in slot.team.members
            )
        return False

    async def check_in(
        self,
        match_id: UUID,
        current_user: User,
        *,
        team_id: Optional[UUID] = None,
        participant_id: Optional[UUID] = None,
    ) -> MatchParticipant:
        match = await self.get_match(match_id)
        if match.match_status not in (MatchStatus.CHECK_IN_OPEN, MatchStatus.ROOM_PUBLISHED):
            raise ValidationException("Check-in is not currently open for this match")

        if team_id is not None:
            slot = await self.slot_repo.get_by_match_and_team(match.id, team_id)
        else:
            slot = await self.slot_repo.get_by_match_and_participant(match.id, participant_id)
        if slot is None:
            raise NotFoundException("You are not assigned to this match")

        if not self._slot_belongs_to_user(slot, current_user):
            raise ForbiddenException(
                "Only the assigned team captain/member or player may check in"
            )

        if slot.check_in_status in (
            MatchCheckInStatus.CHECKED_IN,
            MatchCheckInStatus.LATE_CHECKED_IN,
        ):
            raise ConflictException("You have already checked in for this match")

        now = datetime.now(timezone.utc)
        is_late = match.check_in_deadline is not None and now > match.check_in_deadline
        target_status = (
            MatchCheckInStatus.LATE_CHECKED_IN if is_late else MatchCheckInStatus.CHECKED_IN
        )
        allowed = MATCH_CHECKIN_TRANSITIONS.get(slot.check_in_status, set())
        if target_status not in allowed and slot.check_in_status != MatchCheckInStatus.NOT_OPEN:
            raise ValidationException(
                f"Cannot check in from status '{slot.check_in_status.value}'"
            )

        slot = await self.slot_repo.update(
            slot,
            check_in_status=target_status,
            checked_in_at=now,
            checked_in_by=current_user.id,
            is_organizer_override=False,
            is_disqualified=False,
            disqualified_reason=None,
        )
        await self.session.commit()
        await self.session.refresh(slot)
        return slot

    async def organizer_override_check_in(
        self,
        match_id: UUID,
        slot_id: UUID,
        target_status: MatchCheckInStatus,
        current_user: User,
    ) -> MatchParticipant:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)

        slot = await self.slot_repo.get_by_id(slot_id)
        if slot is None or slot.match_id != match.id:
            raise NotFoundException("Match slot not found")

        update_fields: dict = {
            "check_in_status": target_status,
            "is_organizer_override": True,
            "checked_in_by": current_user.id,
        }
        if target_status in (
            MatchCheckInStatus.CHECKED_IN,
            MatchCheckInStatus.LATE_CHECKED_IN,
        ):
            update_fields["checked_in_at"] = datetime.now(timezone.utc)
            update_fields["is_disqualified"] = False
            update_fields["disqualified_reason"] = None
        elif target_status == MatchCheckInStatus.NO_SHOW:
            update_fields["checked_in_at"] = None

        slot = await self.slot_repo.update(slot, **update_fields)
        await self.session.commit()
        await self.session.refresh(slot)
        return slot

    async def get_check_in_status(self, match_id: UUID) -> list[MatchParticipant]:
        await self.get_match(match_id)
        return list(await self.slot_repo.list_for_match(match_id))

    # ==================================================================
    # 7. No-show Handling
    # ==================================================================
    async def _process_no_shows(self, match: Match) -> None:
        """Marks every slot still PENDING at check-in deadline as NO_SHOW,
        auto-disqualifying it when the match is configured to do so."""
        slots = await self.slot_repo.list_for_match(match.id)
        for slot in slots:
            if slot.check_in_status != MatchCheckInStatus.PENDING:
                continue
            await self.slot_repo.update(
                slot,
                check_in_status=MatchCheckInStatus.NO_SHOW,
                is_disqualified=match.auto_disqualify_on_no_show,
                disqualified_reason=(
                    "Automatic disqualification: no-show at check-in deadline"
                    if match.auto_disqualify_on_no_show
                    else None
                ),
            )

    async def mark_no_show(
        self, match_id: UUID, slot_id: UUID, current_user: User, *, disqualify: bool = True
    ) -> MatchParticipant:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)

        slot = await self.slot_repo.get_by_id(slot_id)
        if slot is None or slot.match_id != match.id:
            raise NotFoundException("Match slot not found")

        slot = await self.slot_repo.update(
            slot,
            check_in_status=MatchCheckInStatus.NO_SHOW,
            is_disqualified=disqualify,
            disqualified_reason="Manual no-show ruling by organizer" if disqualify else None,
            checked_in_at=None,
            is_organizer_override=True,
        )
        await self.session.commit()
        await self.session.refresh(slot)
        return slot

    async def override_no_show(
        self,
        match_id: UUID,
        slot_id: UUID,
        current_user: User,
        *,
        is_disqualified: bool,
        reason: Optional[str] = None,
    ) -> MatchParticipant:
        """Manual organizer override of a no-show/disqualification ruling —
        e.g. reinstating a team after a late but valid check-in dispute."""
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)

        slot = await self.slot_repo.get_by_id(slot_id)
        if slot is None or slot.match_id != match.id:
            raise NotFoundException("Match slot not found")

        update_fields: dict = {
            "is_disqualified": is_disqualified,
            "disqualified_reason": reason,
            "is_organizer_override": True,
        }
        if not is_disqualified and slot.check_in_status == MatchCheckInStatus.NO_SHOW:
            update_fields["check_in_status"] = MatchCheckInStatus.CHECKED_IN
            update_fields["checked_in_at"] = datetime.now(timezone.utc)
            update_fields["checked_in_by"] = current_user.id

        slot = await self.slot_repo.update(slot, **update_fields)
        await self.session.commit()
        await self.session.refresh(slot)
        return slot