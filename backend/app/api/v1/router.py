from fastapi import APIRouter

from app.api.v1.analytics import router as analytics_router
from app.api.v1.anomalies import router as anomalies_router
from app.api.v1.auth import router as auth_router
from app.api.v1.facilities import router as facilities_router
from app.api.v1.health import router as health_router
from app.api.v1.insights import router as insights_router
from app.api.v1.meters import router as meters_router
from app.api.v1.telemetry import router as telemetry_router
from app.api.v1.users import router as users_router
from app.api.v1.zones import router as zones_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(facilities_router)
api_router.include_router(zones_router)
api_router.include_router(meters_router)
api_router.include_router(telemetry_router)
api_router.include_router(analytics_router)
api_router.include_router(anomalies_router)
api_router.include_router(insights_router)
