import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_analytics_operator
from app.api.v1.errors import raise_http_from_service_error
from app.core.constants import InsightCategory, InsightPriority, InsightStatus
from app.core.database import get_db
from app.models.user import User
from app.schemas.common import DEFAULT_PAGE, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PaginatedResponse
from app.schemas.insight import (
    InsightDetailResponse,
    InsightResponse,
    InsightStatusUpdateRequest,
    InsightWorkflowLogResponse,
)
from app.services import insights as insight_service
from app.services.exceptions import (
    ConflictError,
    InvalidRelationError,
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationFailureError,
)

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get(
    "",
    response_model=PaginatedResponse[InsightResponse],
    status_code=status.HTTP_200_OK,
    summary="List energy insights with pagination and optional facility, zone, meter, status, priority, and category filters",
)
def list_insights_endpoint(
    page: int = Query(default=DEFAULT_PAGE, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    facility_id: str | None = Query(default=None, min_length=2, max_length=64),
    zone_id: uuid.UUID | None = Query(default=None),
    meter_id: uuid.UUID | None = Query(default=None),
    status_filter: InsightStatus | None = Query(default=None, alias="status"),
    priority: InsightPriority | None = Query(default=None),
    category: InsightCategory | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[InsightResponse]:
    try:
        return insight_service.list_insights(
            db,
            actor=current_user,
            page=page,
            page_size=page_size,
            facility_id=facility_id,
            zone_id=zone_id,
            meter_id=meter_id,
            status=status_filter,
            priority=priority,
            category=category,
        )
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
        ValidationFailureError,
    ) as exc:
        raise_http_from_service_error(exc)


@router.get(
    "/{insight_id}",
    response_model=InsightDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve full energy insight details including structured rule evidence",
)
def get_insight_endpoint(
    insight_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InsightDetailResponse:
    try:
        return insight_service.get_insight(db, actor=current_user, insight_id=insight_id)
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
        ValidationFailureError,
    ) as exc:
        raise_http_from_service_error(exc)


@router.get(
    "/{insight_id}/history",
    response_model=list[InsightWorkflowLogResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve chronological workflow audit logs for an energy insight",
)
def get_insight_history_endpoint(
    insight_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[InsightWorkflowLogResponse]:
    try:
        return insight_service.get_insight_history(db, actor=current_user, insight_id=insight_id)
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
        ValidationFailureError,
    ) as exc:
        raise_http_from_service_error(exc)


@router.patch(
    "/{insight_id}",
    response_model=InsightDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Update insight status with deduplication reactivation conflict guard (admin or utility_engineer)",
)
def update_insight_status_endpoint(
    insight_id: uuid.UUID,
    payload: InsightStatusUpdateRequest,
    current_actor: User = Depends(require_analytics_operator),
    db: Session = Depends(get_db),
) -> InsightDetailResponse:
    try:
        return insight_service.update_insight_status(
            db,
            actor=current_actor,
            insight_id=insight_id,
            new_status=payload.status,
            note=payload.note,
        )
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
        ValidationFailureError,
    ) as exc:
        raise_http_from_service_error(exc)
