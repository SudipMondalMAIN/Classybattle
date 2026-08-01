"""
Team Community System services — Phase 15B (Team Invitations, Join
Requests, Announcements & Activity Feed).

TeamInvitationService — invite/accept/reject/cancel team invitations.
TeamJoinRequestService — request/accept/reject/cancel join requests.
TeamAnnouncementService — captain/organizer announcements.
TeamActivityFeedService — idempotent activity recording + feed/history reads.

These services integrate with (without modifying) the existing Team
System (Phase 6), Notification System (Phase 13) and Tournament module,
reusing `AuditService` for sensitive mutations and
`NotificationDispatchService` for user-facing notifications — the same
pattern established by `SocialService` in Phase 15A. Membership changes
made here (accepting an invite/join request) reuse the exact
Participant-sync logic from `TeamService` so tournament capacity, payment
status and check-in flows keep working unmodified.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.models.audit_log import AuditAction
from app.models.notification import NotificationEventType
from app.models.participant import ParticipantPaymentStatus, ParticipantStatus, RegistrationType
from app.models.team import Team, TeamStatus
from app.models.team_community import (
    MEMBER_HISTORY_ACTIVITY_TYPES,
    TeamActivityFeedEntry,
    TeamActivityType,
    TeamAnnouncement,
    TeamInvitation,
    TeamInvitationStatus,
    TeamJoinRequest,
    TeamJoinRequestStatus,
)
from app.models.team_member import TeamMemberRole
from app.models.tournament import Tournament
from app.models.user import User, UserRole
from app.notifications.dispatch_service import NotificationDispatchService
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.team_community_repository import (
    TeamActivityFeedRepository,
    TeamAnnouncementRepository,
    TeamInvitationRepository,
    TeamJoinRequestRepository,
)
from app.repositories.team_member_repository import TeamMemberRepository
from app.repositories.team_repository import TeamRepository
from app.repositories.tournament_repository import TournamentRepository
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService

_MANAGER_ROLES = {UserRole.ADMIN, UserRole.SUPER_ADMIN}


def _paginate(total: int, page_size: int) -> int:
    return math.ceil(total / page_size) if total else 0


class _TeamCommunityBase:
    """Shared helpers reused across the Team Community services — kept
    local to this module (rather than editing `TeamService`) to preserve
    backward compatibility with the existing Team System."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.team_repo = TeamRepository(session)
        self.member_repo = TeamMemberRepository(session)
        self.tournament_repo = TournamentRepository(session)
        self.participant_repo = ParticipantRepository(session)
        self.user_repo = UserRepository(session)
        self.feed_repo = TeamActivityFeedRepository(session)
        self.audit = AuditService(session)
        self.dispatch = NotificationDispatchService(session)

    @staticmethod
    def _is_admin(user: User) -> bool:
        return user.role in _MANAGER_ROLES

    def _is_organizer(self, tournament: Tournament, user: User) -> bool:
        return tournament.created_by is not None and tournament.created_by == user.id

    def _assert_is_captain_or_manager(self, tournament: Tournament, team: Team, user: User) -> None:
        if self._is_admin(user) or self._is_organizer(tournament, user):
            return
        if team.captain_id == user.id:
            return
        raise ForbiddenException("Only the team captain or an organizer/admin can do this")

    async def _get_team(self, team_id: UUID) -> Team:
        team = await self.team_repo.get_by_id(team_id)
        if team is None:
            raise NotFoundException("Team not found")
        return team

    async def _get_tournament(self, tournament_id: UUID) -> Tournament:
        tournament = await self.tournament_repo.get_by_id(tournament_id)
        if tournament is None:
            raise NotFoundException("Tournament not found")
        return tournament

    async def _get_user(self, user_id: UUID) -> User:
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise NotFoundException("User not found")
        return user

    def _assert_team_joinable(self, team: Team) -> None:
        if team.status == TeamStatus.DISBANDED:
            raise ValidationException("This team no longer exists")
        if team.is_locked or team.status == TeamStatus.LOCKED:
            raise ConflictException("This team is locked and not accepting new members")
        if team.current_members >= team.team_size:
            raise ConflictException("This team has reached its maximum size")

    async def _assert_user_not_already_teamed(self, tournament_id: UUID, user_id: UUID) -> None:
        existing = await self.member_repo.get_for_user_in_tournament(tournament_id, user_id)
        if existing is not None:
            raise ConflictException("You are already a member of a team in this tournament")

    # ------------------------------------------------------------------
    # Participant sync — mirrors TeamService's private helper 1:1 so
    # tournament capacity/payment/check-in tracking stays consistent.
    # ------------------------------------------------------------------
    async def _ensure_participant_for_member(
        self, tournament: Tournament, team: Team, user: User
    ) -> Optional[UUID]:
        existing = await self.participant_repo.get_by_tournament_and_user(tournament.id, user.id)

        payment_status = (
            ParticipantPaymentStatus.PENDING
            if tournament.entry_fee and tournament.entry_fee > 0
            else ParticipantPaymentStatus.NOT_REQUIRED
        )

        if existing is not None and existing.status not in (
            ParticipantStatus.CANCELLED,
            ParticipantStatus.REJECTED,
        ):
            raise ConflictException("You are already registered for this tournament")

        if existing is not None:
            participant = await self.participant_repo.update(
                existing,
                registration_type=RegistrationType.TEAM,
                team_name=team.team_name,
                status=ParticipantStatus.PENDING,
                payment_status=payment_status,
                payment_reference=None,
                entry_fee_paid=0,
                cancelled_at=None,
                checked_in_at=None,
                joined_at=datetime.now(timezone.utc),
            )
        else:
            return None

        active_count = await self.participant_repo.count_active_for_tournament(tournament.id)
        if active_count > tournament.max_players:
            raise ConflictException("Tournament has reached maximum participant capacity")
        await self.tournament_repo.update(tournament, current_players=active_count)
        return participant.id

    async def _add_member_to_team(self, tournament: Tournament, team: Team, user: User) -> Team:
        existing_member = await self.member_repo.get_by_team_and_user(team.id, user.id)
        if existing_member is not None:
            raise ConflictException("You are already a member of this team")

        await self._assert_user_not_already_teamed(tournament.id, user.id)
        self._assert_team_joinable(team)

        participant_id = await self._ensure_participant_for_member(tournament, team, user)
        await self.member_repo.create(
            team_id=team.id,
            user_id=user.id,
            participant_id=participant_id,
            role=TeamMemberRole.MEMBER,
        )

        member_count = await self.member_repo.count_for_team(team.id)
        update_fields: dict = {"current_members": member_count}
        if member_count >= team.team_size and team.status == TeamStatus.FORMING:
            update_fields["status"] = TeamStatus.LOCKED
            update_fields["is_locked"] = True
        team = await self.team_repo.update(team, **update_fields)
        return team

    async def _record_activity(
        self,
        *,
        team: Team,
        actor: Optional[User],
        activity_type: TeamActivityType,
        title: str,
        event_key: Optional[str] = None,
        meta_data: Optional[dict] = None,
    ) -> Optional[TeamActivityFeedEntry]:
        """Idempotent when `event_key` is given (no-op on duplicate)."""
        if event_key:
            existing = await self.feed_repo.get_by_event_key(event_key)
            if existing is not None:
                return existing
        try:
            entry = await self.feed_repo.create(
                team_id=team.id,
                actor_id=actor.id if actor is not None else None,
                activity_type=activity_type,
                title=title,
                meta_data=meta_data,
                event_key=event_key,
            )
        except IntegrityError:
            await self.session.rollback()
            return await self.feed_repo.get_by_event_key(event_key) if event_key else None
        return entry


