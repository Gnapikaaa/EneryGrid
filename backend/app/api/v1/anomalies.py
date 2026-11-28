from datetime import datetime
from decimal import Decimal
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_analytics_operator
from app.api.v1.errors import raise_http_from_service_error
from app.core.constants import AnomalySeverity, AnomalyStatus
from app.core.database import get_db
from app.models.user import User
from app.schemas.anomaly import (
    AnomalyAcknowledgeRequest,
    AnomalyDetailResponse,
    AnomalyInvestigateRequest,
    AnomalyReopenRequest,
    AnomalyResolveRequest,
    AnomalyResponse,
    AnomalyWorkflowLogResponse,
)
from app.schemas.common import DEFAULT_PAGE, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PaginatedResponse
from app.services import anomalies as anomaly_service
from app.services.exceptions import (
    ConflictError,
    InvalidRelationError,
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationFailureError,
)

router = APIRouter(prefix="/anomalies", tags=["anomalies"])


@router.get(
    "",
    response_model=PaginatedResponse[AnomalyResponse],
    status_code=status.HTTP_200_OK,
    summary="List anomalies with pagination and optional facility, zone, meter, status, severity, and time filters",
)
def list_anomalies_endpoint(
    page: int = Query(default=DEFAULT_PAGE, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    facility_id: str | None = Query(default=None, min_length=2, max_length=64),
    zone_id: uuid.UUID | None = Query(default=None),
    meter_id: uuid.UUID | None = Query(default=None),
    status_filter: AnomalyStatus | None = Query(default=None, alias="status"),
    severity: AnomalySeverity | None = Query(default=None),
    min_z_score: Decimal | None = Query(default=None),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[AnomalyResponse]:
    try:
        return anomaly_service.list_anomalies(
            db,
            actor=current_user,
            page=page,
            page_size=page_size,
            facility_id=facility_id,
            zone_id=zone_id,
            meter_id=meter_id,
            status=status_filter,
            severity=severity,
            min_z_score=min_z_score,
            start_at=start_at,
            end_at=end_at,
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
    "/{anomaly_id}",
    response_model=AnomalyDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve full anomaly details including waveform arrays",
)
def get_anomaly_endpoint(
    anomaly_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnomalyDetailResponse:
    try:
        return anomaly_service.get_anomaly(db, actor=current_user, anomaly_id=anomaly_id)
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
        ValidationFailureError,
    ) as exc:
        raise_http_from_service_error(exc)


@router.get(
    "/{anomaly_id}/history",
    response_model=list[AnomalyWorkflowLogResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve chronological workflow audit logs for an anomaly",
)
def get_anomaly_history_endpoint(
    anomaly_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AnomalyWorkflowLogResponse]:
    try:
        return anomaly_service.get_anomaly_history(db, actor=current_user, anomaly_id=anomaly_id)
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
        ValidationFailureError,
    ) as exc:
        raise_http_from_service_error(exc)


@router.post(
    "/{anomaly_id}/acknowledge",
    response_model=AnomalyDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Acknowledge an Open anomaly (admin or utility_engineer)",
)
def acknowledge_anomaly_endpoint(
    anomaly_id: uuid.UUID,
    payload: AnomalyAcknowledgeRequest,
    current_actor: User = Depends(require_analytics_operator),
    db: Session = Depends(get_db),
) -> AnomalyDetailResponse:
    try:
        return anomaly_service.acknowledge_anomaly(
            db,
            actor=current_actor,
            anomaly_id=anomaly_id,
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


@router.post(
    "/{anomaly_id}/investigate",
    response_model=AnomalyDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign an Open or Acknowledged anomaly for investigation (admin or utility_engineer)",
)
def investigate_anomaly_endpoint(
    anomaly_id: uuid.UUID,
    payload: AnomalyInvestigateRequest,
    current_actor: User = Depends(require_analytics_operator),
    db: Session = Depends(get_db),
) -> AnomalyDetailResponse:
    try:
        return anomaly_service.investigate_anomaly(
            db,
            actor=current_actor,
            anomaly_id=anomaly_id,
            assigned_to_user_id=payload.assigned_to_user_id,
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


@router.post(
    "/{anomaly_id}/resolve",
    response_model=AnomalyDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve an anomaly with a required resolution note (admin or utility_engineer)",
)
def resolve_anomaly_endpoint(
    anomaly_id: uuid.UUID,
    payload: AnomalyResolveRequest,
    current_actor: User = Depends(require_analytics_operator),
    db: Session = Depends(get_db),
) -> AnomalyDetailResponse:
    try:
        return anomaly_service.resolve_anomaly(
            db,
            actor=current_actor,
            anomaly_id=anomaly_id,
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


@router.post(
    "/{anomaly_id}/reopen",
    response_model=AnomalyDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Reopen a Resolved anomaly back to Open status (admin or utility_engineer)",
)
def reopen_anomaly_endpoint(
    anomaly_id: uuid.UUID,
    payload: AnomalyReopenRequest,
    current_actor: User = Depends(require_analytics_operator),
    db: Session = Depends(get_db),
) -> AnomalyDetailResponse:
    try:
        return anomaly_service.reopen_anomaly(
            db,
            actor=current_actor,
            anomaly_id=anomaly_id,
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
