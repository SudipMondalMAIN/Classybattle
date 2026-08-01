"""
Live Match & Real-Time Tournament services — Phase 12.

Layered on top of the existing MatchService (Phase 7) / MatchResultService
(Phase 11) / TournamentService (Phase 2): match lifecycle status
(``Match.match_status``) is still transitioned exclusively through
``MatchService.update_match_status`` so every existing invariant
(room handling, no-show sweeps, etc.) keeps working unchanged. This
module only adds the *real-time* layer on top (pause/resume timers,
score/event feed, live leaderboard, tournament round progress) and
wires automatic match-completion / round-completion / tournament
progression into that same flow.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.models.audit_log import AuditAction
from app.models.live_match import (
    LIVE_MATCH_STATUS_TRANSITIONS,
    LiveMatch,
    LiveMatchEvent,
    LiveMatchEventType,
    LiveMatchScore,
    LiveMatchStatus,
    LiveTournamentState,
    LiveTournamentStatus,
)
from app.models.match import Match, MatchStatus
from app.models.tournament import TOURNAMENT_STATUS_TRANSITIONS, Tournament, TournamentStatus
from app.models.user import User, UserRole
from app.repositories.live_match_repository import (
    LiveMatchEventRepository,
    LiveMatchRepository,
    LiveMatchScoreRepository,
    LiveTournamentRepository,
)
from app.repositories.match_participant_repository import MatchParticipantRepository
from app.repositories.match_repository import MatchRepository
from app.repositories.tournament_repository import TournamentRepository
from app.schemas.live_match import LogEventRequest, PlayerScoreUpdate, TeamScoreUpdate
from app.services.audit_service import AuditService
from app.services.match_service import MatchService

_MANAGER_ROLES = {UserRole.ADMIN, UserRole.SUPER_ADMIN}

_LIVE_ENTITY = "live_match"
_TOURNAMENT_ENTITY = "live_tournament"


class LiveMatchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.live_repo = LiveMatchRepository(session)
        self.event_repo = LiveMatchEventRepository(session)
        self.score_repo = LiveMatchScoreRepository(session)
        self.match_repo = MatchRepository(session)
        self.slot_repo = MatchParticipantRepository(session)
        self.tournament_repo = TournamentRepository(session)
        self.match_service = MatchService(session)
        self.audit = AuditService(session)
        self.live_tournament_service = LiveTournamentService(session)

    # ------------------------------------------------------------------
    # Authorization / fetch helpers
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
            "You do not have permission to manage the live state of this match"
        )

    async def _get_match_and_tournament(self, match_id: UUID) -> tuple[Match, Tournament]:
        match = await self.match_repo.get_by_id(match_id)
        if match is None:
            raise NotFoundException("Match not found")
        tournament = await self.tournament_repo.get_by_id(match.tournament_id)
        if tournament is None:
            raise NotFoundException("Tournament not found")
        return match, tournament

    async def _get_or_create_live_match(self, match: Match) -> LiveMatch:
        live = await self.live_repo.get_by_match_id(match.id, with_lock=True)
        if live is None:
            live = await self.live_repo.create(
                match_id=match.id,
                tournament_id=match.tournament_id,
                status=LiveMatchStatus.NOT_STARTED,
                current_round=match.round_number,
            )
        return live

    async def get_live_match(self, match_id: UUID) -> LiveMatch:
        live = await self.live_repo.get_by_match_id(match_id)
        if live is None:
            raise NotFoundException("This match has no live session yet")
        return live

    def _assert_live_transition(
        self, current: LiveMatchStatus, target: LiveMatchStatus
    ) -> None:
        allowed = LIVE_MATCH_STATUS_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValidationException(
                f"Cannot transition live match from '{current.value}' to '{target.value}'"
            )

    @staticmethod
    def _elapsed_seconds(live: LiveMatch) -> int:
        if live.started_at is None:
            return 0
        now = datetime.now(timezone.utc)
        end = live.ended_at or now
        paused_span = 0
        if live.status == LiveMatchStatus.PAUSED and live.paused_at is not None:
            paused_span = int((now - live.paused_at).total_seconds())
        total = (end - live.started_at).total_seconds() - live.total_paused_seconds - paused_span
        return max(0, int(total))

    async def _log_event(
        self,
        match: Match,
        event_type: LiveMatchEventType,
        *,
        round_number: Optional[int] = None,
        team_id: Optional[UUID] = None,
        participant_id: Optional[UUID] = None,
        message: Optional[str] = None,
        event_metadata: Optional[dict] = None,
        client_event_id: Optional[str] = None,
        actor: Optional[User] = None,
    ) -> LiveMatchEvent:
        if client_event_id:
            existing = await self.event_repo.get_by_client_event_id(match.id, client_event_id)
            if existing is not None:
                return existing

        sequence = await self.event_repo.next_sequence(match.id)
        event = await self.event_repo.create(
            match_id=match.id,
            sequence=sequence,
            event_type=event_type,
            round_number=round_number,
            team_id=team_id,
            participant_id=participant_id,
            message=message,
            event_metadata=event_metadata,
            client_event_id=client_event_id,
            created_by=actor.id if actor is not None else None,
        )
        return event

    # ==================================================================
    # Lifecycle: start / pause / resume / end / cancel
    # ==================================================================
    async def start_match(self, match_id: UUID, current_user: User) -> LiveMatch:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)

        live = await self._get_or_create_live_match(match)
        self._assert_live_transition(live.status, LiveMatchStatus.LIVE)

        # Drives the underlying Match lifecycle through its own validated
        # transition table; a no-op if it's already LIVE.
        if match.match_status != MatchStatus.LIVE:
            match = await self.match_service.update_match_status(
                match.id, MatchStatus.LIVE, current_user
            )

        now = datetime.now(timezone.utc)
        live = await self.live_repo.update(
            live,
            status=LiveMatchStatus.LIVE,
            started_at=live.started_at or now,
            round_started_at=now,
            current_round=live.current_round or match.round_number,
        )
        await self._log_event(
            match, LiveMatchEventType.MATCH_STARTED, actor=current_user, round_number=live.current_round
        )
        await self.audit.record(
            entity=_LIVE_ENTITY,
            action=AuditAction.STATUS_CHANGE,
            entity_id=live.id,
            actor=current_user,
            new_values={"status": LiveMatchStatus.LIVE.value},
            description=f"Live match started for match {match.match_uid}",
        )
        await self.live_tournament_service.sync_tournament_progress(tournament.id)
        await self.session.commit()
        await self.session.refresh(live)

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
                    event_type=NotificationEventType.LIVE_MATCH_STARTED,
                    title="Live match started",
                    body=f"The live match for '{tournament.title}' (round {match.round_number}) has started. Join now!",
                    event_key_prefix=f"live_match_started:{live.id}",
                )
        except Exception:  # noqa: BLE001
            pass

        return live

    async def pause_match(self, match_id: UUID, current_user: User, reason: Optional[str] = None) -> LiveMatch:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        live = await self.get_live_match(match_id)
        self._assert_live_transition(live.status, LiveMatchStatus.PAUSED)

        now = datetime.now(timezone.utc)
        live = await self.live_repo.update(live, status=LiveMatchStatus.PAUSED, paused_at=now)
        await self._log_event(
            match, LiveMatchEventType.MATCH_PAUSED, actor=current_user, message=reason
        )
        await self.audit.record(
            entity=_LIVE_ENTITY,
            action=AuditAction.STATUS_CHANGE,
            entity_id=live.id,
            actor=current_user,
            new_values={"status": LiveMatchStatus.PAUSED.value},
            description=f"Live match paused for match {match.match_uid}",
        )
        await self.session.commit()
        await self.session.refresh(live)
        return live

    async def resume_match(self, match_id: UUID, current_user: User) -> LiveMatch:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        live = await self.get_live_match(match_id)
        self._assert_live_transition(live.status, LiveMatchStatus.LIVE)

        now = datetime.now(timezone.utc)
        additional_pause = 0
        if live.paused_at is not None:
            additional_pause = int((now - live.paused_at).total_seconds())

        live = await self.live_repo.update(
            live,
            status=LiveMatchStatus.LIVE,
            paused_at=None,
            total_paused_seconds=live.total_paused_seconds + max(0, additional_pause),
        )
        await self._log_event(match, LiveMatchEventType.MATCH_RESUMED, actor=current_user)
        await self.audit.record(
            entity=_LIVE_ENTITY,
            action=AuditAction.STATUS_CHANGE,
            entity_id=live.id,
            actor=current_user,
            new_values={"status": LiveMatchStatus.LIVE.value},
            description=f"Live match resumed for match {match.match_uid}",
        )
        await self.session.commit()
        await self.session.refresh(live)
        return live

    async def end_match(self, match_id: UUID, current_user: User) -> LiveMatch:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        live = await self.get_live_match(match_id)

        if live.status == LiveMatchStatus.ENDED:
            # Idempotent: ending an already-ended live match is a no-op,
            # never a duplicate completion.
            return live

        self._assert_live_transition(live.status, LiveMatchStatus.ENDED)

        now = datetime.now(timezone.utc)
        paused_extra = 0
        if live.status == LiveMatchStatus.PAUSED and live.paused_at is not None:
            paused_extra = int((now - live.paused_at).total_seconds())

        live = await self.live_repo.update(
            live,
            status=LiveMatchStatus.ENDED,
            ended_at=now,
            paused_at=None,
            total_paused_seconds=live.total_paused_seconds + max(0, paused_extra),
        )

        if match.match_status not in (MatchStatus.COMPLETED, MatchStatus.CANCELLED):
            match = await self.match_service.update_match_status(
                match.id, MatchStatus.COMPLETED, current_user
            )

        if not live.auto_completion_processed:
            live = await self.live_repo.update(live, auto_completion_processed=True)

        await self._log_event(match, LiveMatchEventType.MATCH_ENDED, actor=current_user)
        await self.audit.record(
            entity=_LIVE_ENTITY,
            action=AuditAction.STATUS_CHANGE,
            entity_id=live.id,
            actor=current_user,
            new_values={"status": LiveMatchStatus.ENDED.value},
            description=f"Live match ended for match {match.match_uid}",
        )
        await self.live_tournament_service.sync_tournament_progress(tournament.id)
        await self.session.commit()
        await self.session.refresh(live)
        return live

    async def cancel_match(
        self, match_id: UUID, current_user: User, reason: Optional[str] = None
    ) -> LiveMatch:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        live = await self._get_or_create_live_match(match)

        if live.status == LiveMatchStatus.CANCELLED:
            return live

        self._assert_live_transition(live.status, LiveMatchStatus.CANCELLED)
        now = datetime.now(timezone.utc)
        live = await self.live_repo.update(
            live, status=LiveMatchStatus.CANCELLED, ended_at=now, paused_at=None
        )

        if match.match_status not in (MatchStatus.COMPLETED, MatchStatus.CANCELLED):
            match = await self.match_service.update_match_status(
                match.id, MatchStatus.CANCELLED, current_user
            )

        await self._log_event(
            match, LiveMatchEventType.MATCH_CANCELLED, actor=current_user, message=reason
        )
        await self.audit.record(
            entity=_LIVE_ENTITY,
            action=AuditAction.STATUS_CHANGE,
            entity_id=live.id,
            actor=current_user,
            new_values={"status": LiveMatchStatus.CANCELLED.value},
            description=f"Live match cancelled for match {match.match_uid}: {reason or 'n/a'}",
        )
        await self.live_tournament_service.sync_tournament_progress(tournament.id)
        await self.session.commit()
        await self.session.refresh(live)
        return live

    # ==================================================================
    # Round timer
    # ==================================================================
    async def update_round_timer(
        self, match_id: UUID, current_user: User, round_number: int, round_timer_seconds: Optional[int]
    ) -> LiveMatch:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        live = await self.get_live_match(match_id)
        if live.status not in (LiveMatchStatus.LIVE, LiveMatchStatus.PAUSED):
            raise ValidationException("Round timer can only be updated while the match is live")

        is_new_round = round_number != live.current_round
        now = datetime.now(timezone.utc)
        live = await self.live_repo.update(
            live,
            current_round=round_number,
            round_timer_seconds=round_timer_seconds,
            round_started_at=now if is_new_round else live.round_started_at,
        )
        if is_new_round:
            await self._log_event(
                match,
                LiveMatchEventType.ROUND_STARTED,
                actor=current_user,
                round_number=round_number,
            )
        await self.session.commit()
        await self.session.refresh(live)
        return live

    # ==================================================================
    # Score updates
    # ==================================================================
    async def update_team_score(
        self, match_id: UUID, current_user: User, payload: TeamScoreUpdate
    ) -> LiveMatchScore:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        live = await self.get_live_match(match_id)
        if live.status not in (LiveMatchStatus.LIVE, LiveMatchStatus.PAUSED):
            raise ValidationException("Scores can only be updated while the match is live")

        slot = await self.slot_repo.get_by_match_and_team(match.id, payload.team_id)
        if slot is None:
            raise ValidationException("Team is not assigned to this match")

        row = await self.score_repo.get_by_team(match.id, payload.team_id)
        now = datetime.now(timezone.utc)
        if row is None:
            row = await self.score_repo.create(
                match_id=match.id,
                team_id=payload.team_id,
                kills=payload.kills or 0,
                score=payload.score if payload.score is not None else (payload.score_delta or 0),
                extra_stats=payload.extra_stats,
                last_updated_at=now,
            )
        else:
            update_fields: dict = {"last_updated_at": now}
            if payload.kills is not None:
                update_fields["kills"] = payload.kills
            if payload.score is not None:
                update_fields["score"] = payload.score
            elif payload.score_delta is not None:
                update_fields["score"] = row.score + payload.score_delta
            if payload.extra_stats is not None:
                update_fields["extra_stats"] = payload.extra_stats
            row = await self.score_repo.update(row, **update_fields)

        await self._recompute_ranks(match.id)
        await self._log_event(
            match,
            LiveMatchEventType.SCORE_UPDATE,
            actor=current_user,
            team_id=payload.team_id,
            round_number=live.current_round,
            event_metadata={"score": row.score, "kills": row.kills},
        )
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def update_player_score(
        self, match_id: UUID, current_user: User, payload: PlayerScoreUpdate
    ) -> LiveMatchScore:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        live = await self.get_live_match(match_id)
        if live.status not in (LiveMatchStatus.LIVE, LiveMatchStatus.PAUSED):
            raise ValidationException("Scores can only be updated while the match is live")

        slot = await self.slot_repo.get_by_match_and_participant(match.id, payload.participant_id)
        if slot is None:
            raise ValidationException("Participant is not assigned to this match")

        row = await self.score_repo.get_by_participant(match.id, payload.participant_id)
        now = datetime.now(timezone.utc)
        if row is None:
            row = await self.score_repo.create(
                match_id=match.id,
                participant_id=payload.participant_id,
                kills=payload.kills or 0,
                score=payload.score if payload.score is not None else (payload.score_delta or 0),
                extra_stats=payload.extra_stats,
                last_updated_at=now,
            )
        else:
            update_fields: dict = {"last_updated_at": now}
            if payload.kills is not None:
                update_fields["kills"] = payload.kills
            if payload.score is not None:
                update_fields["score"] = payload.score
            elif payload.score_delta is not None:
                update_fields["score"] = row.score + payload.score_delta
            if payload.extra_stats is not None:
                update_fields["extra_stats"] = payload.extra_stats
            row = await self.score_repo.update(row, **update_fields)

        await self._recompute_ranks(match.id)
        await self._log_event(
            match,
            LiveMatchEventType.SCORE_UPDATE,
            actor=current_user,
            participant_id=payload.participant_id,
            round_number=live.current_round,
            event_metadata={"score": row.score, "kills": row.kills},
        )
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def _recompute_ranks(self, match_id: UUID) -> None:
        rows = await self.score_repo.list_all_for_match(match_id)
        for idx, row in enumerate(rows, start=1):
            if row.rank != idx:
                await self.score_repo.update(row, rank=idx)

    # ==================================================================
    # Kill / event logging
    # ==================================================================
    async def log_event(
        self, match_id: UUID, current_user: User, payload: LogEventRequest
    ) -> LiveMatchEvent:
        match, tournament = await self._get_match_and_tournament(match_id)
        self._assert_can_manage(tournament, current_user)
        live = await self.get_live_match(match_id)
        if live.status not in (LiveMatchStatus.LIVE, LiveMatchStatus.PAUSED):
            raise ValidationException("Events can only be logged while the match is live")

        event = await self._log_event(
            match,
            payload.event_type,
            round_number=payload.round_number or live.current_round,
            team_id=payload.team_id,
            participant_id=payload.participant_id,
            message=payload.message,
            event_metadata=payload.event_metadata,
            client_event_id=payload.client_event_id,
            actor=current_user,
        )

        if payload.event_type in (LiveMatchEventType.KILL, LiveMatchEventType.ELIMINATION) and (
            payload.team_id or payload.participant_id
        ):
            if payload.team_id:
                row = await self.score_repo.get_by_team(match.id, payload.team_id)
                if row is not None:
                    await self.score_repo.update(row, kills=row.kills + 1)
            elif payload.participant_id:
                row = await self.score_repo.get_by_participant(match.id, payload.participant_id)
                if row is not None:
                    await self.score_repo.update(row, kills=row.kills + 1)
            await self._recompute_ranks(match.id)

        await self.session.commit()
        await self.session.refresh(event)
        return event

    # ==================================================================
    # Reads (status / leaderboard / stats / timeline / active list)
    # ==================================================================
    async def get_status(self, match_id: UUID) -> LiveMatch:
        return await self.get_live_match(match_id)

    async def get_leaderboard(self, match_id: UUID, page: int = 1, page_size: int = 50):
        return await self.score_repo.leaderboard(match_id, page=page, page_size=page_size)

    async def get_stats(self, match_id: UUID) -> dict:
        live = await self.get_live_match(match_id)
        rows = await self.score_repo.list_all_for_match(match_id)
        _, total_events = await self.event_repo.list_for_match(match_id, page=1, page_size=1)
        total_kills = sum(r.kills for r in rows)
        top_scorer = rows[0] if rows else None
        return {
            "match_id": match_id,
            "status": live.status,
            "elapsed_seconds": self._elapsed_seconds(live),
            "current_round": live.current_round,
            "total_kills": total_kills,
            "total_events": total_events,
            "participants_or_teams_tracked": len(rows),
            "top_scorer": top_scorer,
        }

    async def get_timeline(
        self,
        match_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        event_type: Optional[LiveMatchEventType] = None,
        round_number: Optional[int] = None,
        sort_by: str = "sequence",
        sort_order: str = "desc",
    ):
        return await self.event_repo.list_for_match(
            match_id,
            page=page,
            page_size=page_size,
            event_type=event_type,
            round_number=round_number,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def list_active_matches(
        self, *, tournament_id: Optional[UUID] = None, page: int = 1, page_size: int = 20
    ):
        return await self.live_repo.list_active(
            tournament_id=tournament_id, page=page, page_size=page_size
        )


class LiveTournamentService:
    """Tracks aggregate real-time progress for a tournament: current
    round, live/completed match counters, and automatic round/tournament
    progression, driven by LiveMatchService whenever a match starts/ends.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.state_repo = LiveTournamentRepository(session)
        self.match_repo = MatchRepository(session)
        self.tournament_repo = TournamentRepository(session)
        self.audit = AuditService(session)

    async def _get_or_create_state(self, tournament_id: UUID) -> LiveTournamentState:
        state = await self.state_repo.get_by_tournament_id(tournament_id, with_lock=True)
        if state is None:
            state = await self.state_repo.create(
                tournament_id=tournament_id,
                status=LiveTournamentStatus.NOT_STARTED,
                current_round=1,
            )
        return state

    async def get_state(self, tournament_id: UUID) -> LiveTournamentState:
        state = await self.state_repo.get_by_tournament_id(tournament_id)
        if state is None:
            raise NotFoundException("This tournament has no live progress yet")
        return state

    async def sync_tournament_progress(self, tournament_id: UUID) -> LiveTournamentState:
        """Atomically recomputes live/completed match counters, advances
        `current_round` once every match in it is finished, and marks the
        tournament COMPLETED once its final round is finished. Safe to
        call repeatedly (idempotent) — row-locked via `with_for_update`.
        """
        state = await self._get_or_create_state(tournament_id)

        all_matches, total = await self.match_repo.list_for_tournament(
            tournament_id, page=1, page_size=10_000
        )
        if not all_matches:
            return state

        live_count = sum(1 for m in all_matches if m.match_status == MatchStatus.LIVE)
        completed_count = sum(
            1
            for m in all_matches
            if m.match_status in (MatchStatus.COMPLETED, MatchStatus.CANCELLED)
        )
        max_round = max(m.round_number for m in all_matches)

        update_fields: dict = {
            "total_matches": total,
            "live_matches": live_count,
            "completed_matches": completed_count,
            "total_rounds": max_round,
            "last_progressed_at": datetime.now(timezone.utc),
        }
        if state.status == LiveTournamentStatus.NOT_STARTED and live_count > 0:
            update_fields["status"] = LiveTournamentStatus.LIVE

        # Automatic round completion: advance current_round while every
        # match in it is finished and a later round exists.
        current_round = state.current_round
        while True:
            round_matches = [m for m in all_matches if m.round_number == current_round]
            if not round_matches:
                break
            round_done = all(
                m.match_status in (MatchStatus.COMPLETED, MatchStatus.CANCELLED)
                for m in round_matches
            )
            has_next_round = any(m.round_number == current_round + 1 for m in all_matches)
            if round_done and has_next_round:
                current_round += 1
                continue
            break
        update_fields["current_round"] = current_round

        # Automatic tournament completion: last round finished.
        last_round_matches = [m for m in all_matches if m.round_number == max_round]
        tournament_finished = last_round_matches and all(
            m.match_status in (MatchStatus.COMPLETED, MatchStatus.CANCELLED)
            for m in last_round_matches
        )
        if tournament_finished:
            update_fields["status"] = LiveTournamentStatus.COMPLETED

        state = await self.state_repo.update(state, **update_fields)

        if tournament_finished:
            tournament = await self.tournament_repo.get_by_id(tournament_id)
            if (
                tournament is not None
                and tournament.status == TournamentStatus.LIVE
                and TournamentStatus.COMPLETED
                in TOURNAMENT_STATUS_TRANSITIONS.get(tournament.status, set())
            ):
                await self.tournament_repo.update(
                    tournament, status=TournamentStatus.COMPLETED
                )
                await self.audit.record(
                    entity=_TOURNAMENT_ENTITY,
                    action=AuditAction.STATUS_CHANGE,
                    entity_id=tournament.id,
                    new_values={"status": TournamentStatus.COMPLETED.value},
                    description="Tournament automatically completed: all rounds finished",
                )

        return state

    async def get_progress(self, tournament_id: UUID) -> dict:
        state = await self.get_state(tournament_id)
        all_matches, _ = await self.match_repo.list_for_tournament(
            tournament_id, page=1, page_size=10_000
        )
        round_matches = [m for m in all_matches if m.round_number == state.current_round]
        round_total = len(round_matches)
        round_completed = sum(
            1
            for m in round_matches
            if m.match_status in (MatchStatus.COMPLETED, MatchStatus.CANCELLED)
        )
        progress_percent = (
            round(100 * state.completed_matches / state.total_matches, 2)
            if state.total_matches
            else 0.0
        )
        return {
            "id": state.id,
            "tournament_id": state.tournament_id,
            "status": state.status,
            "current_round": state.current_round,
            "total_rounds": state.total_rounds,
            "total_matches": state.total_matches,
            "live_matches": state.live_matches,
            "completed_matches": state.completed_matches,
            "last_progressed_at": state.last_progressed_at,
            "current_round_matches_total": round_total,
            "current_round_matches_completed": round_completed,
            "progress_percent": progress_percent,
        }
