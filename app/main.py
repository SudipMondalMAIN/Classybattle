"""
ClassyBattle API — application entrypoint.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.router import api_v1_router
from app.api.v2.router import api_v2_router
from app.config.settings import settings
from app.core.logging import configure_logging, get_logger
from app.core.scheduler import start_slot_scheduler, stop_slot_scheduler
from app.core.sentry import init_sentry
from app.middleware.exception_handlers import register_exception_handlers
from app.middleware.logging_middleware import RequestLoggingMiddleware
from app.middleware.rate_limiter import limiter
from app.notifications.push_service import init_firebase

configure_logging()
init_sentry()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app_starting", env=settings.APP_ENV)
    init_firebase()
    start_slot_scheduler()
    yield
    stop_slot_scheduler()
    logger.info("app_shutting_down")


def create_app() -> FastAPI:
    docs_enabled = settings.docs_enabled
    logger.info("api_docs_configuration", enabled=docs_enabled, env=settings.APP_ENV)

    app = FastAPI(
        title=settings.APP_NAME,
        description="ClassyBattle eSports Tournament Platform API — Phases 1-7: Foundation, Auth, Tournament Core, Game Modes, Registration & Team System, Room Management & Match Lifecycle",
        version="1.0.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)

    # Request logging
    app.add_middleware(RequestLoggingMiddleware)

    # Global exception handlers
    register_exception_handlers(app)

    # Routes
    app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)
    app.include_router(api_v2_router, prefix=settings.API_V2_PREFIX)

    return app


async def _rate_limit_handler(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=429,
        content={
            "success": False,
            "error_code": "TOO_MANY_REQUESTS",
            "message": "Rate limit exceeded. Please slow down.",
            "details": None,
        },
    )


app = create_app()
