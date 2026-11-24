from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import require_analytics_operator
from app.api.v1.errors import raise_http_from_service_error
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.analytics import AnalyticsProcessRequest, AnalyticsProcessSummary
from app.services import analytics as analytics_service
from app.services.exceptions import (
    ConflictError,
    InvalidRelationError,
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationFailureError,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post(
    "/process",
    response_model=AnalyticsProcessSummary,
    status_code=status.HTTP_200_OK,
    summary="Synchronously process bounded batches of baselines, anomalies, and energy insights (admin or utility_engineer)",
)
def process_analytics_endpoint(
    payload: AnalyticsProcessRequest,
    current_actor: User = Depends(require_analytics_operator),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AnalyticsProcessSummary:
    try:
        return analytics_service.process_analytics_batch(
            db,
            actor=current_actor,
            payload=payload,
            settings=settings,
        )
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
        ValidationFailureError,
    ) as exc:
        raise_http_from_service_error(exc)