class TeamInvitationService(_TeamCommunityBase):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repo = TeamInvitationRepository(session)

    async def invite(
        self, team_id: UUID, inviter: User, invitee_id: UUID, message: Optional[str]
    ) -> TeamInvitation:
        team = await self._get_team(team_id)
        tournament = await self._get_tournament(team.tournament_id)
        self._assert_is_captain_or_manager(tournament, team, inviter)

        if inviter.id == invitee_id:
            raise BadRequestException("You cannot invite yourself")
        invitee = await self._get_user(invitee_id)

        self._assert_team_joinable(team)

        existing_member = await self.member_repo.get_by_team_and_user(team.id, invitee_id)
        if existing_member is not None:
            raise ConflictException("This user is already a member of this team")

        existing = await self.repo.get_by_team_and_invitee(team.id, invitee_id, include_deleted=True)
        if existing is not None and existing.deleted_at is None and existing.status == TeamInvitationStatus.PENDING:
            raise ConflictException("An invitation is already pending for this user")

        if existing is not None:
            invitation = await self.repo.update(
                existing,
                inviter_id=inviter.id,
                status=TeamInvitationStatus.PENDING,
                message=message,
                responded_at=None,
                deleted_at=None,
            )
        else:
            try:
                invitation = await self.repo.create(
                    team_id=team.id,
                    tournament_id=tournament.id,
                    inviter_id=inviter.id,
                    invitee_id=invitee_id,
                    status=TeamInvitationStatus.PENDING,
                    message=message,
                )
            except IntegrityError:
                await self.session.rollback()
                raise ConflictException("An invitation already exists for this user")

        await self.audit.record(
            entity="team_invitation",
            action=AuditAction.CREATE,
            entity_id=invitation.id,
            actor=inviter,
            new_values={"team_id": str(team.id), "invitee_id": str(invitee_id)},
        )
        await self._record_activity(
            team=team,
            actor=inviter,
            activity_type=TeamActivityType.INVITATION_SENT,
            title=f"{inviter.full_name} invited {invitee.full_name} to the team",
            event_key=f"team_invitation_sent:{invitation.id}",
            meta_data={"invitee_id": str(invitee_id)},
        )
        await self.session.commit()

        await self.dispatch.dispatch(
            user=invitee,
            event_type=NotificationEventType.GENERAL,
            title="Team invitation",
            body=f"{inviter.full_name} invited you to join team '{team.team_name}'.",
            event_key=f"team_invite:{invitation.id}",
        )
        return invitation

    async def _get_pending_for_invitee(self, invitee: User, invitation_id: UUID) -> TeamInvitation:
        invitation = await self.repo.get_by_id(invitation_id)
        if invitation is None or invitation.invitee_id != invitee.id:
            raise NotFoundException("Invitation not found")
        if invitation.status != TeamInvitationStatus.PENDING:
            raise ConflictException("This invitation is no longer pending")
        return invitation

    async def accept(self, invitee: User, invitation_id: UUID) -> TeamInvitation:
        invitation = await self._get_pending_for_invitee(invitee, invitation_id)
        team = await self._get_team(invitation.team_id)
        tournament = await self._get_tournament(invitation.tournament_id)

        team = await self._add_member_to_team(tournament, team, invitee)

        invitation = await self.repo.update(
            invitation,
            status=TeamInvitationStatus.ACCEPTED,
            responded_at=datetime.now(timezone.utc),
        )
        await self.audit.record(
            entity="team_invitation",
            action=AuditAction.STATUS_CHANGE,
            entity_id=invitation.id,
            actor=invitee,
            new_values={"status": "accepted"},
        )
        await self._record_activity(
            team=team,
            actor=invitee,
            activity_type=TeamActivityType.INVITATION_ACCEPTED,
            title=f"{invitee.full_name} accepted the invitation and joined the team",
            event_key=f"team_invitation_accepted:{invitation.id}",
        )
        await self._record_activity(
            team=team,
            actor=invitee,
            activity_type=TeamActivityType.MEMBER_JOINED,
            title=f"{invitee.full_name} joined the team",
            event_key=f"team_member_joined:{team.id}:{invitee.id}:{invitation.id}",
        )
        await self.session.commit()

        inviter = await self.user_repo.get_by_id(invitation.inviter_id)
        if inviter is not None:
            await self.dispatch.dispatch(
                user=inviter,
                event_type=NotificationEventType.GENERAL,
                title="Invitation accepted",
                body=f"{invitee.full_name} accepted your invitation to team '{team.team_name}'.",
                event_key=f"team_invite_accepted_notify:{invitation.id}",
            )
        return invitation

    async def reject(self, invitee: User, invitation_id: UUID) -> TeamInvitation:
        invitation = await self._get_pending_for_invitee(invitee, invitation_id)
        invitation = await self.repo.update(
            invitation,
            status=TeamInvitationStatus.REJECTED,
            responded_at=datetime.now(timezone.utc),
        )
        team = await self._get_team(invitation.team_id)
        await self.audit.record(
            entity="team_invitation",
            action=AuditAction.STATUS_CHANGE,
            entity_id=invitation.id,
            actor=invitee,
            new_values={"status": "rejected"},
        )
        await self._record_activity(
            team=team,
            actor=invitee,
            activity_type=TeamActivityType.INVITATION_REJECTED,
            title=f"{invitee.full_name} declined the team invitation",
            event_key=f"team_invitation_rejected:{invitation.id}",
        )
        await self.session.commit()
        return invitation

    async def cancel(self, actor: User, invitation_id: UUID) -> TeamInvitation:
        invitation = await self.repo.get_by_id(invitation_id)
        if invitation is None:
            raise NotFoundException("Invitation not found")
        team = await self._get_team(invitation.team_id)
        tournament = await self._get_tournament(invitation.tournament_id)

        if invitation.inviter_id != actor.id:
            self._assert_is_captain_or_manager(tournament, team, actor)
        if invitation.status != TeamInvitationStatus.PENDING:
            raise ConflictException("Only pending invitations can be cancelled")

        invitation = await self.repo.update(
            invitation, status=TeamInvitationStatus.CANCELLED, responded_at=datetime.now(timezone.utc)
        )
        await self.audit.record(
            entity="team_invitation",
            action=AuditAction.STATUS_CHANGE,
            entity_id=invitation.id,
            actor=actor,
            new_values={"status": "cancelled"},
        )
        await self._record_activity(
            team=team,
            actor=actor,
            activity_type=TeamActivityType.INVITATION_CANCELLED,
            title=f"{actor.full_name} cancelled a team invitation",
            event_key=f"team_invitation_cancelled:{invitation.id}",
        )
        await self.session.commit()
        return invitation

    async def list_for_team(
        self,
        team_id: UUID,
        actor: User,
        *,
        page: int,
        page_size: int,
        status: Optional[TeamInvitationStatus],
        sort_by: str,
        sort_order: str,
    ) -> tuple[Sequence[TeamInvitation], int]:
        team = await self._get_team(team_id)
        tournament = await self._get_tournament(team.tournament_id)
        self._assert_is_captain_or_manager(tournament, team, actor)
        return await self.repo.list_for_team(
            team_id, page=page, page_size=page_size, status=status, sort_by=sort_by, sort_order=sort_order
        )

    async def list_incoming(self, user: User, *, page: int, page_size: int):
        return await self.repo.list_incoming_for_user(user.id, page=page, page_size=page_size)


