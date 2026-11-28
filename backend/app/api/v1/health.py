from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import check_database_connectivity, get_db
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service and PostgreSQL connectivity health check",
)
def health_check(
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    try:
        is_connected = check_database_connectivity(db)
    except (SQLAlchemyError, OSError):
        is_connected = False

    if not is_connected:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="degraded",
            service=settings.app_name,
            environment=settings.environment.value,
            database="unavailable",
            timestamp=datetime.now(UTC),
        )

    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.environment.value,
        database="connected",
        timestamp=datetime.now(UTC),
    )
