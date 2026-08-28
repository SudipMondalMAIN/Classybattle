"""
Import every model here so Alembic's autogenerate can discover them
via Base.metadata.
"""
from app.database.base import Base
from app.models.app_version import AppPlatform, AppVersion
from app.models.maintenance import MaintenanceConfig
from app.models.telegram_chat import TelegramAuthorizedChat
from app.models.achievement import (
    Achievement,
    AchievementComparison,
    AchievementTriggerType,
    Badge,
    BadgeTier,
    UserAchievement,
)
from app.models.moderation import (
    Appeal,
    AppealStatus,
    ModerationAction,
    ModerationActionStatus,
    ModerationActionType,
    Report,
    ReportReason,
    ReportStatus,
    ReportTargetType,
)
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
from app.models.tournament_participant import (
    TOURNAMENT_CHECKIN_TRANSITIONS,
    TournamentAssignmentType,
    TournamentCheckInStatus,
    TournamentParticipant,
)
from app.models.custom_match_claim import (
    CustomMatchClaim,
    CustomMatchClaimOutcome,
    CustomMatchClaimStatus,
)
from app.models.tournament_result import (
    TOURNAMENT_RESULT_STATUS_TRANSITIONS,
    TournamentResult,
    TournamentResultStatus,
)
from app.models.tournament_team import TournamentTeam, TournamentTeamMember, TournamentTeamStatus
from app.models.tournament_winner import TournamentWinner, WinnerAssignmentSource
from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationEventType,
    NotificationPreference,
    NotificationStatus,
)
from app.models.otp import OTP
from app.models.payment import (
    PaymentProvider,
    PaymentRejectionReason,
    PaymentRequest,
    PaymentRequestStatus,
    PaymentSettings,
)
from app.models.payment_method import PaymentMethod, PaymentMethodType
from app.models.withdrawal import WithdrawalRequest, WithdrawalStatus
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
from app.models.security import (
    AccountLock,
    AnalyticsMetricType,
    AnalyticsPeriodType,
    AnalyticsSnapshot,
    FraudFlag,
    FraudFlagStatus,
    FraudFlagType,
    LoginHistory,
    SecurityEvent,
    SecurityEventSeverity,
    SecurityEventType,
)
from app.models.support_chat import (
    SupportChatClosedBy,
    SupportChatMessage,
    SupportChatSenderType,
    SupportChatSession,
    SupportChatStatus,
)
from app.models.social import (
    ActivityFeedEntry,
    ActivityType,
    Follow,
    Friendship,
    FriendshipStatus,
    PlayerProfile,
    ProfileVisibility,
)
from app.models.team import Team, TeamStatus
from app.models.team_member import TeamMember, TeamMemberRole
from app.models.team_community import (
    MEMBER_HISTORY_ACTIVITY_TYPES,
    TeamActivityFeedEntry,
    TeamActivityType,
    TeamAnnouncement,
    TeamInvitation,
    TeamInvitationStatus,
    TeamJoinRequest,
    TeamJoinRequestStatus,
)
from app.models.tournament import (
    TOURNAMENT_STATUS_TRANSITIONS,
    ScheduleCategory,
    TeamFormat,
    TeamRegistrationMode,
    Tournament,
    TournamentStatus,
    TournamentVisibility,
)
from app.models.user import User
from app.models.referral import (
    DEFAULT_MILESTONE_RULES,
    Referral,
    ReferralConfig,
    ReferralMilestoneClaim,
    ReferralStatus,
)
from app.models.wallet import Wallet
from app.models.wallet_transaction import (
    WalletTransaction,
    WalletTransactionStatus,
    WalletTransactionType,
)

__all__ = [
    "Base",
    "AppVersion",
    "AppPlatform",
    "MaintenanceConfig",
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
    "TOURNAMENT_STATUS_TRANSITIONS",
    "ScheduleCategory",
    "TournamentParticipant",
    "TournamentAssignmentType",
    "TournamentCheckInStatus",
    "TOURNAMENT_CHECKIN_TRANSITIONS",
    "TournamentTeam",
    "TournamentTeamMember",
    "TournamentTeamStatus",
    "TeamFormat",
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
    "TournamentResult",
    "TournamentResultStatus",
    "TOURNAMENT_RESULT_STATUS_TRANSITIONS",
    "TournamentWinner",
    "WinnerAssignmentSource",
    "CustomMatchClaim",
    "CustomMatchClaimOutcome",
    "CustomMatchClaimStatus",
    "PlayerStatistics",
    "TeamStatistics",
    "PlayerPeriodStats",
    "TeamPeriodStats",
    "RankHistory",
    "RankingScope",
    "LeaderboardPeriodType",
    "LeaderboardSourceEvent",
    "LeaderboardUpdateLog",
    "PlayerProfile",
    "ProfileVisibility",
    "Friendship",
    "FriendshipStatus",
    "Follow",
    "ActivityFeedEntry",
    "ActivityType",
    "TeamInvitation",
    "TeamInvitationStatus",
    "TeamJoinRequest",
    "TeamJoinRequestStatus",
    "TeamAnnouncement",
    "TeamActivityFeedEntry",
    "TeamActivityType",
    "MEMBER_HISTORY_ACTIVITY_TYPES",
    "Achievement",
    "AchievementComparison",
    "AchievementTriggerType",
    "Badge",
    "BadgeTier",
    "UserAchievement",
    "Appeal",
    "AppealStatus",
    "ModerationAction",
    "ModerationActionStatus",
    "ModerationActionType",
    "Report",
    "ReportReason",
    "ReportStatus",
    "ReportTargetType",
    "LoginHistory",
    "SecurityEvent",
    "SecurityEventType",
    "SecurityEventSeverity",
    "AccountLock",
    "FraudFlag",
    "FraudFlagType",
    "FraudFlagStatus",
    "AnalyticsSnapshot",
    "AnalyticsMetricType",
    "AnalyticsPeriodType",
    "PaymentSettings",
    "PaymentRequest",
    "PaymentProvider",
    "PaymentRequestStatus",
    "PaymentRejectionReason",
    "PaymentMethod",
    "PaymentMethodType",
    "WithdrawalRequest",
    "WithdrawalStatus",
    "SupportChatSession",
    "SupportChatMessage",
    "SupportChatStatus",
    "SupportChatClosedBy",
    "SupportChatSenderType",
]