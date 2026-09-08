"""
Tournament Admin Service (formerly Match Admin Service) — powers the admin
"tournament details" page: who joined (with their game nickname/UID),
kills, winner declaration, and paying out the winning amount straight to
the player's wallet.

Match-refactor: Match and its parent schedule are now the same row
(`Tournament`), so there is no separate schedule lookup any more.
"""
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_delete_prefix
from app.core.exceptions import NotFoundException, ValidationException
from app.models.notification import NotificationEventType
from app.models.tournament import PrizeType, Tournament, TournamentStatus
from app.models.tournament_participant import TournamentParticipant
from app.models.user import User
from app.notifications.dispatch_service import NotificationDispatchService
from app.repositories.game_repository import GameRepository, UserGameProfileRepository
from app.repositories.tournament_participant_repository import TournamentParticipantRepository
from app.repositories.tournament_repository import TournamentRepository
from app.schemas.tournament_admin import MatchAdminDetailRead, MatchAdminPlayerRead, PlayerActionRead
from app.services.tournament_result_service import TournamentResultService
from app.services.wallet_service import WalletService

_WALLET_WINNING_REF_TYPE = "tournament_winning_payout"


class TournamentAdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tournament_repo = TournamentRepository(session)
        self.game_repo = GameRepository(session)
        self.game_profile_repo = UserGameProfileRepository(session)
        self.slot_repo = TournamentParticipantRepository(session)
        self.wallet_service = WalletService(session)

    async def _get_tournament_and_game(self, tournament_id: UUID):
        tournament = await self.tournament_repo.get_by_id(tournament_id)
        if tournament is None:
            raise NotFoundException("Tournament not found")
        game = await self.game_repo.get_by_id(tournament.game_id)
        return tournament, game

    async def get_tournament_details(self, tournament_id: UUID) -> MatchAdminDetailRead:
        tournament, game = await self._get_tournament_and_game(tournament_id)
        slots = await self.slot_repo.list_for_tournament(tournament.id)

        players: list[MatchAdminPlayerRead] = []
        for slot in slots:
            if slot.participant_id and slot.participant is not None:
                # Solo join.
                user = slot.participant.user
                profile = await self.game_profile_repo.get_by_user_and_game(user.id, game.id)
                players.append(
                    MatchAdminPlayerRead(
                        user_id=user.id,
                        full_name=user.full_name,
                        phone_number=user.phone_number,
                        game_nickname=(profile.data or {}).get("nickname") if profile else None,
                        game_uid=(profile.data or {}).get("uid") if profile else None,
                        team_name=None,
                        team_id=None,
                        kills=slot.kills,
                        is_winner=slot.is_winner,
                        rank=slot.rank,
                        winning_amount=slot.winning_amount,
                        winning_paid_at=slot.winning_paid_at,
                        joined_at=slot.created_at,
                    )
                )
            elif slot.tournament_team_id and slot.tournament_team is not None:
                # Squad join — one row per team member.
                for member in slot.tournament_team.members:
                    user = member.user
                    profile = await self.game_profile_repo.get_by_user_and_game(user.id, game.id)
                    players.append(
                        MatchAdminPlayerRead(
                            user_id=user.id,
                            full_name=user.full_name,
                            phone_number=user.phone_number,
                            game_nickname=(profile.data or {}).get("nickname") if profile else None,
                            game_uid=(profile.data or {}).get("uid") if profile else None,
                            team_name=slot.tournament_team.team_name,
                            team_id=slot.tournament_team.id,
                            kills=member.kills,
                            is_winner=member.is_winner,
                            rank=member.rank,
                            winning_amount=member.winning_amount,
                            winning_paid_at=member.winning_paid_at,
                            joined_at=member.created_at,
                        )
                    )

        return MatchAdminDetailRead(
            id=tournament.id,
            short_id=tournament.short_id,
            match_uid=tournament.tournament_uid,
            game_id=game.id,
            game_name=game.name,
            category=tournament.category.value if tournament.category else None,
            team_format=None,
            scheduled_start=tournament.published_at,
            match_status=tournament.status.value,
            room_id=tournament.room_id,
            room_password=tournament.room_password,
            entry_fee=tournament.entry_fee,
            prize_pool=tournament.prize_pool,
            total_joined=len(players),
            max_players=tournament.max_players,
            players=players,
        )

    async def _find_player_slot(self, tournament_id: UUID, user_id: UUID):
        """Returns ('solo', TournamentParticipant) or ('squad', TournamentTeamMember)
        for this user in this tournament, or raises NotFoundException."""
        slots = await self.slot_repo.list_for_tournament(tournament_id)
        for slot in slots:
            if slot.participant_id and slot.participant is not None and slot.participant.user_id == user_id:
                return "solo", slot
            if slot.tournament_team_id and slot.tournament_team is not None:
                for member in slot.tournament_team.members:
                    if member.user_id == user_id:
                        return "squad", member
        raise NotFoundException("This user did not join this tournament")

    async def declare_result(
        self,
        tournament_id: UUID,
        user_id: UUID,
        *,
        kills: Optional[int],
        is_winner: Optional[bool],
        rank: Optional[int] = None,
        commit: bool = True,
    ):
        kind, row = await self._find_player_slot(tournament_id, user_id)
        update_data = {}
        if kills is not None:
            update_data["kills"] = kills
        if is_winner is not None:
            update_data["is_winner"] = is_winner
            # Clearing winner status also clears any rank it had.
            if is_winner is False and rank is None:
                update_data["rank"] = None
        if rank is not None:
            if rank < 1:
                raise ValidationException("Rank must be 1 or greater")
            update_data["rank"] = rank
            # Setting a rank implicitly marks the player as a winner.
            update_data.setdefault("is_winner", True)
        if update_data:
            if kind == "solo":
                row = await self.slot_repo.update(row, **update_data)
            else:
                from app.repositories.base import BaseRepository
                from app.models.tournament_team import TournamentTeamMember

                repo = BaseRepository(self.session, TournamentTeamMember)
                row = await repo.update(row, **update_data)

            if commit:
                await self.session.commit()
            else:
                await self.session.flush()
            await self.session.refresh(row)

            # Newly marked a winner -> let the player know right away,
            # otherwise they have no way of finding out they won.
            if update_data.get("is_winner") is True:
                from app.repositories.user_repository import UserRepository

                user = await UserRepository(self.session).get_by_id(user_id)
                if user is not None:
                    tournament, _game = await self._get_tournament_and_game(tournament_id)
                    rank_txt = f" (Rank #{row.rank})" if row.rank else ""
                    try:
                        await NotificationDispatchService(self.session).dispatch(
                            user=user,
                            event_type=NotificationEventType.WINNER_DECLARED,
                            title="You won! 🏆",
                            body=(
                                f"Congratulations! You've been declared a winner{rank_txt} "
                                f"in {tournament.title}. Your prize will be credited to your "
                                f"wallet shortly."
                            ),
                            event_key=f"winner_declared:{tournament_id}:{user_id}",
                            send_email=False,
                            meta_data={"tournament_id": str(tournament_id)},
                            # Must match declare_result's own commit flag —
                            # otherwise this notification's internal commit
                            # releases any row lock the caller (e.g. a
                            # locked 1v1 auto-resolve) is still holding.
                            commit=commit,
                        )
                    except Exception:  # noqa: BLE001 - never block result declaration
                        pass

        return PlayerActionRead(
            user_id=user_id,
            kills=row.kills,
            is_winner=row.is_winner,
            rank=row.rank,
            winning_amount=row.winning_amount,
            winning_paid_at=row.winning_paid_at,
        )

    async def publish_result(self, tournament_id: UUID, current_user: User):
        """
        One-click bridge from this page's simple kills/is_winner/rank
        declarations to the formal TournamentResult submit -> verify ->
        approve pipeline (see TournamentResultService) that the public
        result site / Export JPG actually reads from.

        Without this, an admin could declare winners here forever and
        Export JPG would still 404 with "No published result for this
        tournament" -- the two systems never talk to each other on
        their own.

        Which rows qualify depends on the tournament's own prize_type,
        so admins are never forced to fill in a field their prize type
        doesn't use:
          RANK      -> rows with a rank set.
          WIN       -> rows ticked "Winner?" (rank not required).
          PER_KILL  -> rows with kills > 0 (no winner/rank required).
        """
        tournament, _game = await self._get_tournament_and_game(tournament_id)
        slots = await self.slot_repo.list_for_tournament(tournament.id)

        result_data: list[dict] = []

        def _team_rank(team) -> Optional[int]:
            return next((m.rank for m in team.members if m.rank is not None), None)

        def _team_is_winner(team) -> bool:
            return any(m.is_winner for m in team.members)

        def _team_kills(team) -> int:
            return sum((m.kills or 0) for m in team.members)

        if tournament.prize_type == PrizeType.RANK:
            # Rank-based: only rows an admin actually assigned a rank to.
            for slot in slots:
                if slot.participant_id and slot.participant is not None:
                    if slot.rank is not None:
                        result_data.append(
                            {"participant_id": str(slot.participant_id), "placement": slot.rank}
                        )
                elif slot.tournament_team_id and slot.tournament_team is not None:
                    team = slot.tournament_team
                    team_rank = _team_rank(team)
                    if team_rank is not None:
                        result_data.append({"team_id": str(team.id), "placement": team_rank})
            if not result_data:
                raise ValidationException(
                    "No winners have been declared yet -- set a rank for at least one "
                    "player/team on this tournament before publishing a result."
                )

        elif tournament.prize_type == PrizeType.WIN:
            # Flat win payout: whoever is ticked "Winner?" -- no rank required.
            # They all share placement 1 since there's no ordering between them.
            for slot in slots:
                if slot.participant_id and slot.participant is not None:
                    if slot.is_winner:
                        result_data.append(
                            {"participant_id": str(slot.participant_id), "placement": slot.rank or 1}
                        )
                elif slot.tournament_team_id and slot.tournament_team is not None:
                    team = slot.tournament_team
                    if _team_is_winner(team):
                        result_data.append(
                            {"team_id": str(team.id), "placement": _team_rank(team) or 1}
                        )
            if not result_data:
                raise ValidationException(
                    "No winners have been marked yet -- tick \"Winner?\" for at least one "
                    "player/team on this tournament before publishing a result."
                )

        elif tournament.prize_type == PrizeType.PER_KILL:
            # Per-kill payout: every row with kills > 0 gets paid regardless
            # of winner/rank. Rank them by kills for the record only.
            rows: list[tuple] = []
            for slot in slots:
                if slot.participant_id and slot.participant is not None:
                    if (slot.kills or 0) > 0:
                        rows.append(("participant_id", str(slot.participant_id), slot.kills or 0, slot.rank))
                elif slot.tournament_team_id and slot.tournament_team is not None:
                    team = slot.tournament_team
                    kills = _team_kills(team)
                    if kills > 0:
                        rows.append(("team_id", str(team.id), kills, _team_rank(team)))
            rows.sort(key=lambda r: r[2], reverse=True)
            for placement, (key, ident, _kills, existing_rank) in enumerate(rows, start=1):
                result_data.append({key: ident, "placement": existing_rank or placement})
            if not result_data:
                raise ValidationException(
                    "No kills have been recorded yet -- enter kills for at least one "
                    "player/team on this tournament before publishing a result."
                )

        else:
            raise ValidationException(
                "This tournament has no valid prize type configured -- set one before "
                "publishing a result."
            )

        result_service = TournamentResultService(self.session)
        result = await result_service.submit_result(
            tournament_id, result_data=result_data, is_tie=False, current_user=current_user
        )
        result = await result_service.verify_result(result.id, current_user)
        result = await result_service.approve_result(result.id, current_user)

        # Publishing a result here is the *actual* "this tournament is
        # done" signal on the admin page -- but until now it never
        # touched Tournament.status. Status only flipped LIVE->COMPLETED
        # via the 40-min auto-complete scheduler tick, so a tournament
        # whose result was published *before* that tick stayed LIVE/
        # SCHEDULED: it kept cluttering the "Tournaments" (ongoing) list
        # and never showed up under Tournament Results (which filters
        # on status=='completed'). Force it to COMPLETED here so both
        # panels reflect reality immediately instead of waiting on the
        # scheduler.
        if tournament.status != TournamentStatus.COMPLETED:
            await self.tournament_repo.update(
                tournament,
                status=TournamentStatus.COMPLETED,
                auto_complete_at=None,
            )
            await self.session.commit()
            await cache_delete_prefix("tournament:")

        # Automatic payout — this is the whole point of "one-click
        # publish": the ₹ amounts are already configured on the
        # tournament (rank_prize_rules / per_kill_amount / win_amount),
        # so the moment the admin confirms results here, every eligible
        # player/team gets credited straight away. No separate manual
        # "enter amount and pay" step needed. Safe to re-run (already
        # paid rows are skipped), so a retried publish never double-pays.
        try:
            await self.auto_pay_all(tournament_id, current_user, commit=True)
        except Exception:  # noqa: BLE001 - a payout hiccup must never hide the published result
            pass

        return result

    async def pay_winner(
        self, tournament_id: UUID, user_id: UUID, *, amount: Decimal, note: Optional[str],
        current_user: User, commit: bool = True,
    ):
        """Manual/override payout — admin types the amount themselves.
        For the normal flow, prefer publish_result(), which pays everyone
        automatically from the tournament's configured prize_type instead
        of requiring this per-player manual entry."""
        kind, row = await self._find_player_slot(tournament_id, user_id)
        if not row.is_winner:
            raise ValidationException(
                "This player is not declared a winner yet — declare them a winner first."
            )
        if row.winning_paid_at is not None:
            raise ValidationException("This player has already been paid for this tournament.")

        from app.repositories.user_repository import UserRepository

        user = await UserRepository(self.session).get_by_id(user_id)
        if user is None:
            raise NotFoundException("User not found")

        return await self._credit_player(
            tournament_id=tournament_id,
            user=user,
            kind=kind,
            row=row,
            amount=amount,
            note=note,
            commit=commit,
        )

    # ------------------------------------------------------------------
    # Shared settlement primitive — used by both the manual pay_winner()
    # override above and the automatic prize_type-driven payout below.
    # ------------------------------------------------------------------
    async def _credit_player(
        self, *, tournament_id: UUID, user: User, kind: str, row, amount: Decimal,
        note: Optional[str], commit: bool,
    ) -> PlayerActionRead:
        user_id = user.id
        await self.wallet_service.credit(
            user,
            amount=amount,
            reference_type=_WALLET_WINNING_REF_TYPE,
            reference_id=f"{tournament_id}:{user_id}",
            description=note or f"Winning amount for tournament {tournament_id}",
            commit=False,
        )

        from datetime import datetime, timezone

        update_data = {"winning_amount": amount, "winning_paid_at": datetime.now(timezone.utc)}
        if kind == "solo":
            row = await self.slot_repo.update(row, **update_data)
        else:
            from app.repositories.base import BaseRepository
            from app.models.tournament_team import TournamentTeamMember

            repo = BaseRepository(self.session, TournamentTeamMember)
            row = await repo.update(row, **update_data)

        if commit:
            await self.session.commit()
        else:
            await self.session.flush()
        await self.session.refresh(row)

        tournament, _game = await self._get_tournament_and_game(tournament_id)

        # Fold this paid win into leaderboard/statistics -- this admin
        # flow never goes through TournamentResult approve, which is the
        # only other place statistics get updated. See
        # LeaderboardService.record_admin_winner_payout for why this is
        # the right (idempotent) point to hook it in.
        try:
            from app.services.leaderboard_service import LeaderboardService

            await LeaderboardService(self.session).record_admin_winner_payout(
                tournament_id=tournament_id,
                user_id=user_id,
                kills=row.kills or 0,
                rank=row.rank,
                amount=amount,
                commit=commit,
            )
        except Exception:  # noqa: BLE001 - leaderboard stats must never block a payout
            pass

        try:
            await NotificationDispatchService(self.session).dispatch(
                user=user,
                event_type=NotificationEventType.PRIZE_DISTRIBUTED,
                title="Prize credited 💰",
                body=(
                    f"₹{amount} has been credited to your wallet as your winning prize "
                    f"for {tournament.title}."
                ),
                event_key=f"prize_distributed:{tournament_id}:{user_id}",
                send_email=False,
                meta_data={"tournament_id": str(tournament_id)},
                # Same reasoning as in declare_result() above — must match
                # the caller's own commit flag or this internal commit
                # releases the caller's still-held row lock early.
                commit=commit,
            )
        except Exception:  # noqa: BLE001 - never block the payout itself
            pass

        return PlayerActionRead(
            user_id=user_id,
            kills=row.kills,
            is_winner=row.is_winner,
            rank=row.rank,
            winning_amount=row.winning_amount,
            winning_paid_at=row.winning_paid_at,
        )

    def _auto_amount_for_row(self, tournament: Tournament, row) -> Decimal:
        """Computes the payout for one player/team row purely from the
        tournament's own configured prize_type -- no admin-entered amount
        needed, since the ₹ rules were already set up front:

        RANK      -> rank_prize_rules[{'rank': n, 'amount': x}, ...] matched
                     against this row's rank.
        PER_KILL  -> kills * per_kill_amount, for every row with kills > 0
                     (a per-kill payout doesn't require is_winner).
        WIN       -> a flat win_amount, only for rows marked is_winner.
        """
        if tournament.prize_type == PrizeType.RANK:
            if row.rank is None or not tournament.rank_prize_rules:
                return Decimal("0")
            for rule in tournament.rank_prize_rules:
                if int(rule.get("rank", -1)) == row.rank:
                    return Decimal(str(rule.get("amount", 0)))
            return Decimal("0")

        if tournament.prize_type == PrizeType.PER_KILL:
            kills = row.kills or 0
            if kills <= 0 or not tournament.per_kill_amount:
                return Decimal("0")
            return Decimal(str(tournament.per_kill_amount)) * Decimal(kills)

        if tournament.prize_type == PrizeType.WIN:
            if not row.is_winner or not tournament.win_amount:
                return Decimal("0")
            return Decimal(str(tournament.win_amount))

        return Decimal("0")

    async def auto_pay_all(self, tournament_id: UUID, current_user: User, commit: bool = True):
        """Pays every eligible player/team member automatically, using
        only the tournament's pre-configured prize_type rules -- no
        amount is ever typed in by the admin. Rows with ₹0 computed
        amount or that are already paid are silently skipped, so this is
        safe to call repeatedly (e.g. if publish_result is retried)."""
        tournament, _game = await self._get_tournament_and_game(tournament_id)
        slots = await self.slot_repo.list_for_tournament(tournament.id)

        from app.repositories.user_repository import UserRepository

        user_repo = UserRepository(self.session)
        paid: list[PlayerActionRead] = []
        skipped: list[dict] = []

        async def _maybe_pay(kind: str, row, user_id: UUID):
            if row.winning_paid_at is not None:
                return
            amount = self._auto_amount_for_row(tournament, row)
            if amount <= 0:
                skipped.append({"user_id": str(user_id), "reason": "no amount due"})
                return
            user = await user_repo.get_by_id(user_id)
            if user is None:
                skipped.append({"user_id": str(user_id), "reason": "user not found"})
                return
            result = await self._credit_player(
                tournament_id=tournament_id,
                user=user,
                kind=kind,
                row=row,
                amount=amount,
                note=f"Automatic {tournament.prize_type.value} payout for {tournament.title}",
                commit=commit,
            )
            paid.append(result)

        for slot in slots:
            if slot.participant_id and slot.participant is not None:
                await _maybe_pay("solo", slot, slot.participant.user_id)
            elif slot.tournament_team_id and slot.tournament_team is not None:
                for member in slot.tournament_team.members:
                    await _maybe_pay("squad", member, member.user_id)

        return {"paid": paid, "skipped": skipped}