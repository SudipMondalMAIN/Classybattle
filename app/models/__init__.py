"""
Import every model here so Alembic's autogenerate can discover them
via Base.metadata.
"""
from app.database.base import Base
from app.models.audit_log import AuditAction, AuditActorType, AuditLog
from app.models.device_token import DeviceToken
from app.models.idempotency_key import IdempotencyKey, IdempotencyKeyStatus
from app.models.game import Game
from app.models.game_mode import GameMode
from app.models.game_profile import UserGameProfile
from app.models.map import Map
from app.models.match import MATCH_STATUS_TRANSITIONS, Match, MatchStatus, RoomStatus
from app.models.match_participant import (
    MATCH_CHECKIN_TRANSITIONS,
    MatchAssignmentType,
    MatchCheckInStatus,
    MatchParticipant,
)
from app.models.notification import Notification
from app.models.otp import OTP
from app.models.participant import (
    Participant,
    ParticipantPaymentStatus,
    ParticipantStatus,
    RegistrationType,
)
from app.models.refresh_token import RefreshToken
from app.models.team import Team, TeamStatus
from app.models.team_member import TeamMember, TeamMemberRole
from app.models.tournament import (
    TeamRegistrationMode,
    Tournament,
    TournamentStatus,
    TournamentVisibility,
)
from app.models.user import User

__all__ = [
    "Base",
    "User",
    "OTP",
    "RefreshToken",
    "Game",
    "GameMode",
    "UserGameProfile",
    "Map",
    "Notification",
    "DeviceToken",
    "Tournament",
    "TournamentStatus",
    "TournamentVisibility",
    "Participant",
    "ParticipantStatus",
    "ParticipantPaymentStatus",
    "RegistrationType",
    "Team",
    "TeamStatus",
    "TeamMember",
    "TeamMemberRole",
    "TeamRegistrationMode",
    "Match",
    "MatchStatus",
    "RoomStatus",
    "MATCH_STATUS_TRANSITIONS",
    "MatchParticipant",
    "MatchAssignmentType",
    "MatchCheckInStatus",
    "MATCH_CHECKIN_TRANSITIONS",
    "AuditLog",
    "AuditAction",
    "AuditActorType",
    "IdempotencyKey",
    "IdempotencyKeyStatus",
]
