"""
Aggregates all v2 routers into a single APIRouter.
"""
from fastapi import APIRouter

from app.api.v2.admin_referral_routes import router as admin_referral_router
from app.api.v2.referral_routes import router as referral_router

api_v2_router = APIRouter()
api_v2_router.include_router(referral_router)
api_v2_router.include_router(admin_referral_router)
