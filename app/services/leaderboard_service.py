"""
LeaderboardService — Leaderboards, Rankings & Player/Team Statistics
(Phase 14).

Integration points (called from other services, never the other way
around, mirroring how PrizeService is invoked from
MatchResultService.approve_result):

- ``record_match_completion`` — called once per approved MatchResult
  (from MatchResultService._trigger_prize_distribution / approve_result)
  to increment matches_played/won/lost, kills/deaths/assists/mvp, and
  roll the same deltas into the Daily/Weekly/Monthly/Seasonal period
  tables for every participant and team slot in the match.
- ``record_prize_credit`` — called once per PAID PrizePayout (from
  PrizeService._settle_payout) to add prize money into
  PlayerStatistics/PlayerPeriodStats.wallet/prize earnings and
  TeamStatistics for team payouts.
- ``record_tournament_completion`` — called when a Tournament transitions
  to COMPLETED, to increment tournaments_played/won for every
  participant/team.

Idempotency: every mutation is guarded by LeaderboardUpdateLog, keyed on
(source_event, source_id). A duplicate call (retry, concurrent worker)
is a guaranteed no-op, so statistics/leaderboards can never double count
even if the calling service's own trigger fires more than once.

Ranking: ``ranking_score`` is a single deterministic weighted score used
to ORDER BY every leaderboard consistently:
    score = wins*10 + kills*2 + assists*1 - deaths*0.5 + mvp*5
            + (prize_money_earned / 100)
Recomputing ranks (``recompute_global_ranks`` / ``recompute_period_ranks``)
walks the ordered rows once and writes an immutable RankHistory row for
every entity whose rank actually changed, allowing "automatic ranking
updates" + "rank change tracking" without a full-table rank recompute
being required on every single read.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Optional, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.audit_log import AuditAction
from app.models.leaderboard import (
    LeaderboardPeriodType,
    LeaderboardSourceEvent,
    PlayerPeriodStats,
    PlayerStatistics,
    RankingScope,
    TeamPeriodStats,
    TeamStatistics,
)
from app.models.tournament import Tournament
from app.models.tournament_result import TournamentResult
from app.models.tournament_winner import TournamentWinner
from app.repositories.leaderboard_repository import (
    LeaderboardUpdateLogRepository,
    PlayerPeriodStatsRepository,
    PlayerStatisticsRepository,
    RankHistoryRepository,
    TeamPeriodStatsRepository,
    TeamStatisticsRepository,
)
from app.repositories.tournament_participant_repository import TournamentParticipantRepository
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.team_member_repository import TeamMemberRepository
from app.services.audit_service import AuditService
from app.models.achievement import AchievementTriggerType

_WIN_WEIGHT = Decimal("10")
_KILL_WEIGHT = Decimal("2")
_ASSIST_WEIGHT = Decimal("1")
_DEATH_WEIGHT = Decimal("0.5")
_MVP_WEIGHT = Decimal("5")
_PRIZE_DIVISOR = Decimal("100")


def _player_score(
    *, matches_won: int, kills: int, deaths: int, assists: int, mvp_count: int, prize_money: Decimal
) -> Decimal:
    return (
        Decimal(matches_won) * _WIN_WEIGHT
        + Decimal(kills) * _KILL_WEIGHT
        + Decimal(assists) * _ASSIST_WEIGHT
        - Decimal(deaths) * _DEATH_WEIGHT
        + Decimal(mvp_count) * _MVP_WEIGHT
        + (prize_money / _PRIZE_DIVISOR)
    )


def _team_score(*, matches_won: int, tournaments_won: int, prize_money: Decimal) -> Decimal:
    return (
        Decimal(matches_won) * _WIN_WEIGHT
        + Decimal(tournaments_won) * (_WIN_WEIGHT * 3)
        + (prize_money / _PRIZE_DIVISOR)
    )


def daily_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def weekly_key(dt: datetime) -> str:
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def monthly_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def seasonal_key(dt: datetime) -> str:
    quarter = math.ceil(dt.month / 3)
    return f"{dt.year}-S{quarter}"


def period_keys(dt: Optional[datetime] = None) -> dict[LeaderboardPeriodType, str]:
    dt = dt or datetime.now(timezone.utc)
    return {
        LeaderboardPeriodType.DAILY: daily_key(dt),
        LeaderboardPeriodType.WEEKLY: weekly_key(dt),
        LeaderboardPeriodType.MONTHLY: monthly_key(dt),
        LeaderboardPeriodType.SEASONAL: seasonal_key(dt),
    }


class LeaderboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.player_stats_repo = PlayerStatisticsRepository(session)
        self.team_stats_repo = TeamStatisticsRepository(session)
        self.player_period_repo = PlayerPeriodStatsRepository(session)
        self.team_period_repo = TeamPeriodStatsRepository(session)
        self.rank_history_repo = RankHistoryRepository(session)
        self.update_log_repo = LeaderboardUpdateLogRepository(session)
        self.match_participant_repo = TournamentParticipantRepository(session)
        self.team_member_repo = TeamMemberRepository(session)
        self.participant_repo = ParticipantRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------
    # Per-slot result extraction helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _entry_for(entries: Iterable[dict], *, participant_id=None, team_id=None) -> dict:
        for e in entries:
            if participant_id is not None and str(e.get("participant_id")) == str(participant_id):
                return e
            if team_id is not None and str(e.get("team_id")) == str(team_id):
                return e
        return {}

    # ------------------------------------------------------------------
    # 1. Match completion -> player/team statistics + period stats
    # ------------------------------------------------------------------
    async def record_match_completion(
        self, *, match: Tournament, result: TournamentResult, winners: Sequence[TournamentWinner]
    ) -> None:
        source_id = str(result.id)
        if await self.update_log_repo.exists(LeaderboardSourceEvent.MATCH_COMPLETED, source_id):
            return  # Already folded into statistics — safe no-op on retry.

        slots = await self.match_participant_repo.list_for_tournament(match.id)
        winner_participant_ids = {w.participant_id for w in winners if w.participant_id}
        winner_team_ids = {w.team_id for w in winners if w.team_id}
        winners_by_rank1 = [w for w in winners if w.rank == 1]
        mvp_participant_ids: set = set()
        for w in winners_by_rank1:
            if w.participant_id:
                mvp_participant_ids.add(w.participant_id)
            elif w.team_id:
                captain_id = await self._captain_user_participant(w.team_id)
                if captain_id:
                    mvp_participant_ids.add(captain_id)

        entries = result.result_data or []
        now = datetime.now(timezone.utc)
        pkeys = period_keys(now)

        for slot in slots:
            if slot.participant_id and slot.participant is not None:
                await self._apply_player_match(
                    user_id=slot.participant.user_id,
                    participant_id=slot.participant_id,
                    won=slot.participant_id in winner_participant_ids,
                    is_mvp=slot.participant_id in mvp_participant_ids,
                    entry=self._entry_for(entries, participant_id=slot.participant_id),
                    pkeys=pkeys,
                )
            if slot.team_id is not None:
                won = slot.team_id in winner_team_ids
                placement = self._entry_for(entries, team_id=slot.team_id).get("placement")
                await self._apply_team_match(
                    team_id=slot.team_id, won=won, placement=placement, pkeys=pkeys
                )
                members = await self.team_member_repo.list_for_team(slot.team_id)
                is_mvp_team = slot.team_id in {w.team_id for w in winners_by_rank1}
                for member in members:
                    await self._apply_player_match(
                        user_id=member.user_id,
                        participant_id=None,
                        won=won,
                        is_mvp=is_mvp_team and member.role.value == "captain",
                        entry=self._entry_for(entries, team_id=slot.team_id),
                        pkeys=pkeys,
                    )

        await self.update_log_repo.mark(
            LeaderboardSourceEvent.MATCH_COMPLETED, source_id, detail=f"match={match.id}"
        )
        await self.audit.record(
            entity="leaderboard",
            action=AuditAction.OTHER,
            entity_id=result.id,
            actor=None,
            new_values={"event": "match_completed"},
            description=f"Leaderboard statistics updated for match {match.id}",
        )
        await self.session.commit()

        # Phase 15C: automatic MATCH_WIN / MVP achievement evaluation.
        # Runs after the statistics transaction has committed so
        # achievement unlocks (which commit independently) never
        # interleave with in-progress leaderboard mutations.
        touched_user_ids: set = set()
        for slot in slots:
            if slot.participant_id and slot.participant is not None:
                touched_user_ids.add(slot.participant.user_id)
            if slot.team_id is not None:
                members = await self.team_member_repo.list_for_team(slot.team_id)
                for member in members:
                    touched_user_ids.add(member.user_id)
        for user_id in touched_user_ids:
            stats = await self.player_stats_repo.get_by_user_id(user_id)
            if stats is None:
                continue
            await self._evaluate_achievements(
                user_id, AchievementTriggerType.MATCH_WIN, stats.matches_won
            )
            await self._evaluate_achievements(user_id, AchievementTriggerType.MVP, stats.mvp_count)

    async def _evaluate_achievements(self, user_id: UUID, trigger_type, metric_value) -> None:
        """Best-effort hook into Phase 15C automatic achievement unlocks.
        Local import avoids a circular import between LeaderboardService
        and AchievementService."""
        try:
            from app.services.achievement_service import AchievementService

            await AchievementService(self.session).evaluate(
                user_id=user_id, trigger_type=trigger_type, metric_value=metric_value
            )
        except Exception:  # noqa: BLE001 - achievements must never break callers
            pass

    async def _captain_user_participant(self, team_id: UUID) -> Optional[UUID]:
        members = await self.team_member_repo.list_for_team(team_id)
        for m in members:
            if m.role.value == "captain" and m.participant_id is not None:
                return m.participant_id
        return None

    async def _apply_player_match(
        self,
        *,
        user_id: UUID,
        participant_id: Optional[UUID],
        won: bool,
        is_mvp: bool,
        entry: dict,
        pkeys: dict,
    ) -> None:
        kills = int(entry.get("kills", 0) or 0)
        deaths = int(entry.get("deaths", 0) or 0)
        assists = int(entry.get("assists", 0) or 0)

        stats = await self.player_stats_repo.get_by_user_id_for_update(user_id)
        if stats is None:
            stats = await self.player_stats_repo.get_or_create(user_id)
            stats = await self.player_stats_repo.get_by_user_id_for_update(user_id)

        matches_won = stats.matches_won + (1 if won else 0)
        matches_lost = stats.matches_lost + (0 if won else 1)
        new_kills = stats.kills + kills
        new_deaths = stats.deaths + deaths
        new_assists = stats.assists + assists
        new_mvp = stats.mvp_count + (1 if is_mvp else 0)
        score = _player_score(
            matches_won=matches_won,
            kills=new_kills,
            deaths=new_deaths,
            assists=new_assists,
            mvp_count=new_mvp,
            prize_money=stats.prize_money_earned,
        )
        await self.player_stats_repo.update(
            stats,
            matches_played=stats.matches_played + 1,
            matches_won=matches_won,
            matches_lost=matches_lost,
            kills=new_kills,
            deaths=new_deaths,
            assists=new_assists,
            mvp_count=new_mvp,
            ranking_score=score,
        )

        for ptype, pkey in pkeys.items():
            period = await self.player_period_repo.get_or_create(user_id, ptype, pkey)
            period = await self.player_period_repo.get_for_update(user_id, ptype, pkey)
            p_won = period.matches_won + (1 if won else 0)
            p_kills = period.kills + kills
            p_deaths = period.deaths + deaths
            p_assists = period.assists + assists
            p_mvp = period.mvp_count + (1 if is_mvp else 0)
            p_score = _player_score(
                matches_won=p_won,
                kills=p_kills,
                deaths=p_deaths,
                assists=p_assists,
                mvp_count=p_mvp,
                prize_money=period.prize_money_earned,
            )
            await self.player_period_repo.update(
                period,
                matches_played=period.matches_played + 1,
                matches_won=p_won,
                kills=p_kills,
                deaths=p_deaths,
                assists=p_assists,
                mvp_count=p_mvp,
                ranking_score=p_score,
            )

    async def _apply_team_match(
        self, *, team_id: UUID, won: bool, placement: Optional[int], pkeys: dict
    ) -> None:
        stats = await self.team_stats_repo.get_by_team_id_for_update(team_id)
        if stats is None:
            await self.team_stats_repo.get_or_create(team_id)
            stats = await self.team_stats_repo.get_by_team_id_for_update(team_id)

        matches_won = stats.matches_won + (1 if won else 0)
        matches_lost = stats.matches_lost + (0 if won else 1)
        placement_total = stats.placement_total + int(placement or (1 if won else 2))
        score = _team_score(
            matches_won=matches_won,
            tournaments_won=stats.tournaments_won,
            prize_money=stats.prize_money_earned,
        )
        await self.team_stats_repo.update(
            stats,
            matches_played=stats.matches_played + 1,
            matches_won=matches_won,
            matches_lost=matches_lost,
            placement_total=placement_total,
            ranking_score=score,
        )

        for ptype, pkey in pkeys.items():
            period = await self.team_period_repo.get_or_create(team_id, ptype, pkey)
            period = await self.team_period_repo.get_for_update(team_id, ptype, pkey)
            p_won = period.matches_won + (1 if won else 0)
            p_score = _team_score(
                matches_won=p_won, tournaments_won=0, prize_money=period.prize_money_earned
            )
            await self.team_period_repo.update(
                period,
                matches_played=period.matches_played + 1,
                matches_won=p_won,
                ranking_score=p_score,
            )

    # ------------------------------------------------------------------
    # 2. Prize credit -> earnings statistics
    # ------------------------------------------------------------------
    async def record_prize_credit(
        self, *, payout_id: UUID, user_id: UUID, team_id: Optional[UUID], amount: Decimal
    ) -> None:
        source_id = str(payout_id)
        if await self.update_log_repo.exists(LeaderboardSourceEvent.PRIZE_CREDITED, source_id):
            return

        stats = await self.player_stats_repo.get_by_user_id_for_update(user_id)
        if stats is None:
            await self.player_stats_repo.get_or_create(user_id)
            stats = await self.player_stats_repo.get_by_user_id_for_update(user_id)
        new_prize = stats.prize_money_earned + amount
        new_wallet = stats.wallet_earnings + amount
        score = _player_score(
            matches_won=stats.matches_won,
            kills=stats.kills,
            deaths=stats.deaths,
            assists=stats.assists,
            mvp_count=stats.mvp_count,
            prize_money=new_prize,
        )
        await self.player_stats_repo.update(
            stats, prize_money_earned=new_prize, wallet_earnings=new_wallet, ranking_score=score
        )

        pkeys = period_keys()
        for ptype, pkey in pkeys.items():
            period = await self.player_period_repo.get_or_create(user_id, ptype, pkey)
            period = await self.player_period_repo.get_for_update(user_id, ptype, pkey)
            p_prize = period.prize_money_earned + amount
            p_score = _player_score(
                matches_won=period.matches_won,
                kills=period.kills,
                deaths=period.deaths,
                assists=period.assists,
                mvp_count=period.mvp_count,
                prize_money=p_prize,
            )
            await self.player_period_repo.update(
                period, prize_money_earned=p_prize, ranking_score=p_score
            )

        if team_id is not None:
            tstats = await self.team_stats_repo.get_by_team_id_for_update(team_id)
            if tstats is None:
                await self.team_stats_repo.get_or_create(team_id)
                tstats = await self.team_stats_repo.get_by_team_id_for_update(team_id)
            t_prize = tstats.prize_money_earned + amount
            t_score = _team_score(
                matches_won=tstats.matches_won,
                tournaments_won=tstats.tournaments_won,
                prize_money=t_prize,
            )
            await self.team_stats_repo.update(
                tstats, prize_money_earned=t_prize, ranking_score=t_score
            )

        await self.update_log_repo.mark(LeaderboardSourceEvent.PRIZE_CREDITED, source_id)
        await self.session.commit()

        await self._evaluate_achievements(
            user_id, AchievementTriggerType.PRIZE_MILESTONE, new_prize
        )

    # ------------------------------------------------------------------
    # 3. Tournament completion -> tournaments played/won
    # ------------------------------------------------------------------
    async def record_tournament_completion(
        self,
        *,
        tournament_id: UUID,
        participant_user_ids: Sequence[UUID],
        winner_user_ids: Sequence[UUID],
        team_ids: Sequence[UUID] = (),
        winner_team_ids: Sequence[UUID] = (),
    ) -> None:
        source_id = str(tournament_id)
        if await self.update_log_repo.exists(LeaderboardSourceEvent.TOURNAMENT_COMPLETED, source_id):
            return

        winner_set = set(winner_user_ids)
        for user_id in set(participant_user_ids):
            stats = await self.player_stats_repo.get_by_user_id_for_update(user_id)
            if stats is None:
                await self.player_stats_repo.get_or_create(user_id)
                stats = await self.player_stats_repo.get_by_user_id_for_update(user_id)
            await self.player_stats_repo.update(
                stats,
                tournaments_played=stats.tournaments_played + 1,
                tournaments_won=stats.tournaments_won + (1 if user_id in winner_set else 0),
            )

        winner_team_set = set(winner_team_ids)
        for team_id in set(team_ids):
            tstats = await self.team_stats_repo.get_by_team_id_for_update(team_id)
            if tstats is None:
                await self.team_stats_repo.get_or_create(team_id)
                tstats = await self.team_stats_repo.get_by_team_id_for_update(team_id)
            new_tw = tstats.tournaments_won + (1 if team_id in winner_team_set else 0)
            score = _team_score(
                matches_won=tstats.matches_won,
                tournaments_won=new_tw,
                prize_money=tstats.prize_money_earned,
            )
            await self.team_stats_repo.update(
                tstats,
                tournaments_played=tstats.tournaments_played + 1,
                tournaments_won=new_tw,
                ranking_score=score,
            )

        await self.update_log_repo.mark(LeaderboardSourceEvent.TOURNAMENT_COMPLETED, source_id)
        await self.session.commit()

        for user_id in set(participant_user_ids):
            stats = await self.player_stats_repo.get_by_user_id(user_id)
            if stats is None:
                continue
            await self._evaluate_achievements(
                user_id, AchievementTriggerType.TOURNAMENT_PARTICIPATION, stats.tournaments_played
            )
            await self._evaluate_achievements(
                user_id, AchievementTriggerType.TOURNAMENT_WIN, stats.tournaments_won
            )

    # ------------------------------------------------------------------
    # 4. Rank recomputation + rank-change tracking
    # ------------------------------------------------------------------
    async def recompute_global_ranks(self) -> None:
        players = await self.player_stats_repo.list_all_ordered()
        improved_user_ids: list = []
        for idx, p in enumerate(players, start=1):
            if p.current_rank != idx:
                old_rank = p.current_rank
                await self.player_stats_repo.update(p, previous_rank=old_rank, current_rank=idx)
                await self.rank_history_repo.create(
                    scope=RankingScope.GLOBAL_PLAYER,
                    entity_id=p.user_id,
                    user_id=p.user_id,
                    old_rank=old_rank,
                    new_rank=idx,
                    ranking_score=p.ranking_score,
                    source_event=LeaderboardSourceEvent.MANUAL_RECOMPUTE,
                )
                if old_rank is None or idx < old_rank:
                    improved_user_ids.append((p.user_id, idx))

        teams = await self.team_stats_repo.list_all_ordered()
        for idx, t in enumerate(teams, start=1):
            if t.current_rank != idx:
                old_rank = t.current_rank
                await self.team_stats_repo.update(t, previous_rank=old_rank, current_rank=idx)
                await self.rank_history_repo.create(
                    scope=RankingScope.GLOBAL_TEAM,
                    entity_id=t.team_id,
                    team_id=t.team_id,
                    old_rank=old_rank,
                    new_rank=idx,
                    ranking_score=t.ranking_score,
                    source_event=LeaderboardSourceEvent.MANUAL_RECOMPUTE,
                )

        await self.audit.record(
            entity="leaderboard",
            action=AuditAction.OTHER,
            actor=None,
            description="Global player/team ranks recomputed",
        )
        await self.session.commit()

        for user_id, new_rank in improved_user_ids:
            await self._evaluate_achievements(user_id, AchievementTriggerType.RANKING, new_rank)

    async def recompute_period_ranks(self, period_type: LeaderboardPeriodType, period_key: str) -> None:
        rows = await self.player_period_repo.list_for_period_ordered(period_type, period_key)
        for idx, row in enumerate(rows, start=1):
            if row.current_rank != idx:
                await self.player_period_repo.update(row, current_rank=idx)
        await self.session.commit()

    # ------------------------------------------------------------------
    # 5. Read APIs
    # ------------------------------------------------------------------
    async def get_player_statistics(self, user_id: UUID) -> PlayerStatistics:
        stats = await self.player_stats_repo.get_by_user_id(user_id)
        if stats is None:
            raise NotFoundException("No statistics found for this player yet")
        return stats

    async def get_team_statistics(self, team_id: UUID) -> TeamStatistics:
        stats = await self.team_stats_repo.get_by_team_id(team_id)
        if stats is None:
            raise NotFoundException("No statistics found for this team yet")
        return stats

    async def top_players(self, *, page: int, page_size: int) -> tuple[Sequence[PlayerStatistics], int]:
        skip = (page - 1) * page_size
        rows = await self.player_stats_repo.top(skip=skip, limit=page_size)
        total = await self.player_stats_repo.count_all()
        return rows, total

    async def top_teams(self, *, page: int, page_size: int) -> tuple[Sequence[TeamStatistics], int]:
        skip = (page - 1) * page_size
        rows = await self.team_stats_repo.top(skip=skip, limit=page_size)
        total = await self.team_stats_repo.count_all()
        return rows, total

    async def period_leaderboard(
        self, period_type: LeaderboardPeriodType, period_key: str, *, page: int, page_size: int
    ) -> tuple[Sequence[PlayerPeriodStats], int]:
        skip = (page - 1) * page_size
        rows = await self.player_period_repo.top(period_type, period_key, skip=skip, limit=page_size)
        total = await self.player_period_repo.count(period_type, period_key)
        return rows, total

    async def team_period_leaderboard(
        self, period_type: LeaderboardPeriodType, period_key: str, *, page: int, page_size: int
    ) -> tuple[Sequence[TeamPeriodStats], int]:
        skip = (page - 1) * page_size
        rows = await self.team_period_repo.top(period_type, period_key, skip=skip, limit=page_size)
        total = await self.team_period_repo.count(period_type, period_key)
        return rows, total

    async def search_players(self, query: str, *, page: int, page_size: int) -> tuple[Sequence[PlayerStatistics], int]:
        skip = (page - 1) * page_size
        rows = await self.player_stats_repo.search_by_name(query, skip=skip, limit=page_size)
        return rows, len(rows)

    async def search_teams(self, query: str, *, page: int, page_size: int) -> tuple[Sequence[TeamStatistics], int]:
        skip = (page - 1) * page_size
        rows = await self.team_stats_repo.search_by_name(query, skip=skip, limit=page_size)
        return rows, len(rows)

    async def get_rank_history(
        self, scope: RankingScope, entity_id: UUID, *, page: int, page_size: int
    ):
        skip = (page - 1) * page_size
        return await self.rank_history_repo.list_for_entity(scope, entity_id, skip=skip, limit=page_size)

    async def tournament_player_rankings(
        self, tournament_id: UUID, *, page: int, page_size: int
    ) -> tuple[list[PlayerStatistics], int]:
        """Ranks this tournament's participants against each other using
        their existing global ranking_score (recomputed continuously by
        match completion), so no separate per-tournament counter table is
        needed just to answer "who's ahead within this tournament"."""
        participants = await self.participant_repo.list_active_for_tournament_all(tournament_id)
        user_ids = [p.user_id for p in participants]
        rows: list[PlayerStatistics] = []
        for uid in user_ids:
            stats = await self.player_stats_repo.get_by_user_id(uid)
            if stats is not None:
                rows.append(stats)
        rows.sort(key=lambda r: r.ranking_score, reverse=True)
        total = len(rows)
        skip = (page - 1) * page_size
        return rows[skip: skip + page_size], total
