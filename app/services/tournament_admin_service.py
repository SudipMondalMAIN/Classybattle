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

from app.core.exceptions import NotFoundException, ValidationException
from app.models.notification import NotificationEventType
from app.models.tournament import Tournament
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
        their own. This builds result_data from whichever slots already
        have a rank set (solo participant_id, or one row per winning
        team) and drives the pipeline straight through in one call.
        """
        tournament, _game = await self._get_tournament_and_game(tournament_id)
        slots = await self.slot_repo.list_for_tournament(tournament.id)

        result_data: list[dict] = []
        for slot in slots:
            if slot.participant_id and slot.participant is not None:
                if slot.rank is not None:
                    result_data.append(
                        {"participant_id": str(slot.participant_id), "placement": slot.rank}
                    )
            elif slot.tournament_team_id and slot.tournament_team is not None:
                # Squad: rank/is_winner live per-member, but a whole team
                # shares one rank -- take it from whichever member has one
                # set (declare_result always writes the same rank to a
                # team's members together) and emit a single row keyed by
                # team_id, matching TournamentWinner's one-row-per-team shape.
                team = slot.tournament_team
                team_rank = next((m.rank for m in team.members if m.rank is not None), None)
                if team_rank is not None:
                    result_data.append({"team_id": str(team.id), "placement": team_rank})

        if not result_data:
            raise ValidationException(
                "No winners have been declared yet -- set a rank for at least one "
                "player/team on this tournament before publishing a result."
            )

        result_service = TournamentResultService(self.session)
        result = await result_service.submit_result(
            tournament_id, result_data=result_data, is_tie=False, current_user=current_user
        )
        result = await result_service.verify_result(result.id, current_user)
        result = await result_service.approve_result(result.id, current_user)
        return result

    async def pay_winner(
        self, tournament_id: UUID, user_id: UUID, *, amount: Decimal, note: Optional[str],
        current_user: User, commit: bool = True,
    ):
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
                # pay_winner's own commit flag or its internal commit
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