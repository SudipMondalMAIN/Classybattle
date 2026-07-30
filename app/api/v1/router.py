"""
Aggregates all v1 routers into a single APIRouter.
"""
from fastapi import APIRouter

from app.api.v1.auth_routes import router as auth_router
from app.api.v1.game_mode_routes import router as game_mode_router
from app.api.v1.game_routes import router as game_router
from app.api.v1.health_routes import router as health_router
from app.api.v1.map_routes import router as map_router
from app.api.v1.match_routes import router as match_router
from app.api.v1.participant_routes import router as participant_router
from app.api.v1.team_routes import router as team_router
from app.api.v1.tournament_routes import router as tournament_router
from app.api.v1.user_routes import router as user_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(user_router)
api_v1_router.include_router(game_router)
api_v1_router.include_router(game_mode_router)
api_v1_router.include_router(map_router)
api_v1_router.include_router(tournament_router)
api_v1_router.include_router(participant_router)
api_v1_router.include_router(team_router)
api_v1_router.include_router(match_router)
