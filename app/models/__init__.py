"""
Import every model here so Alembic's autogenerate can discover them
via Base.metadata.
"""
from app.database.base import Base
from app.models.audit_log import AuditAction, AuditActorType, AuditLog
from app.models.device_token import DeviceToken
from app.models.idempotency_key import IdempotencyKey, IdempotencyKeyStatus
from app.models.leaderboard import (
    LeaderboardPeriodType,
    LeaderboardSourceEvent,
    LeaderboardUpdateLog,
    PlayerPeriodStats,
    PlayerStatistics,
    RankHistory,
    RankingScope,
    TeamPeriodStats,
    TeamStatistics,
)
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
from app.models.match_result import (
    MATCH_RESULT_STATUS_TRANSITIONS,
    MatchResult,
    MatchResultStatus,
)
from app.models.match_winner import MatchWinner, WinnerAssignmentSource
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
from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationEventType,
    NotificationPreference,
    NotificationStatus,
)
from app.models.otp import OTP
from app.models.participant import (
    Participant,
    ParticipantPaymentStatus,
    ParticipantStatus,
    RegistrationType,
)
from app.models.prize import (
    PRIZE_POOL_STATUS_TRANSITIONS,
    PrizeDistributionType,
    PrizePayout,
    PrizePayoutStatus,
    PrizePool,
    PrizePoolStatus,
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
from app.models.wallet import Wallet
from app.models.wallet_transaction import (
    WalletTransaction,
    WalletTransactionStatus,
    WalletTransactionType,
)

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
    "NotificationChannel",
    "NotificationStatus",
    "NotificationEventType",
    "NotificationPreference",
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
    "Wallet",
    "WalletTransaction",
    "WalletTransactionType",
    "WalletTransactionStatus",
    "PrizePool",
    "PrizePoolStatus",
    "PrizeDistributionType",
    "PRIZE_POOL_STATUS_TRANSITIONS",
    "PrizePayout",
    "PrizePayoutStatus",
    "MatchResult",
    "MatchResultStatus",
    "MATCH_RESULT_STATUS_TRANSITIONS",
    "MatchWinner",
    "WinnerAssignmentSource",
    "LiveMatch",
    "LiveMatchStatus",
    "LIVE_MATCH_STATUS_TRANSITIONS",
    "LiveMatchEvent",
    "LiveMatchEventType",
    "LiveMatchScore",
    "LiveTournamentState",
    "LiveTournamentStatus",
    "PlayerStatistics",
    "TeamStatistics",
    "PlayerPeriodStats",
    "TeamPeriodStats",
    "RankHistory",
    "RankingScope",
    "LeaderboardPeriodType",
    "LeaderboardSourceEvent",
    "LeaderboardUpdateLog",
]
