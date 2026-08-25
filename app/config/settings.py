"""
Application configuration using Pydantic Settings.
Loads and validates all environment variables in one place.
"""
from functools import lru_cache
from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings, populated from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------------- APP ----------------
    APP_NAME: str = "ClassyBattle"
    APP_ENV: str = "development"
    APP_DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    SECRET_KEY: str

    # ---------------- DATABASE ----------------
    DATABASE_URL: str
    DATABASE_URL_SYNC: str
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO: bool = False

    # ---------------- JWT ----------------
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # The Flutter app auto-refreshes the access token in the background
    # on every 401 (see ApiClient's refresh interceptor), so this only
    # matters as the "how long can a user go without opening the app
    # before being asked to log in again" window. Set long so a user
    # effectively stays logged in until they tap Logout.
    REFRESH_TOKEN_EXPIRE_DAYS: int = 365

    # ---------------- OTP ----------------
    OTP_LENGTH: int = 6
    OTP_EXPIRY_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RESEND_COOLDOWN_SECONDS: int = 60
    OTP_MAX_PER_HOUR: int = 5
    OTP_MAX_PER_DAY: int = 11

    # ---------------- SUPABASE ----------------
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_STORAGE_BUCKET: str = "classybattle-assets"

    # ---------------- BREVO ----------------
    BREVO_API_KEY: str = ""
    BREVO_SENDER_EMAIL: str = "noreply@classybattle.com"
    BREVO_SENDER_NAME: str = "ClassyBattle"

    # ---------------- FIREBASE ----------------
    FIREBASE_CREDENTIALS_PATH: str = "firebase-service-account.json"
    FIREBASE_PROJECT_ID: str = ""

    # ---------------- TELEGRAM ADMIN BOT ----------------
    # Leave TELEGRAM_BOT_TOKEN empty to disable the bot entirely (no
    # startup error, webhook route just responds 503).
    TELEGRAM_BOT_TOKEN: str = ""
    # Code a chat must send via /start <code> to become authorized.
    TELEGRAM_AUTH_CODE: str = "CB1245"
    # Secret path segment mixed into the webhook URL so it can't be
    # guessed/spammed by outsiders (Telegram doesn't sign requests).
    TELEGRAM_WEBHOOK_SECRET: str = ""
    # Email of the admin user the bot acts as when it approves/rejects
    # deposits via inline buttons.
    TELEGRAM_BOT_ADMIN_EMAIL: str = ""

    # ---------------- CORS ----------------
    CORS_ORIGINS: List[str] = ["*"]

    # ---------------- RATE LIMITING ----------------
    RATE_LIMIT_PER_MINUTE: int = 60
    AUTH_RATE_LIMIT: str = "10/minute"
    OTP_RATE_LIMIT: str = "5/minute"
    LOGIN_OTP_RATE_LIMIT: str = "2/5minute"
    # Shared storage backend for the rate limiter. Required in production
    # whenever the app runs with more than one uvicorn worker (see
    # docker-compose.prod.yml's --workers 4) — without it, each worker
    # keeps its own separate in-memory counters, so the *effective*
    # per-IP limit is actually (configured limit x worker count).
    # Leave empty to fall back to in-memory storage (fine for local dev
    # with a single worker only).
    REDIS_URL: str = ""

    # ---------------- PROXY / CLIENT IP ----------------
    # Number of trusted reverse-proxy hops in front of the app (e.g. Render's
    # own edge proxy = 1). Used to safely resolve the real client IP from
    # X-Forwarded-For without letting a client spoof it. See app/core/client_ip.py.
    TRUSTED_PROXY_COUNT: int = 1

    # ---------------- LOGGING ----------------
    LOG_LEVEL: str = "INFO"

    # ---------------- SENTRY ----------------
    # Leave empty to disable Sentry entirely (no startup error).
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    # ---------------- API DOCUMENTATION ----------------
    # Explicit override for exposing Swagger/Redoc/OpenAPI JSON. When left
    # unset (None), documentation is enabled automatically in every
    # environment except production. Set to true/false to force behaviour
    # regardless of APP_ENV (e.g. to expose docs on a staging environment
    # that has APP_ENV=production).
    ENABLE_API_DOCS: Optional[bool] = None

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            import json

            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def docs_enabled(self) -> bool:
        """Whether Swagger/Redoc/OpenAPI JSON should be publicly exposed.

        Controlled by ENABLE_API_DOCS when explicitly set; otherwise
        defaults to "enabled everywhere except production" so that docs
        never leak in a production deployment by accident.
        """
        if self.ENABLE_API_DOCS is not None:
            return self.ENABLE_API_DOCS
        return not self.is_production


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — avoids re-parsing env vars on every import."""
    return Settings()


settings = get_settings()