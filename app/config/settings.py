"""
Application configuration using Pydantic Settings.
Loads and validates all environment variables in one place.
"""
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
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
    APP_DEBUG: bool = True
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
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ---------------- OTP ----------------
    OTP_LENGTH: int = 6
    OTP_EXPIRY_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RESEND_COOLDOWN_SECONDS: int = 60
    OTP_MAX_PER_HOUR: int = 5

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

    # ---------------- CORS ----------------
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    # ---------------- RATE LIMITING ----------------
    RATE_LIMIT_PER_MINUTE: int = 60

    # ---------------- LOGGING ----------------
    LOG_LEVEL: str = "INFO"

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


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — avoids re-parsing env vars on every import."""
    return Settings()


settings = get_settings()
