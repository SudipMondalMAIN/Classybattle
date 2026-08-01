"""
MatchResultService — Match Result & Winner Management System (Phase 11).

Orchestrates:
- Submission / update / (admin) delete of a match's result, one active
  row per match (mirrors PrizePool's one-per-tournament pattern).
- Verify -> Approve -> Reject workflow, guarded by an explicit status
  transition table (MATCH_RESULT_STATUS_TRANSITIONS), same style as
  MatchService/PrizeService.
- Automatic rank calculation from submitted scores (ties share a rank),
  and manual winner override, both funnelling into MatchWinner rows
  guarded by DB-level uniqueness (rank / team / participant per match)
  so winners can never be declared twice for the same match.
- Exactly-once, atomic Automatic Prize Distribution Trigger on approval:
  winners are handed to the existing Phase 10 PrizeService
  (assign_winners + distribute_prizes), guarded by
  MatchResult.prize_distribution_triggered with a row lock, so retries
  or concurrent approve calls can never double-trigger payouts.
- Full audit trail via the existing AuditService; match result / winner
  history is served straight from that same audit trail.

Team-match payout assumption
-----------------------------
Phase 10's PrizePayout is keyed on a single Participant. For a team win,
this service resolves the payout recipient as the team captain's
Participant record (via TeamMember), since Prize's schema has no notion
of splitting a payout across teammates. This mirrors how Team's own
`captain_id` is already used as the team's primary point of contact
elsewhere in the codebase.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.models.audit_log import AuditAction, AuditActorType, AuditLog
from app.models.match import Match, MatchStatus
from app.models.match_result import (
    MATCH_RESULT_STATUS_TRANSITIONS,
    MatchResult,
    MatchResultStatus,
)
from app.models.match_winner import MatchWinner, WinnerAssignmentSource
from app.models.team_member import TeamMemberRole
from app.models.tournament import Tournament
from app.models.user import User, UserRole
from app.repositories.match_participant_repository import MatchParticipantRepository
from app.repositories.match_repository import MatchRepository
from app.repositories.match_result_repository import MatchResultRepository
from app.repositories.match_winner_repository import MatchWinnerRepository
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.team_repository import TeamRepository
from app.repositories.tournament_repository import TournamentRepository
from app.services.audit_service import AuditService
from app.services.prize_service import PrizeService

_MANAGER_ROLES = {UserRole.ADMIN, UserRole.SUPER_ADMIN}

_RESULT_ENTITY = "match_result"
_WINNER_ENTITY = "match_winner"

# Results can only be reported once a match has actually been played.
_RESULT_ELIGIBLE_STATUSES = {MatchStatus.LIVE, MatchStatus.COMPLETED}


class MatchResultService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.result_repo = MatchResultRepository(session)
        self.winner_repo = MatchWinnerRepository(session)
        self.match_repo = MatchRepository(session)
        self.slot_repo = MatchParticipantRepository(session)
        self.tournament_repo = TournamentRepository(session)
        self.team_repo = TeamRepository(session)
        self.participant_repo = ParticipantRepository(session)
        self.audit = AuditService(session)
        self.prize_service = PrizeService(session)

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
            "You do not have permission to manage match results for this tournament"
        )

    async def _notify_winners(self, winners: list) -> None:
        try:
            from app.models.notification import NotificationEventType
            from app.notifications.dispatch_service import NotificationDispatchService

            dispatch = NotificationDispatchService(self.session)
            for winner in winners:
                participant_id = winner.participant_id
                if participant_id is None and winner.team_id is not None:
                    participant_id = await self._resolve_captain_participant_id(winner.team_id)
                if participant_id is None:
                    continue
                participant = await self.participant_repo.get_by_id(participant_id)
                if participant is None or participant.user is None:
                    continue
                await dispatch.dispatch(
                    user=participant.user,
                    event_type=NotificationEventType.WINNER_DECLARED,
                    title="You won!",
                    body=f"Congratulations! You placed rank {winner.rank} in your match.",
                    event_key=f"winner_declared:{winner.id}",
                )
        except Exception:  # noqa: BLE001 - notifications must never break result flows
            pass

    async def _slot_belongs_to_user(self, match_id: UUID, user: User) -> bool:
        slots = await self.slot_repo.list_for_match(match_id)
        for slot in slots:
            if slot.participant is not None and slot.participant.user_id == user.id:
                return True
            if slot.team is not None:
                if slot.team.captain_id == user.id:
                    return True
                if any(m.user_id == user.id and m.deleted_at is None for m in slot.team.members):
                    return True
        return False

    # ------------------------------------------------------------------
    # Fetch helpers
    # ------------------------------------------------------------------
    async def _get_match(self, match_id: UUID) -> Match:
        match = await self.match_repo.get_by_id(match_id)
        if match is None:
            raise NotFoundException("Match not found")
        return match

    async def _get_tournament(self, tournament_id: UUID) -> Tournament:
        tournament = await self.tournament_repo.get_by_id(tournament_id)
        if tournament is None:
            raise NotFoundException("Tournament not found")
        return tournament

    async def _get_match_and_tournament(self, match_id: UUID) -> tuple[Match, Tournament]:
        match = await self._get_match(match_id)
        tournament = await self._get_tournament(match.tournament_id)
        return match, tournament

    async def get_result(self, match_id: UUID) -> MatchResult:
        result = await self.result_repo.get_by_match_id(match_id)
        if result is None:
            raise NotFoundException("No match result has been submitted for this match")
        return result

    # ==================================================================
    # 1. Submit / Update / Delete
    # ==================================================================
    @staticmethod
    def _entries_to_json(entries) -> list[dict]:
        out = []
        for e in entries:
            item: dict = {"score": e.score}
            if e.team_id is not None:
                item["team_id"] = str(e.team_id)
            if e.participant_id is not None:
                item["participant_id"] = str(e.participant_id)
            if e.placement is not None:
                item["placement"] = e.placement
            out.append(item)
        return out

    async def _validate_entities_in_match(self, match_id: UUID, entries) -> None:
        for e in entries:
            if e.team_id is not None:
                slot = await self.slot_repo.get_by_match_and_team(match_id, e.team_id)
                if slot is None:
                    raise ValidationException(f"Team {e.team_id} is not assigned to this match")
            else:
                slot = await self.slot_repo.get_by_match_and_participant(match_id, e.participant_id)
                if slot is None:
                    raise ValidationException(
                        f"Participant {e.participant_id} is not assigned to this match"
                    )

    async def submit_result(self, match_id: UUID, payload, current_user: User) -> MatchResult:
        match, tournament = await self._get_match_and_tournament(match_id)

        is_manager = self._is_admin(current_user) or self._is_organizer(tournament, current_user)
        if not is_manager and not await self._slot_belongs_to_user(match_id, current_user):
            raise ForbiddenException(
                "Only the organizer, an admin, or a match participant may submit a result"
            )

        if match.match_status not in _RESULT_ELIGIBLE_STATUSES:
            raise ValidationException(
                "A result can only be submitted once the match is live or completed"
            )

        await self._validate_entities_in_match(match_id, payload.result_data)
        result_data = self._entries_to_json(payload.result_data)
        now = datetime.now(timezone.utc)

        existing = await self.result_repo.get_by_match_id(match_id)
        if existing is not None:
            if existing.status != MatchResultStatus.REJECTED:
                raise ConflictException(
                    "A result has already been submitted for this match "
                    f"(current status: '{existing.status.value}')"
                )
            # Resubmission after rejection reuses the same row.
            result = await self.result_repo.update(
                existing,
                result_data=result_data,
                is_tie=payload.is_tie,
                notes=payload.notes,
                status=MatchResultStatus.SUBMITTED,
                submitted_by=current_user.id,
                submitted_at=now,
                rejected_by=None,
                rejected_at=None,
                rejection_reason=None,
            )
            action = AuditAction.UPDATE
            description = f"Match result resubmitted for match {match_id}"
        else:
            result = await self.result_repo.create(
                match_id=match_id,
                tournament_id=match.tournament_id,
                result_data=result_data,
                is_tie=payload.is_tie,
                notes=payload.notes,
                status=MatchResultStatus.SUBMITTED,
                submitted_by=current_user.id,
                submitted_at=now,
            )
            action = AuditAction.CREATE
            description = f"Match result submitted for match {match_id}"

        await self.audit.record(
            entity=_RESULT_ENTITY,
            action=action,
            entity_id=result.id,
            actor=current_user,
            new_values={"result_data": result_data, "is_tie": payload.is_tie},
            description=description,
        )
        await self.session.commit()
        await self.session.refresh(result)
        return result

    async def update_result(self, match_id: UUID, payload, current_user: User) -> MatchResult:
        match, tournament = await self._get_match_and_tournament(match_id)
        result = await self.get_result(match_id)

        is_manager = self._is_admin(current_user) or self._is_organizer(tournament, current_user)
        is_submitter = result.submitted_by == current_user.id
        if not is_manager and not is_submitter:
            raise ForbiddenException(
                "Only the organizer, an admin, or the original submitter may update this result"
            )
        if result.status == MatchResultStatus.APPROVED:
            raise ValidationException("Cannot update a result that has already been approved")

        old_values = {"result_data": result.result_data, "is_tie": result.is_tie}
        update_fields: dict = {}
        if payload.result_data is not None:
            await self._validate_entities_in_match(match_id, payload.result_data)
            update_fields["result_data"] = self._entries_to_json(payload.result_data)
        if payload.is_tie is not None:
            update_fields["is_tie"] = payload.is_tie
        if payload.notes is not None:
            update_fields["notes"] = payload.notes

        # Editing content after verification resets it back to SUBMITTED so
        # it must be re-verified/re-approved.
        if result.status == MatchResultStatus.VERIFIED and update_fields:
            update_fields["status"] = MatchResultStatus.SUBMITTED
            update_fields["verified_by"] = None
            update_fields["verified_at"] = None

        result = await self.result_repo.update(result, **update_fields)

        await self.audit.record(
            entity=_RESULT_ENTITY,
            action=AuditAction.UPDATE,
            entity_id=result.id,
            actor=current_user,
            old_values=old_values,
            new_values={"result_data": result.result_data, "is_tie": result.is_tie},
            description=f"Match result updated for match {match_id}",
        )
        await self.session.commit()
        await self.session.refresh(result)
        return result

    async def delete_result(self, match_id: UUID, current_user: User) -> None:
        if not self._is_admin(current_user):
            raise ForbiddenException("Only an admin can delete a match result")

        result = await self.get_result(match_id)
        if result.prize_distribution_triggered:
            raise ConflictException(
                "Cannot delete a match result after prize distribution has been triggered"
            )

        await self.winner_repo.delete_all_for_match(match_id)
        await self.result_repo.soft_delete(result)

        await self.audit.record(
            entity=_RESULT_ENTITY,
            action=AuditAction.DELETE,
            entity_id=result.id,
            actor=current_user,
            actor_type=AuditActorType.ADMIN,
            description=f"Match result deleted for match {match_id}",
        )
        await self.session.commit()

    # ==================================================================
    # 2. Verify / Reject
    # ==================================================================
    @staticmethod
    def _assert_valid_transition(current: MatchResultStatus, target: MatchResultStatus) -> None:
        allowed = MATCH_RESULT_STATUS_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValidationException(
                f"Cannot transition match result from '{current.value}' to '{target.value}'"
            )

    async def verify_result(self, match_id: UUID, current_user: User) -> MatchResult:
        _, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        result = await self.get_result(match_id)
        self._assert_valid_transition(result.status, MatchResultStatus.VERIFIED)

        result = await self.result_repo.update(
            result,
            status=MatchResultStatus.VERIFIED,
            verified_by=current_user.id,
            verified_at=datetime.now(timezone.utc),
        )
        await self.audit.record(
            entity=_RESULT_ENTITY,
            action=AuditAction.STATUS_CHANGE,
            entity_id=result.id,
            actor=current_user,
            new_values={"status": MatchResultStatus.VERIFIED.value},
            description=f"Match result verified for match {match_id}",
        )
        await self.session.commit()
        await self.session.refresh(result)
        return result

    async def reject_result(self, match_id: UUID, reason: str, current_user: User) -> MatchResult:
        _, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        result = await self.get_result(match_id)
        if result.prize_distribution_triggered:
            raise ConflictException(
                "Cannot reject a match result after prize distribution has been triggered"
            )
        self._assert_valid_transition(result.status, MatchResultStatus.REJECTED)

        await self.winner_repo.delete_all_for_match(match_id)
        result = await self.result_repo.update(
            result,
            status=MatchResultStatus.REJECTED,
            rejected_by=current_user.id,
            rejected_at=datetime.now(timezone.utc),
            rejection_reason=reason,
        )
        await self.audit.record(
            entity=_RESULT_ENTITY,
            action=AuditAction.STATUS_CHANGE,
            entity_id=result.id,
            actor=current_user,
            new_values={"status": MatchResultStatus.REJECTED.value, "reason": reason},
            description=f"Match result rejected for match {match_id}: {reason}",
        )
        await self.session.commit()
        await self.session.refresh(result)
        return result

    # ==================================================================
    # 3. Automatic rank calculation / winner selection
    # ==================================================================
    @staticmethod
    def _compute_ranks(result_data: list[dict]) -> list[dict]:
        """Standard competition ranking ("1224"): equal scores share the
        same rank and the next rank skips accordingly."""
        entries = [dict(e) for e in result_data]
        entries.sort(key=lambda e: e.get("score", 0), reverse=True)

        ranked: list[dict] = []
        current_rank = 0
        previous_score = None
        for idx, entry in enumerate(entries, start=1):
            score = entry.get("score", 0)
            if entry.get("placement"):
                entry["rank"] = entry["placement"]
            else:
                if score != previous_score:
                    current_rank = idx
                entry["rank"] = current_rank
            previous_score = score
            ranked.append(entry)
        return ranked

    async def _resolve_captain_participant_id(self, team_id: UUID) -> Optional[UUID]:
        team = await self.team_repo.get_by_id(team_id)
        if team is None:
            return None
        for member in team.members:
            if member.deleted_at is not None:
                continue
            if member.role == TeamMemberRole.CAPTAIN or member.user_id == team.captain_id:
                if member.participant_id is not None:
                    return member.participant_id
        return None

    async def auto_select_winners(self, match_id: UUID, current_user: User) -> list[MatchWinner]:
        """Automatically declares winners from the submitted result_data's
        scores. Idempotent: if winners already exist for this match
        (whether manual or automatic), this is a no-op — call
        `declare_winners` to explicitly override."""
        _, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        result = await self.get_result(match_id)

        existing = await self.winner_repo.list_for_match(match_id)
        if existing:
            return list(existing)

        ranked = self._compute_ranks(result.result_data)
        rank_counts: dict[int, int] = {}
        for e in ranked:
            rank_counts[e["rank"]] = rank_counts.get(e["rank"], 0) + 1

        created: list[MatchWinner] = []
        now = datetime.now(timezone.utc)
        for entry in ranked:
            team_id = UUID(entry["team_id"]) if entry.get("team_id") else None
            participant_id = UUID(entry["participant_id"]) if entry.get("participant_id") else None
            is_tie = rank_counts[entry["rank"]] > 1

            winner = await self.winner_repo.create(
                match_id=match_id,
                match_result_id=result.id,
                tournament_id=result.tournament_id,
                team_id=team_id,
                participant_id=participant_id,
                rank=entry["rank"],
                is_tie=is_tie,
                assignment_source=WinnerAssignmentSource.AUTOMATIC,
                is_manual_override=False,
                declared_by=current_user.id,
                declared_at=now,
            )
            created.append(winner)

        if any(w.is_tie for w in created) and not result.is_tie:
            result = await self.result_repo.update(result, is_tie=True)

        await self.audit.record(
            entity=_WINNER_ENTITY,
            action=AuditAction.CREATE,
            entity_id=match_id,
            actor=current_user,
            new_values={"winners": [str(w.id) for w in created], "source": "automatic"},
            description=f"Winners auto-selected for match {match_id}",
        )
        await self.session.commit()
        for w in created:
            await self.session.refresh(w)

        await self._notify_winners(created)

        return created

    async def declare_winners(
        self, match_id: UUID, payload, current_user: User
    ) -> list[MatchWinner]:
        """Manual winner declaration / override. Idempotent for exact
        repeats (same rank+entity), but raises a conflict if a rank or
        entity is already assigned differently — winners can never be
        silently overwritten once declared."""
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        result = await self.get_result(match_id)

        if result.status not in (MatchResultStatus.VERIFIED, MatchResultStatus.APPROVED):
            raise ValidationException(
                "Winners can only be declared once the match result has been verified"
            )
        if result.prize_distribution_triggered:
            raise ConflictException(
                "Cannot change winners after prize distribution has been triggered"
            )

        created: list[MatchWinner] = []
        now = datetime.now(timezone.utc)
        for winner in payload.winners:
            if winner.team_id is not None:
                slot = await self.slot_repo.get_by_match_and_team(match_id, winner.team_id)
                if slot is None:
                    raise ValidationException(
                        f"Team {winner.team_id} is not assigned to this match"
                    )
                existing_entity = await self.winner_repo.get_by_match_and_team(
                    match_id, winner.team_id
                )
            else:
                slot = await self.slot_repo.get_by_match_and_participant(
                    match_id, winner.participant_id
                )
                if slot is None:
                    raise ValidationException(
                        f"Participant {winner.participant_id} is not assigned to this match"
                    )
                existing_entity = await self.winner_repo.get_by_match_and_participant(
                    match_id, winner.participant_id
                )

            existing_rank = await self.winner_repo.get_by_match_and_rank(match_id, winner.rank)
            same_entity_same_rank = existing_entity is not None and existing_entity.rank == winner.rank
            if (existing_entity is not None or existing_rank) and not same_entity_same_rank:
                raise ConflictException(
                    f"Rank {winner.rank} or the given team/participant is already assigned a winner"
                )
            if same_entity_same_rank:
                created.append(existing_entity)
                continue

            match_winner = await self.winner_repo.create(
                match_id=match_id,
                match_result_id=result.id,
                tournament_id=match.tournament_id,
                team_id=winner.team_id,
                participant_id=winner.participant_id,
                rank=winner.rank,
                is_tie=winner.is_tie,
                assignment_source=WinnerAssignmentSource.MANUAL,
                is_manual_override=True,
                declared_by=current_user.id,
                declared_at=now,
            )
            created.append(match_winner)

        if any(w.is_tie for w in created) and not result.is_tie:
            await self.result_repo.update(result, is_tie=True)

        await self.audit.record(
            entity=_WINNER_ENTITY,
            action=AuditAction.CREATE,
            entity_id=match_id,
            actor=current_user,
            new_values={"winners": [str(w.id) for w in created], "source": "manual"},
            description=f"Winners manually declared for match {match_id}",
        )
        await self.session.commit()
        for w in created:
            await self.session.refresh(w)

        await self._notify_winners(created)

        return created

    async def list_match_winners(self, match_id: UUID) -> list[MatchWinner]:
        await self._get_match(match_id)
        return list(await self.winner_repo.list_for_match(match_id))

    # ==================================================================
    # 4. Approve -> automatic winner selection -> prize distribution
    # ==================================================================
    async def approve_result(self, match_id: UUID, current_user: User) -> MatchResult:
        if not self._is_admin(current_user):
            raise ForbiddenException("Only an admin can approve a match result")

        match, tournament = await self._get_match_and_tournament(match_id)
        result = await self.get_result(match_id)

        if result.status == MatchResultStatus.APPROVED:
            # Idempotent no-op — safe to retry an approve call.
            return result
        self._assert_valid_transition(result.status, MatchResultStatus.APPROVED)

        result = await self.result_repo.update(
            result,
            status=MatchResultStatus.APPROVED,
            approved_by=current_user.id,
            approved_at=datetime.now(timezone.utc),
        )

        winners = await self.winner_repo.list_for_match(match_id)
        if not winners:
            winners = await self.auto_select_winners(match_id, current_user)
            result = await self.result_repo.get_by_match_id(match_id)

        await self.audit.record(
            entity=_RESULT_ENTITY,
            action=AuditAction.STATUS_CHANGE,
            entity_id=result.id,
            actor=current_user,
            new_values={"status": MatchResultStatus.APPROVED.value},
            description=f"Match result approved for match {match_id}",
        )
        await self.session.commit()
        await self.session.refresh(result)

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
                    event_type=NotificationEventType.MATCH_RESULT_APPROVED,
                    title="Match result approved",
                    body=f"The result for match {match.match_number} in '{tournament.title}' has been approved.",
                    event_key_prefix=f"match_result_approved:{result.id}",
                )
        except Exception:  # noqa: BLE001
            pass

        await self._trigger_prize_distribution(match, result, current_user)

        await self.session.refresh(result)
        return result

    async def _trigger_prize_distribution(
        self, match: Match, result: MatchResult, admin: User
    ) -> None:
        """Exactly-once, atomic trigger into the Phase 10 prize system.
        Locks the MatchResult row so concurrent approve/retry calls can
        never assign winners or distribute payouts twice."""
        locked = await self.result_repo.get_by_id_for_update(result.id)
        if locked is None or locked.prize_distribution_triggered:
            return  # Already triggered (or result vanished) — no-op.

        pool = await self.prize_service.pool_repo.get_by_tournament_id(match.tournament_id)
        if pool is None:
            return  # No prize pool configured for this tournament — nothing to do.

        winners = await self.winner_repo.list_for_match(match.id)
        if not winners:
            return

        winner_payloads: list[dict] = []
        for w in winners:
            participant_id = w.participant_id
            if participant_id is None and w.team_id is not None:
                participant_id = await self._resolve_captain_participant_id(w.team_id)
            if participant_id is None:
                continue
            winner_payloads.append({"rank": w.rank, "participant_id": participant_id})

        if not winner_payloads:
            return

        try:
            await self.prize_service.assign_winners(
                tournament_id=match.tournament_id, admin=admin, winners=winner_payloads
            )
            await self.prize_service.distribute_prizes(tournament_id=match.tournament_id, admin=admin)
        finally:
            # Mark as triggered regardless of partial failure inside
            # PrizeService (it already leaves failed payouts retryable via
            # its own admin endpoints) so this trigger is never re-run
            # automatically for the same match result.
            locked = await self.result_repo.get_by_id_for_update(result.id)
            if locked is not None and not locked.prize_distribution_triggered:
                await self.result_repo.update(
                    locked,
                    prize_distribution_triggered=True,
                    prize_distribution_triggered_at=datetime.now(timezone.utc),
                )
                await self.audit.record(
                    entity=_RESULT_ENTITY,
                    action=AuditAction.OTHER,
                    entity_id=result.id,
                    actor=admin,
                    actor_type=AuditActorType.SYSTEM,
                    new_values={"prize_distribution_triggered": True},
                    description=f"Prize distribution triggered for match {match.id}",
                )
                await self.session.commit()

    # ==================================================================
    # 5. Listing / pagination / filtering / sorting
    # ==================================================================
    async def list_results(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        tournament_id: Optional[UUID] = None,
        match_id: Optional[UUID] = None,
        status: Optional[MatchResultStatus] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[Sequence[MatchResult], int]:
        return await self.result_repo.list_paginated(
            page=page,
            page_size=page_size,
            tournament_id=tournament_id,
            match_id=match_id,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    # ==================================================================
    # 6. History (Match Result History / Winner History)
    # ==================================================================
    async def get_result_history(self, match_id: UUID) -> list[AuditLog]:
        result = await self.get_result(match_id)
        return list(await self.audit.repository.list_for_entity(_RESULT_ENTITY, str(result.id)))

    async def get_winner_history(self, match_id: UUID) -> list[AuditLog]:
        await self._get_match(match_id)
        return list(await self.audit.repository.list_for_entity(_WINNER_ENTITY, str(match_id)))
