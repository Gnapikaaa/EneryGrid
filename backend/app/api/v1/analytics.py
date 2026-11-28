from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_analytics_operator
from app.api.v1.errors import raise_http_from_service_error
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.analytics import (
    AnalyticsProcessRequest,
    AnalyticsProcessSummary,
    AnalyticsSummaryResponse,
)
from app.services import analytics as analytics_service
from app.services.analytics_summary_math import SummaryWindow
from app.services.exceptions import (
    ConflictError,
    InvalidRelationError,
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationFailureError,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get(
    "/summary",
    response_model=AnalyticsSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Compute facility KPIs, average/peak demand, consumption trends, zone breakdown, live meter snapshots, series buckets, and 7x24 heatmap from stored PostgreSQL readings",
)
def get_analytics_summary_endpoint(
    facility_id: str = Query(..., min_length=2, max_length=64),
    zone_id: uuid.UUID | None = Query(default=None),
    time_window: SummaryWindow = Query(default="24h"),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    include_simulated: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnalyticsSummaryResponse:
    try:
        return analytics_service.get_analytics_summary(
            db,
            actor=current_user,
            facility_id=facility_id,
            zone_id=zone_id,
            time_window=time_window,
            start_at=start_at,
            end_at=end_at,
            include_simulated=include_simulated,
        )
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
        ValidationFailureError,
    ) as exc:
        raise_http_from_service_error(exc)


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

