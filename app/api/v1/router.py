"""
Aggregates all v1 routers into a single APIRouter.
"""
from fastapi import APIRouter

from app.api.v1.achievement_routes import router as achievement_router
from app.api.v1.admin_dashboard_routes import router as admin_dashboard_router
from app.api.v1.admin_user_routes import router as admin_user_router
from app.api.v1.anti_cheat_routes import router as anti_cheat_router
from app.api.v1.security_routes import router as security_router
from app.api.v1.auth_routes import router as auth_router
from app.api.v1.game_mode_routes import router as game_mode_router
from app.api.v1.game_routes import router as game_router
from app.api.v1.health_routes import router as health_router
from app.api.v1.leaderboard_routes import router as leaderboard_router
from app.api.v1.map_routes import router as map_router
from app.api.v1.match_result_routes import router as match_result_router
from app.api.v1.live_match_routes import router as live_match_router
from app.api.v1.match_routes import router as match_router
from app.api.v1.match_admin_routes import router as match_admin_router
from app.api.v1.moderation_routes import router as moderation_router
from app.api.v1.notification_routes import router as notification_router
from app.api.v1.participant_routes import router as participant_router
from app.api.v1.payment_routes import router as payment_router
from app.api.v1.payment_method_routes import router as payment_method_router
from app.api.v1.withdrawal_routes import router as withdrawal_router
from app.api.v1.prize_routes import router as prize_router
from app.api.v1.social_routes import router as social_router
from app.api.v1.team_community_routes import router as team_community_router
from app.api.v1.team_routes import router as team_router
from app.api.v1.schedule_routes import router as schedule_router
from app.api.v1.slot_routes import router as slot_router
from app.api.v1.tournament_routes import router as tournament_router
from app.api.v1.user_routes import router as user_router
from app.api.v1.wallet_routes import router as wallet_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(user_router)
api_v1_router.include_router(wallet_router)
api_v1_router.include_router(payment_router)
api_v1_router.include_router(payment_method_router)
api_v1_router.include_router(withdrawal_router)
api_v1_router.include_router(game_router)
api_v1_router.include_router(game_mode_router)
api_v1_router.include_router(map_router)
api_v1_router.include_router(schedule_router)
api_v1_router.include_router(slot_router)
api_v1_router.include_router(participant_router)
api_v1_router.include_router(prize_router)
api_v1_router.include_router(team_router)
api_v1_router.include_router(team_community_router)
api_v1_router.include_router(tournament_router)
api_v1_router.include_router(match_router)
api_v1_router.include_router(match_admin_router)
api_v1_router.include_router(match_result_router)
api_v1_router.include_router(live_match_router)
api_v1_router.include_router(notification_router)
api_v1_router.include_router(leaderboard_router)
api_v1_router.include_router(social_router)
api_v1_router.include_router(achievement_router)
api_v1_router.include_router(moderation_router)
api_v1_router.include_router(admin_dashboard_router)
api_v1_router.include_router(admin_user_router)
api_v1_router.include_router(security_router)
api_v1_router.include_router(anti_cheat_router)