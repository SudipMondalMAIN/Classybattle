"""
Import every model here so Alembic's autogenerate can discover them
via Base.metadata.
"""
from app.database.base import Base
from app.models.device_token import DeviceToken
from app.models.game import Game
from app.models.game_mode import GameMode
from app.models.game_profile import UserGameProfile
from app.models.map import Map
from app.models.notification import Notification
from app.models.otp import OTP
from app.models.refresh_token import RefreshToken
from app.models.tournament import Tournament, TournamentStatus, TournamentVisibility
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
]