class TeamJoinRequestService(_TeamCommunityBase):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repo = TeamJoinRequestRepository(session)

    async def request_to_join(
        self, team_id: UUID, user: User, message: Optional[str]
    ) -> TeamJoinRequest:
        team = await self._get_team(team_id)
        tournament = await self._get_tournament(team.tournament_id)
        self._assert_team_joinable(team)

        existing_member = await self.member_repo.get_by_team_and_user(team.id, user.id)
        if existing_member is not None:
            raise ConflictException("You are already a member of this team")

        await self._assert_user_not_already_teamed(tournament.id, user.id)

        existing = await self.repo.get_by_team_and_user(team.id, user.id, include_deleted=True)
        if existing is not None and existing.deleted_at is None and existing.status == TeamJoinRequestStatus.PENDING:
            raise ConflictException("You already have a pending join request for this team")

        if existing is not None:
            join_request = await self.repo.update(
                existing,
                status=TeamJoinRequestStatus.PENDING,
                message=message,
                responded_at=None,
                reviewed_by_id=None,
                deleted_at=None,
            )
        else:
            try:
                join_request = await self.repo.create(
                    team_id=team.id,
                    tournament_id=tournament.id,
                    user_id=user.id,
                    status=TeamJoinRequestStatus.PENDING,
                    message=message,
                )
            except IntegrityError:
                await self.session.rollback()
                raise ConflictException("A join request already exists for this team")

        await self.audit.record(
            entity="team_join_request",
            action=AuditAction.CREATE,
            entity_id=join_request.id,
            actor=user,
            new_values={"team_id": str(team.id)},
        )
        await self._record_activity(
            team=team,
            actor=user,
            activity_type=TeamActivityType.JOIN_REQUEST_SENT,
            title=f"{user.full_name} requested to join the team",
            event_key=f"team_join_request_sent:{join_request.id}",
        )
        await self.session.commit()

        if team.captain_id is not None:
            captain = await self.user_repo.get_by_id(team.captain_id)
            if captain is not None:
                await self.dispatch.dispatch(
                    user=captain,
                    event_type=NotificationEventType.GENERAL,
                    title="New join request",
                    body=f"{user.full_name} wants to join team '{team.team_name}'.",
                    event_key=f"team_join_request:{join_request.id}",
                )
        return join_request

    async def _get_pending_for_team(self, team_id: UUID, request_id: UUID) -> TeamJoinRequest:
        join_request = await self.repo.get_by_id(request_id)
        if join_request is None or join_request.team_id != team_id:
            raise NotFoundException("Join request not found")
        if join_request.status != TeamJoinRequestStatus.PENDING:
            raise ConflictException("This join request is no longer pending")
        return join_request

    async def accept(self, team_id: UUID, actor: User, request_id: UUID) -> TeamJoinRequest:
        team = await self._get_team(team_id)
        tournament = await self._get_tournament(team.tournament_id)
        self._assert_is_captain_or_manager(tournament, team, actor)

        join_request = await self._get_pending_for_team(team_id, request_id)
        applicant = await self._get_user(join_request.user_id)

        team = await self._add_member_to_team(tournament, team, applicant)

        join_request = await self.repo.update(
            join_request,
            status=TeamJoinRequestStatus.ACCEPTED,
            responded_at=datetime.now(timezone.utc),
            reviewed_by_id=actor.id,
        )
        await self.audit.record(
            entity="team_join_request",
            action=AuditAction.STATUS_CHANGE,
            entity_id=join_request.id,
            actor=actor,
            new_values={"status": "accepted"},
        )
        await self._record_activity(
            team=team,
            actor=actor,
            activity_type=TeamActivityType.JOIN_REQUEST_ACCEPTED,
            title=f"{applicant.full_name}'s join request was accepted",
            event_key=f"team_join_request_accepted:{join_request.id}",
        )
        await self._record_activity(
            team=team,
            actor=applicant,
            activity_type=TeamActivityType.MEMBER_JOINED,
            title=f"{applicant.full_name} joined the team",
            event_key=f"team_member_joined:{team.id}:{applicant.id}:{join_request.id}",
        )
        await self.session.commit()

        await self.dispatch.dispatch(
            user=applicant,
            event_type=NotificationEventType.GENERAL,
            title="Join request accepted",
            body=f"Your request to join team '{team.team_name}' was accepted.",
            event_key=f"team_join_request_accepted_notify:{join_request.id}",
        )
        return join_request

    async def reject(self, team_id: UUID, actor: User, request_id: UUID) -> TeamJoinRequest:
        team = await self._get_team(team_id)
        tournament = await self._get_tournament(team.tournament_id)
        self._assert_is_captain_or_manager(tournament, team, actor)

        join_request = await self._get_pending_for_team(team_id, request_id)
        join_request = await self.repo.update(
            join_request,
            status=TeamJoinRequestStatus.REJECTED,
            responded_at=datetime.now(timezone.utc),
            reviewed_by_id=actor.id,
        )
        await self.audit.record(
            entity="team_join_request",
            action=AuditAction.STATUS_CHANGE,
            entity_id=join_request.id,
            actor=actor,
            new_values={"status": "rejected"},
        )
        await self._record_activity(
            team=team,
            actor=actor,
            activity_type=TeamActivityType.JOIN_REQUEST_REJECTED,
            title="A join request was declined",
            event_key=f"team_join_request_rejected:{join_request.id}",
        )
        await self.session.commit()
        return join_request

    async def cancel(self, user: User, request_id: UUID) -> TeamJoinRequest:
        join_request = await self.repo.get_by_id(request_id)
        if join_request is None or join_request.user_id != user.id:
            raise NotFoundException("Join request not found")
        if join_request.status != TeamJoinRequestStatus.PENDING:
            raise ConflictException("Only pending join requests can be cancelled")

        join_request = await self.repo.update(
            join_request, status=TeamJoinRequestStatus.CANCELLED, responded_at=datetime.now(timezone.utc)
        )
        team = await self._get_team(join_request.team_id)
        await self.audit.record(
            entity="team_join_request",
            action=AuditAction.STATUS_CHANGE,
            entity_id=join_request.id,
            actor=user,
            new_values={"status": "cancelled"},
        )
        await self._record_activity(
            team=team,
            actor=user,
            activity_type=TeamActivityType.JOIN_REQUEST_CANCELLED,
            title=f"{user.full_name} cancelled their join request",
            event_key=f"team_join_request_cancelled:{join_request.id}",
        )
        await self.session.commit()
        return join_request

    async def list_for_team(
        self,
        team_id: UUID,
        actor: User,
        *,
        page: int,
        page_size: int,
        status: Optional[TeamJoinRequestStatus],
        sort_by: str,
        sort_order: str,
    ) -> tuple[Sequence[TeamJoinRequest], int]:
        team = await self._get_team(team_id)
        tournament = await self._get_tournament(team.tournament_id)
        self._assert_is_captain_or_manager(tournament, team, actor)
        return await self.repo.list_for_team(
            team_id, page=page, page_size=page_size, status=status, sort_by=sort_by, sort_order=sort_order
        )

    async def list_outgoing(self, user: User, *, page: int, page_size: int):
        return await self.repo.list_outgoing_for_user(user.id, page=page, page_size=page_size)


