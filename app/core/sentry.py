"""
Sentry error-monitoring setup.

Initialized once during FastAPI startup (see `app/main.py`). Disabled
gracefully — no startup error — whenever `SENTRY_DSN` is empty, so local
dev and any environment without a DSN configured keep working unchanged.
"""
from app.config.settings import settings
from app.core.logging import get_logger

logger = get_logger("sentry")


def init_sentry() -> None:
    """Initialize Sentry if SENTRY_DSN is configured; no-op otherwise."""
    if not settings.SENTRY_DSN:
        logger.info("sentry_disabled", reason="SENTRY_DSN not set")
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.APP_ENV,
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            integrations=[
                StarletteIntegration(),
                FastApiIntegration(),
            ],
            # Unhandled exceptions (including those raised inside
            # BackgroundTasks, which run within the same asyncio context)
            # are captured automatically by these integrations.
        )
        logger.info("sentry_enabled", environment=settings.APP_ENV)
    except Exception as exc:  # pragma: no cover - defensive, never block startup
        logger.error("sentry_init_failed", error=str(exc))
