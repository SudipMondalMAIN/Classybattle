"""
Custom Match Claim Service (Phase 19) -- lets the two players in a 1v1
Custom Tournament self-report the result instead of an admin refereeing
it, per the rules described on the CustomMatchClaim model:

  * Claim LOSS  -> no proof needed, instantly declares + pays the
                   *other* player as the winner.
  * Claim WIN   -> proof screenshot required, stays PENDING_REVIEW
                   until the opponent's own claim confirms it (they
                   claim LOSS) or an admin approves it.
  * Both WIN    -> genuine dispute, both stay PENDING_REVIEW for an
                   admin to resolve via approve/reject.

Only usable on Custom Tournaments (Tournament.category IS NULL) with
exactly 2 solo players -- squad/duo custom tournaments and admin-run
schedule tournaments keep using the existing admin declare/pay flow in
TournamentAdminService, which this service delegates the actual
is_winner + wallet-credit mechanics to, so both paths share one payout
implementation.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, NotFoundException, ValidationException
from app.core.logging import get_logger
from app.models.custom_match_claim import (
    CustomMatchClaim,
    CustomMatchClaimOutcome,
    CustomMatchClaimStatus,
)
from app.models.tournament import TeamRegistrationMode
from app.models.user import User, UserRole
from app.repositories.custom_match_claim_repository import CustomMatchClaimRepository
from app.repositories.tournament_participant_repository import TournamentParticipantRepository
from app.repositories.tournament_repository import TournamentRepository
from app.repositories.user_repository import UserRepository
from app.schemas.custom_match_claim import CustomMatchClaimPairRead, PendingClaimAdminRead
from app.services.tournament_admin_service import TournamentAdminService

logger = get_logger("custom_match_claim")


def _is_admin(user: User) -> bool:
    return user.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN)


class CustomMatchClaimService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.claim_repo = CustomMatchClaimRepository(session)
        self.tournament_repo = TournamentRepository(session)
        self.slot_repo = TournamentParticipantRepository(session)
        self.user_repo = UserRepository(session)
        self.admin_service = TournamentAdminService(session)

    # ------------------------------------------------------------------
    # Shared guards
    # ------------------------------------------------------------------
    async def _get_eligible_tournament(self, tournament_id: UUID):
        tournament = await self.tournament_repo.get_by_id(tournament_id)
        if tournament is None:
            raise NotFoundException("Tournament not found")
        if tournament.category is not None:
            raise ValidationException(
                "Self-declared results are only available for Custom Tournaments."
            )
        if tournament.registration_mode != TeamRegistrationMode.SOLO or tournament.max_players != 2:
            raise ValidationException(
                "Self-declared results currently only support 1v1 (solo, 2-player) "
                "Custom Tournaments. Squad custom tournaments still go through admin review."
            )
        if tournament.room_id is None:
            raise ValidationException(
                "Wait for the room ID to be shared before submitting a result."
            )
        return tournament

    async def _get_opponent_user_id(self, tournament_id: UUID, user_id: UUID) -> UUID:
        slots = await self.slot_repo.list_for_tournament(tournament_id)
        participant_user_ids = [
            slot.participant.user_id
            for slot in slots
            if slot.participant_id and slot.participant is not None
        ]
        if user_id not in participant_user_ids:
            raise ForbiddenException("You are not a participant in this tournament.")
        others = [uid for uid in participant_user_ids if uid != user_id]
        if len(others) != 1:
            raise ValidationException(
                "Couldn't determine your opponent -- this tournament doesn't have "
                "exactly 2 joined players yet."
            )
        return others[0]

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------
    async def submit_claim(
        self,
        tournament_id: UUID,
        *,
        current_user: User,
        outcome: CustomMatchClaimOutcome,
        proof_url: Optional[str],
    ) -> CustomMatchClaimPairRead:
        tournament = await self._get_eligible_tournament(tournament_id)
        opponent_id = await self._get_opponent_user_id(tournament_id, current_user.id)

        if outcome == CustomMatchClaimOutcome.WIN and not proof_url:
            raise ValidationException("Proof (screenshot) is required when claiming a win.")

        now = datetime.now(timezone.utc)
        existing = await self.claim_repo.get_by_tournament_and_user(
            tournament_id, current_user.id
        )
        if existing is not None and existing.status not in (
            CustomMatchClaimStatus.PENDING_REVIEW,
            CustomMatchClaimStatus.REJECTED,
        ):
            raise ValidationException("This match's result has already been resolved.")

        # Bug fix: the check above only guards against the *current
        # user's own* claim being re-submitted after resolution. It
        # missed the case where the opponent's claim already resolved
        # the match (e.g. opponent claimed LOSS and was auto-paid) but
        # this user had never submitted anything yet (existing is None
        # here). Without this guard, this user could still submit a
        # fresh LOSS claim afterwards and trigger a second payout to
        # their opponent -- letting both players get paid.
        opponent_claim_precheck = await self.claim_repo.get_by_tournament_and_user(
            tournament_id, opponent_id
        )
        if opponent_claim_precheck is not None and opponent_claim_precheck.status in (
            CustomMatchClaimStatus.AUTO_RESOLVED,
            CustomMatchClaimStatus.ADMIN_APPROVED,
        ):
            raise ValidationException("This match's result has already been resolved.")

        if existing is None:
            claim = await self.claim_repo.create(
                tournament_id=tournament_id,
                user_id=current_user.id,
                outcome=outcome,
                proof_url=proof_url,
                status=CustomMatchClaimStatus.PENDING_REVIEW,
                submitted_at=now,
            )
        else:
            claim = await self.claim_repo.update(
                existing,
                outcome=outcome,
                proof_url=proof_url,
                status=CustomMatchClaimStatus.PENDING_REVIEW,
                submitted_at=now,
                resolved_at=None,
                resolved_by=None,
                rejection_reason=None,
            )
        await self.session.commit()
        await self.session.refresh(claim)

        opponent_claim = await self.claim_repo.get_by_tournament_and_user(
            tournament_id, opponent_id
        )

        if outcome == CustomMatchClaimOutcome.LOSS:
            # No incentive to falsely confess a loss -- auto-crown and
            # pay the opponent immediately, no admin needed.
            await self._resolve_auto(
                tournament, player_a_id=current_user.id, player_b_id=opponent_id,
            )
        elif opponent_claim is not None and opponent_claim.outcome == CustomMatchClaimOutcome.LOSS:
            # Opponent already confessed the loss -- this WIN claim is
            # confirmed, no need to wait for admin review.
            await self._resolve_auto(
                tournament, player_a_id=current_user.id, player_b_id=opponent_id,
            )
        # else: both WIN (dispute) or opponent hasn't claimed yet ->
        # stays PENDING_REVIEW for an admin.

        return await self.get_claim_pair(tournament_id, current_user.id)

    async def _resolve_auto(self, tournament, *, player_a_id: UUID, player_b_id: UUID) -> None:
        # Compare-and-swap gate (see migration 0045 + the model comment
        # on Tournament.custom_result_resolving_at for the full story):
        # SELECT ... FOR UPDATE row locks and pg_advisory_lock both
        # failed to reliably serialize two near-simultaneous "I Lost"
        # submissions in production -- confirmed via wallet_transactions
        # showing both players paid for the same 1v1, even with the
        # advisory lock deployed. A single conditional UPDATE is atomic
        # at the row/MVCC level no matter how the pooler multiplexes
        # connections underneath it, so it doesn't depend on lock or
        # session continuity the way the previous approaches did.
        #
        # Whichever request's UPDATE actually flips the flag wins the
        # right to decide this match's outcome; the loser just returns
        # immediately -- it does NOT retry or raise, because the winner
        # is about to finalize *both* players' claims (see below), not
        # just the winner's own.
        result = await self.session.execute(
            text(
                "UPDATE tournaments SET custom_result_resolving_at = now() "
                "WHERE id = :id AND custom_result_resolving_at IS NULL "
                "RETURNING id"
            ),
            {"id": tournament.id},
        )
        won_gate = result.first() is not None
        # Commit immediately so the flag is visible to the other
        # request the instant it checks -- don't hold this open behind
        # whatever else this transaction might still be doing.
        await self.session.commit()
        if not won_gate:
            logger.info(
                "custom_result_gate_lost",
                tournament_id=str(tournament.id),
                player_a=str(player_a_id),
                player_b=str(player_b_id),
            )
            return

        try:
            await self._resolve_auto_locked(tournament, player_a_id=player_a_id, player_b_id=player_b_id)
        finally:
            # Gate is one-shot per tournament (resolution only ever
            # happens once) -- no need to release it for a retry. Left
            # set so a stray third request can never re-enter either.
            pass

    async def _resolve_auto_locked(self, tournament, *, player_a_id: UUID, player_b_id: UUID) -> None:
        # We hold exclusive resolution rights for this tournament now.
        # Re-read BOTH players' claims fresh -- do not trust whatever
        # the caller thought the outcome was, since that snapshot could
        # already be stale relative to what actually got committed by
        # the other player's concurrent request.
        claim_a = await self.claim_repo.get_by_tournament_and_user(tournament.id, player_a_id)
        claim_b = await self.claim_repo.get_by_tournament_and_user(tournament.id, player_b_id)

        a_lost = claim_a is not None and claim_a.outcome == CustomMatchClaimOutcome.LOSS
        b_lost = claim_b is not None and claim_b.outcome == CustomMatchClaimOutcome.LOSS

        now = datetime.now(timezone.utc)

        if a_lost and b_lost:
            # Both players claim they lost -- there's no honest winner
            # to pay here (this is exactly the near-simultaneous "both
            # tap Lost" case). Void the match: mark both claims
            # resolved, pay nobody.
            logger.info(
                "custom_result_double_loss_void",
                tournament_id=str(tournament.id),
                player_a=str(player_a_id),
                player_b=str(player_b_id),
            )
            await self.claim_repo.update(claim_a, status=CustomMatchClaimStatus.AUTO_RESOLVED, resolved_at=now)
            await self.claim_repo.update(claim_b, status=CustomMatchClaimStatus.AUTO_RESOLVED, resolved_at=now)
            await self.session.commit()
            return

        if a_lost:
            loser_claim, loser_id = claim_a, player_a_id
            winner_claim, winner_user_id = claim_b, player_b_id
        elif b_lost:
            loser_claim, loser_id = claim_b, player_b_id
            winner_claim, winner_user_id = claim_a, player_a_id
        else:
            # Neither has a LOSS claim (e.g. a WIN-confirmation call
            # raced ahead of the LOSS claim actually landing) -- nothing
            # to resolve yet. Re-open the gate so whichever call
            # eventually finds a real LOSS claim can win it and settle
            # the match; otherwise this would strand the gate closed
            # forever with the match never resolving.
            await self.session.execute(
                text(
                    "UPDATE tournaments SET custom_result_resolving_at = NULL WHERE id = :id"
                ),
                {"id": tournament.id},
            )
            await self.session.commit()
            return

        locked_tournament = await self.tournament_repo.get_by_id_for_update(tournament.id)
        if locked_tournament is None:
            raise NotFoundException("Tournament not found")

        already_paid = False
        try:
            _, slot = await self.admin_service._find_player_slot(tournament.id, winner_user_id)
            already_paid = slot.winning_paid_at is not None
        except NotFoundException:
            pass
        if not already_paid:
            slots = await self.slot_repo.list_for_tournament(tournament.id)
            already_paid = any(
                s.participant_id and s.participant is not None and s.winning_paid_at is not None
                for s in slots
            )

        if not already_paid:
            await self.admin_service.declare_result(
                tournament.id, winner_user_id, kills=None, is_winner=True, commit=False
            )
            winner_user = await self.user_repo.get_by_id(winner_user_id)
            if winner_user is not None:
                await self.admin_service.pay_winner(
                    locked_tournament.id,
                    winner_user_id,
                    amount=Decimal(locked_tournament.prize_pool),
                    note=f"Auto-approved result for '{locked_tournament.title}'",
                    current_user=winner_user,
                    commit=False,
                )

        if loser_claim is not None:
            await self.claim_repo.update(
                loser_claim, status=CustomMatchClaimStatus.AUTO_RESOLVED, resolved_at=now
            )
        if winner_claim is not None:
            await self.claim_repo.update(
                winner_claim, status=CustomMatchClaimStatus.AUTO_RESOLVED, resolved_at=now
            )
        await self.session.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    async def get_claim_pair(
        self, tournament_id: UUID, user_id: UUID
    ) -> CustomMatchClaimPairRead:
        opponent_id = await self._get_opponent_user_id(tournament_id, user_id)
        my_claim = await self.claim_repo.get_by_tournament_and_user(tournament_id, user_id)
        opponent_claim = await self.claim_repo.get_by_tournament_and_user(
            tournament_id, opponent_id
        )
        resolved = any(
            c is not None
            and c.status in (CustomMatchClaimStatus.AUTO_RESOLVED, CustomMatchClaimStatus.ADMIN_APPROVED)
            for c in (my_claim, opponent_claim)
        )
        return CustomMatchClaimPairRead(
            my_claim=my_claim, opponent_claim=opponent_claim, resolved=resolved
        )

    # ------------------------------------------------------------------
    # Admin review (only reached for genuine WIN/WIN disputes, or a WIN
    # claim whose opponent never submits anything).
    # ------------------------------------------------------------------
    async def list_pending(self, *, page: int = 1, page_size: int = 20):
        claims, total = await self.claim_repo.list_pending(page=page, page_size=page_size)
        items: list[PendingClaimAdminRead] = []
        for claim in claims:
            tournament = await self.tournament_repo.get_by_id(claim.tournament_id)
            claimant = await self.user_repo.get_by_id(claim.user_id)
            opponent_id = None
            opponent_name = None
            opponent_outcome = None
            try:
                opponent_id = await self._get_opponent_user_id(claim.tournament_id, claim.user_id)
                opp = await self.user_repo.get_by_id(opponent_id)
                opponent_name = opp.full_name if opp else None
                opponent_claim = await self.claim_repo.get_by_tournament_and_user(
                    claim.tournament_id, opponent_id
                )
                opponent_outcome = opponent_claim.outcome.value if opponent_claim else None
            except (NotFoundException, ValidationException):
                pass
            items.append(
                PendingClaimAdminRead(
                    id=claim.id,
                    tournament_id=claim.tournament_id,
                    user_id=claim.user_id,
                    outcome=claim.outcome.value,
                    proof_url=claim.proof_url,
                    status=claim.status.value,
                    submitted_at=claim.submitted_at,
                    resolved_at=claim.resolved_at,
                    rejection_reason=claim.rejection_reason,
                    tournament_title=tournament.title if tournament else "Unknown",
                    claimant_name=claimant.full_name if claimant else "Unknown",
                    opponent_user_id=opponent_id,
                    opponent_name=opponent_name,
                    opponent_outcome=opponent_outcome,
                )
            )
        return items, total

    async def approve(self, claim_id: UUID, admin: User) -> CustomMatchClaim:
        claim = await self.claim_repo.get_by_id(claim_id)
        if claim is None:
            raise NotFoundException("Claim not found")
        if claim.status != CustomMatchClaimStatus.PENDING_REVIEW:
            raise ValidationException(f"Cannot approve a claim with status '{claim.status.value}'")
        if claim.outcome != CustomMatchClaimOutcome.WIN:
            raise ValidationException("Only WIN claims need admin approval.")

        # Same advisory-lock + row-lock guard as the auto-resolve path
        # -- see _resolve_auto for why the advisory lock is needed in
        # addition to the row lock. Prevents an admin approval racing a
        # same-tournament auto-resolve (e.g. the opponent taps "Lost"
        # at the same moment) from paying out twice for one 1v1 match.
        lock_key = int(claim.tournament_id.int % (2**63))
        await self.session.execute(
            text("SELECT pg_advisory_lock(:key)"), {"key": lock_key}
        )
        try:
            return await self._approve_locked(claim, admin)
        finally:
            await self.session.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key}
            )

    async def _approve_locked(self, claim: CustomMatchClaim, admin: User) -> CustomMatchClaim:
        tournament = await self.tournament_repo.get_by_id_for_update(claim.tournament_id)
        if tournament is None:
            raise NotFoundException("Tournament not found")
        winner = await self.user_repo.get_by_id(claim.user_id)

        # Fail closed here too -- see the matching comment in
        # _resolve_auto. A swallowed exception must never be read as
        # "not paid yet".
        slots = await self.slot_repo.list_for_tournament(claim.tournament_id)
        already_paid = any(
            s.participant_id and s.participant is not None and s.winning_paid_at is not None
            for s in slots
        )

        if not already_paid:
            await self.admin_service.declare_result(
                claim.tournament_id, claim.user_id, kills=None, is_winner=True, commit=False
            )
            await self.admin_service.pay_winner(
                claim.tournament_id,
                claim.user_id,
                amount=Decimal(tournament.prize_pool),
                note=f"Admin-approved result for '{tournament.title}'",
                current_user=admin,
                commit=False,
            )

        now = datetime.now(timezone.utc)
        claim = await self.claim_repo.update(
            claim,
            status=CustomMatchClaimStatus.ADMIN_APPROVED,
            resolved_at=now,
            resolved_by=admin.id,
        )

        # If the opponent also claimed WIN (the dispute case), their
        # claim is now settled against them -- reject it automatically
        # so it doesn't linger in the review queue.
        opponent_id = await self._get_opponent_user_id(claim.tournament_id, claim.user_id)
        opponent_claim = await self.claim_repo.get_by_tournament_and_user(
            claim.tournament_id, opponent_id
        )
        if (
            opponent_claim is not None
            and opponent_claim.status == CustomMatchClaimStatus.PENDING_REVIEW
        ):
            await self.claim_repo.update(
                opponent_claim,
                status=CustomMatchClaimStatus.REJECTED,
                resolved_at=now,
                resolved_by=admin.id,
                rejection_reason="Opponent's claim was approved for this match instead.",
            )

        await self.session.commit()
        await self.session.refresh(claim)
        return claim

    async def reject(self, claim_id: UUID, *, reason: str, admin: User) -> CustomMatchClaim:
        claim = await self.claim_repo.get_by_id(claim_id)
        if claim is None:
            raise NotFoundException("Claim not found")
        if claim.status != CustomMatchClaimStatus.PENDING_REVIEW:
            raise ValidationException(f"Cannot reject a claim with status '{claim.status.value}'")

        claim = await self.claim_repo.update(
            claim,
            status=CustomMatchClaimStatus.REJECTED,
            resolved_at=datetime.now(timezone.utc),
            resolved_by=admin.id,
            rejection_reason=reason,
        )
        await self.session.commit()
        await self.session.refresh(claim)
        return claim