class TeamAnnouncementService(_TeamCommunityBase):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.repo = TeamAnnouncementRepository(session)

    async def create(
        self, team_id: UUID, author: User, *, title: str, content: str, is_pinned: bool
    ) -> TeamAnnouncement:
        team = await self._get_team(team_id)
        tournament = await self._get_tournament(team.tournament_id)
        self._assert_is_captain_or_manager(tournament, team, author)

        announcement = await self.repo.create(
            team_id=team.id, author_id=author.id, title=title.strip(), content=content.strip(), is_pinned=is_pinned
        )
        await self.audit.record(
            entity="team_announcement",
            action=AuditAction.CREATE,
            entity_id=announcement.id,
            actor=author,
            new_values={"title": title},
        )
        await self._record_activity(
            team=team,
            actor=author,
            activity_type=TeamActivityType.ANNOUNCEMENT_POSTED,
            title=f"New announcement: {announcement.title}",
            event_key=f"team_announcement_posted:{announcement.id}",
        )
        await self.session.commit()

        members = await self.member_repo.list_for_team(team.id)
        recipients = [m.user for m in members if m.user_id != author.id]
        await self.dispatch.dispatch_bulk(
            users=recipients,
            event_type=NotificationEventType.GENERAL,
            title=f"Team announcement: {announcement.title}",
            body=announcement.content[:200],
            event_key_prefix=f"team_announcement:{announcement.id}",
        )
        return announcement

    async def update(
        self,
        team_id: UUID,
        announcement_id: UUID,
        actor: User,
        *,
        title: Optional[str],
        content: Optional[str],
        is_pinned: Optional[bool],
    ) -> TeamAnnouncement:
        team = await self._get_team(team_id)
        tournament = await self._get_tournament(team.tournament_id)
        self._assert_is_captain_or_manager(tournament, team, actor)

        announcement = await self.repo.get_by_id(announcement_id)
        if announcement is None or announcement.team_id != team_id:
            raise NotFoundException("Announcement not found")

        update_data = {}
        if title is not None:
            update_data["title"] = title.strip()
        if content is not None:
            update_data["content"] = content.strip()
        if is_pinned is not None:
            update_data["is_pinned"] = is_pinned

        announcement = await self.repo.update(announcement, **update_data)
        await self.audit.record(
            entity="team_announcement",
            action=AuditAction.UPDATE,
            entity_id=announcement.id,
            actor=actor,
            new_values=update_data,
        )
        await self._record_activity(
            team=team,
            actor=actor,
            activity_type=TeamActivityType.ANNOUNCEMENT_UPDATED,
            title=f"Announcement updated: {announcement.title}",
        )
        await self.session.commit()
        return announcement

    async def delete(self, team_id: UUID, announcement_id: UUID, actor: User) -> None:
        team = await self._get_team(team_id)
        tournament = await self._get_tournament(team.tournament_id)
        self._assert_is_captain_or_manager(tournament, team, actor)

        announcement = await self.repo.get_by_id(announcement_id)
        if announcement is None or announcement.team_id != team_id:
            raise NotFoundException("Announcement not found")

        await self.repo.soft_delete(announcement)
        await self.audit.record(
            entity="team_announcement",
            action=AuditAction.DELETE,
            entity_id=announcement.id,
            actor=actor,
        )
        await self._record_activity(
            team=team,
            actor=actor,
            activity_type=TeamActivityType.ANNOUNCEMENT_DELETED,
            title=f"Announcement removed: {announcement.title}",
        )
        await self.session.commit()

    async def list_for_team(
        self, team_id: UUID, *, page: int, page_size: int, pinned_only: bool, sort_order: str
    ) -> tuple[Sequence[TeamAnnouncement], int]:
        await self._get_team(team_id)
        return await self.repo.list_for_team(
            team_id, page=page, page_size=page_size, pinned_only=pinned_only, sort_order=sort_order
        )


