"""
Match Admin Service — powers the admin "match details" page: who
joined (with their game nickname/UID), kills, winner declaration, and
paying out the winning amount straight to the player's wallet.
"""
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.models.match import Match
from app.models.match_participant import MatchParticipant
from app.models.user import User
from app.repositories.game_repository import GameRepository, UserGameProfileRepository
from app.repositories.match_participant_repository import MatchParticipantRepository
from app.repositories.match_repository import MatchRepository
from app.repositories.tournament_repository import TournamentRepository
from app.schemas.match_admin import MatchAdminDetailRead, MatchAdminPlayerRead
from app.services.wallet_service import WalletService

_WALLET_WINNING_REF_TYPE = "match_winning_payout"


class MatchAdminService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.match_repo = MatchRepository(session)
        self.tournament_repo = TournamentRepository(session)
        self.game_repo = GameRepository(session)
        self.game_profile_repo = UserGameProfileRepository(session)
        self.slot_repo = MatchParticipantRepository(session)
        self.wallet_service = WalletService(session)

    async def _get_match_and_game(self, match_id: UUID):
        match = await self.match_repo.get_by_id(match_id)
        if match is None:
            raise NotFoundException("Match not found")
        schedule = await self.tournament_repo.get_by_id(match.tournament_id)
        if schedule is None:
            raise NotFoundException("Match not found")
        game = await self.game_repo.get_by_id(schedule.game_id)
        return match, schedule, game

    async def get_match_details(self, match_id: UUID) -> MatchAdminDetailRead:
        match, schedule, game = await self._get_match_and_game(match_id)
        slots = await self.slot_repo.list_for_match(match.id)

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
                        winning_amount=slot.winning_amount,
                        winning_paid_at=slot.winning_paid_at,
                        joined_at=slot.created_at,
                    )
                )
            elif slot.match_team_id and slot.match_team is not None:
                # Squad join — one row per team member.
                for member in slot.match_team.members:
                    user = member.user
                    profile = await self.game_profile_repo.get_by_user_and_game(user.id, game.id)
                    players.append(
                        MatchAdminPlayerRead(
                            user_id=user.id,
                            full_name=user.full_name,
                            phone_number=user.phone_number,
                            game_nickname=(profile.data or {}).get("nickname") if profile else None,
                            game_uid=(profile.data or {}).get("uid") if profile else None,
                            team_name=slot.match_team.team_name,
                            team_id=slot.match_team.id,
                            kills=member.kills,
                            is_winner=member.is_winner,
                            winning_amount=member.winning_amount,
                            winning_paid_at=member.winning_paid_at,
                            joined_at=member.created_at,
                        )
                    )

        return MatchAdminDetailRead(
            id=match.id,
            short_id=match.short_id,
            match_uid=match.match_uid,
            game_id=game.id,
            game_name=game.name,
            category=schedule.category.value if schedule.category else None,
            team_format=match.team_format,
            scheduled_start=match.scheduled_start,
            match_status=match.match_status.value,
            room_id=match.room_id,
            room_password=match.room_password,
            entry_fee=match.entry_fee if match.entry_fee is not None else schedule.entry_fee,
            prize_pool=match.prize_pool if match.prize_pool is not None else schedule.prize_pool,
            total_joined=len(players),
            max_players=schedule.max_players,
            players=players,
        )

    async def _find_player_slot(self, match_id: UUID, user_id: UUID):
        """Returns ('solo', MatchParticipant) or ('squad', MatchTeamMember) for
        this user in this match, or raises NotFoundException."""
        slots = await self.slot_repo.list_for_match(match_id)
        for slot in slots:
            if slot.participant_id and slot.participant is not None and slot.participant.user_id == user_id:
                return "solo", slot
            if slot.match_team_id and slot.match_team is not None:
                for member in slot.match_team.members:
                    if member.user_id == user_id:
                        return "squad", member
        raise NotFoundException("This user did not join this match")

    async def declare_result(
        self, match_id: UUID, user_id: UUID, *, kills: Optional[int], is_winner: Optional[bool]
    ):
        kind, row = await self._find_player_slot(match_id, user_id)
        update_data = {}
        if kills is not None:
            update_data["kills"] = kills
        if is_winner is not None:
            update_data["is_winner"] = is_winner
        if not update_data:
            return row

        if kind == "solo":
            row = await self.slot_repo.update(row, **update_data)
        else:
            from app.repositories.base import BaseRepository
            from app.models.match_team import MatchTeamMember

            repo = BaseRepository(self.session, MatchTeamMember)
            row = await repo.update(row, **update_data)

        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def pay_winner(
        self, match_id: UUID, user_id: UUID, *, amount: Decimal, note: Optional[str], current_user: User
    ):
        kind, row = await self._find_player_slot(match_id, user_id)
        if not row.is_winner:
            raise ValidationException(
                "This player is not declared a winner yet — declare them a winner first."
            )
        if row.winning_paid_at is not None:
            raise ValidationException("This player has already been paid for this match.")

        from app.repositories.user_repository import UserRepository

        user = await UserRepository(self.session).get_by_id(user_id)
        if user is None:
            raise NotFoundException("User not found")

        await self.wallet_service.credit(
            user,
            amount=amount,
            reference_type=_WALLET_WINNING_REF_TYPE,
            reference_id=str(match_id),
            description=note or f"Winning amount for match {match_id}",
            commit=False,
        )

        from datetime import datetime, timezone

        update_data = {"winning_amount": amount, "winning_paid_at": datetime.now(timezone.utc)}
        if kind == "solo":
            row = await self.slot_repo.update(row, **update_data)
        else:
            from app.repositories.base import BaseRepository
            from app.models.match_team import MatchTeamMember

            repo = BaseRepository(self.session, MatchTeamMember)
            row = await repo.update(row, **update_data)

        await self.session.commit()
        await self.session.refresh(row)
        return row
