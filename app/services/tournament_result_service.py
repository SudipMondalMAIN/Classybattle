"""
Tournament Result Service (formerly Match Result Service) — Phase 11
submit -> verify -> approve / reject workflow for a Tournament's result,
now keyed on `tournament_id` instead of `match_id`.

This is the structured, auditable result-approval pipeline: one
TournamentResult row per Tournament, holding freeform per-slot
`result_data` (placement/score per participant or team). Approving a
result freezes it into TournamentWinner rows (one per rank) and folds
the outcome into leaderboard statistics exactly once
(``prize_distribution_triggered`` guards this against retries).

This is separate from — and does not replace — TournamentAdminService's
simpler per-player kills/is_winner/payout flow (Raj's admin
"tournament details" page) or PrizeService's explicit
assign_winners/distribute_prizes flow. Those remain the actual money
paths; this service only manages the formal result record.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, NotFoundException, ValidationException
from app.models.audit_log import AuditAction
from app.models.tournament_result import (
    TOURNAMENT_RESULT_STATUS_TRANSITIONS,
    TournamentResult,
    TournamentResultStatus,
)
from app.models.tournament_winner import TournamentWinner, WinnerAssignmentSource
from app.models.user import User, UserRole
from app.repositories.tournament_repository import TournamentRepository
from app.repositories.tournament_result_repository import TournamentResultRepository
from app.repositories.tournament_winner_repository import TournamentWinnerRepository
from app.services.audit_service import AuditService
from app.services.leaderboard_service import LeaderboardService


def _is_admin(user: User) -> bool:
    return user.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN)


class TournamentResultService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tournament_repo = TournamentRepository(session)
        self.result_repo = TournamentResultRepository(session)
        self.winner_repo = TournamentWinnerRepository(session)
        self.audit = AuditService(session)
        self.leaderboard_service = LeaderboardService(session)

    async def _get_tournament(self, tournament_id: UUID):
        tournament = await self.tournament_repo.get_by_id(tournament_id)
        if tournament is None:
            raise NotFoundException("Tournament not found")
        return tournament

    async def _get_result_for_update(self, result_id: UUID) -> TournamentResult:
        result = await self.result_repo.get_by_id_for_update(result_id)
        if result is None:
            raise NotFoundException("Tournament result not found")
        return result

    def _assert_transition(
        self, current: TournamentResultStatus, target: TournamentResultStatus
    ) -> None:
        allowed = TOURNAMENT_RESULT_STATUS_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValidationException(
                f"Cannot move a tournament result from '{current.value}' to '{target.value}'"
            )

    # ------------------------------------------------------------------
    # Submit — creates the one-per-tournament result row, or resubmits
    # a REJECTED one back to SUBMITTED.
    # ------------------------------------------------------------------
    async def submit_result(
        self,
        tournament_id: UUID,
        *,
        result_data: list,
        is_tie: bool,
        current_user: User,
    ) -> TournamentResult:
        tournament = await self._get_tournament(tournament_id)
        existing = await self.result_repo.get_by_match_id(tournament_id)

        now = datetime.now(timezone.utc)
        if existing is None:
            result = await self.result_repo.create(
                tournament_id=tournament.id,
                result_data=result_data,
                is_tie=is_tie,
                status=TournamentResultStatus.SUBMITTED,
                submitted_by=current_user.id,
                submitted_at=now,
            )
        else:
            self._assert_transition(existing.status, TournamentResultStatus.SUBMITTED)
            result = await self.result_repo.update(
                existing,
                result_data=result_data,
                is_tie=is_tie,
                status=TournamentResultStatus.SUBMITTED,
                submitted_by=current_user.id,
                submitted_at=now,
                rejected_by=None,
                rejected_at=None,
                rejection_reason=None,
            )

        await self.audit.record(
            entity="tournament_result",
            action=AuditAction.CREATE if existing is None else AuditAction.UPDATE,
            entity_id=result.id,
            actor=current_user,
            description=f"Result submitted for tournament '{tournament.title}'",
        )
        await self.session.commit()
        await self.session.refresh(result)
        return result

    # ------------------------------------------------------------------
    # Verify — a second pair of eyes before approval (SUBMITTED -> VERIFIED)
    # ------------------------------------------------------------------
    async def verify_result(self, result_id: UUID, current_user: User) -> TournamentResult:
        if not _is_admin(current_user):
            raise ForbiddenException("Only admins can verify tournament results")

        result = await self._get_result_for_update(result_id)
        self._assert_transition(result.status, TournamentResultStatus.VERIFIED)

        result = await self.result_repo.update(
            result,
            status=TournamentResultStatus.VERIFIED,
            verified_by=current_user.id,
            verified_at=datetime.now(timezone.utc),
        )
        await self.audit.record(
            entity="tournament_result",
            action=AuditAction.STATUS_CHANGE,
            entity_id=result.id,
            actor=current_user,
            new_values={"status": TournamentResultStatus.VERIFIED.value},
            description="Tournament result verified",
        )
        await self.session.commit()
        await self.session.refresh(result)
        return result

    # ------------------------------------------------------------------
    # Reject — SUBMITTED or VERIFIED -> REJECTED
    # ------------------------------------------------------------------
    async def reject_result(
        self, result_id: UUID, *, reason: str, current_user: User
    ) -> TournamentResult:
        if not _is_admin(current_user):
            raise ForbiddenException("Only admins can reject tournament results")

        result = await self._get_result_for_update(result_id)
        self._assert_transition(result.status, TournamentResultStatus.REJECTED)

        result = await self.result_repo.update(
            result,
            status=TournamentResultStatus.REJECTED,
            rejected_by=current_user.id,
            rejected_at=datetime.now(timezone.utc),
            rejection_reason=reason,
        )
        await self.audit.record(
            entity="tournament_result",
            action=AuditAction.STATUS_CHANGE,
            entity_id=result.id,
            actor=current_user,
            new_values={"status": TournamentResultStatus.REJECTED.value},
            description=f"Tournament result rejected: {reason}",
        )
        await self.session.commit()
        await self.session.refresh(result)
        return result

    # ------------------------------------------------------------------
    # Approve — VERIFIED -> APPROVED. Freezes result_data into
    # TournamentWinner rows and folds the outcome into leaderboard
    # statistics exactly once (idempotent via prize_distribution_triggered).
    # ------------------------------------------------------------------
    async def approve_result(self, result_id: UUID, current_user: User) -> TournamentResult:
        if not _is_admin(current_user):
            raise ForbiddenException("Only admins can approve tournament results")

        result = await self._get_result_for_update(result_id)
        self._assert_transition(result.status, TournamentResultStatus.APPROVED)

        tournament = await self._get_tournament(result.tournament_id)

        if not result.prize_distribution_triggered:
            await self.winner_repo.delete_all_for_match(result.tournament_id)
            now = datetime.now(timezone.utc)
            for entry in result.result_data or []:
                rank = entry.get("placement") or entry.get("rank")
                if rank is None:
                    continue
                await self.winner_repo.create(
                    tournament_id=result.tournament_id,
                    tournament_result_id=result.id,
                    team_id=entry.get("team_id"),
                    participant_id=entry.get("participant_id"),
                    rank=rank,
                    is_tie=result.is_tie,
                    assignment_source=WinnerAssignmentSource.AUTOMATIC,
                    declared_by=current_user.id,
                    declared_at=now,
                )

        result = await self.result_repo.update(
            result,
            status=TournamentResultStatus.APPROVED,
            approved_by=current_user.id,
            approved_at=datetime.now(timezone.utc),
        )

        winners = await self.winner_repo.list_for_tournament(result.tournament_id)
        if not result.prize_distribution_triggered:
            await self.leaderboard_service.record_match_completion(
                match=tournament, result=result, winners=winners
            )
            result = await self.result_repo.update(
                result,
                prize_distribution_triggered=True,
                prize_distribution_triggered_at=datetime.now(timezone.utc),
            )

        await self.audit.record(
            entity="tournament_result",
            action=AuditAction.STATUS_CHANGE,
            entity_id=result.id,
            actor=current_user,
            new_values={"status": TournamentResultStatus.APPROVED.value},
            description=f"Tournament result approved for '{tournament.title}'",
        )
        await self.session.commit()
        await self.session.refresh(result)
        return result

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    async def get_result(self, tournament_id: UUID) -> Optional[TournamentResult]:
        return await self.result_repo.get_by_match_id(tournament_id)

    async def list_results(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        tournament_id: Optional[UUID] = None,
        status: Optional[TournamentResultStatus] = None,
    ):
        return await self.result_repo.list_paginated(
            page=page, page_size=page_size, tournament_id=tournament_id, status=status
        )