class TeamActivityFeedService(_TeamCommunityBase):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_feed(
        self,
        team_id: UUID,
        *,
        page: int,
        page_size: int,
        activity_type: Optional[TeamActivityType],
        actor_id: Optional[UUID],
        sort_order: str,
    ) -> tuple[Sequence[TeamActivityFeedEntry], int]:
        await self._get_team(team_id)
        activity_types = [activity_type] if activity_type else None
        return await self.feed_repo.list_for_team(
            team_id,
            page=page,
            page_size=page_size,
            activity_types=activity_types,
            actor_id=actor_id,
            sort_order=sort_order,
        )

    async def get_member_history(
        self, team_id: UUID, *, page: int, page_size: int, sort_order: str
    ) -> tuple[Sequence[TeamActivityFeedEntry], int]:
        await self._get_team(team_id)
        return await self.feed_repo.list_for_team(
            team_id,
            page=page,
            page_size=page_size,
            activity_types=MEMBER_HISTORY_ACTIVITY_TYPES,
            sort_order=sort_order,
        )

    async def get_event_history(
        self, team_id: UUID, *, page: int, page_size: int, sort_order: str
    ) -> tuple[Sequence[TeamActivityFeedEntry], int]:
        """Full chronological event history for the team (all activity
        types) — distinct from `get_feed` only in that it is always
        unfiltered, giving organizers/admins a complete audit trail."""
        await self._get_team(team_id)
        return await self.feed_repo.list_for_team(
            team_id, page=page, page_size=page_size, activity_types=None, sort_order=sort_order
        )
