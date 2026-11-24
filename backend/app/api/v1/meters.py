import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin, require_meter_updater
from app.api.v1.errors import raise_http_from_service_error
from app.core.constants import HealthStatus
from app.core.database import get_db
from app.models.user import User
from app.schemas.common import DEFAULT_PAGE, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PaginatedResponse
from app.schemas.facility import MeterCreate, MeterResponse, MeterUpdate
from app.services import meters as meter_service
from app.services.exceptions import (
    ConflictError,
    InvalidRelationError,
    PermissionDeniedError,
    ResourceNotFoundError,
)

router = APIRouter(prefix="/meters", tags=["meters"])


@router.get(
    "",
    response_model=PaginatedResponse[MeterResponse],
    status_code=status.HTTP_200_OK,
    summary="List meters with pagination and optional facility/zone/status filters",
)
def list_meters_endpoint(
    page: int = Query(default=DEFAULT_PAGE, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    facility_id: str | None = Query(default=None, min_length=2, max_length=64),
    zone_id: uuid.UUID | None = Query(default=None),
    status_filter: HealthStatus | None = Query(default=None, alias="status"),
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=160),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MeterResponse]:
    try:
        return meter_service.list_meters(
            db,
            actor=current_user,
            page=page,
            page_size=page_size,
            facility_id=facility_id,
            zone_id=zone_id,
            status=status_filter.value if status_filter is not None else None,
            is_active=is_active,
            search=search,
        )
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
    ) as exc:
        raise_http_from_service_error(exc)


@router.post(
    "",
    response_model=MeterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a meter under a valid active facility and zone (admin only)",
)
def register_meter_endpoint(
    payload: MeterCreate,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MeterResponse:
    try:
        return meter_service.register_meter(db, actor=current_admin, payload=payload)
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
    ) as exc:
        raise_http_from_service_error(exc)


@router.get(
    "/{meter_id}",
    response_model=MeterResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a meter by ID",
)
def get_meter_endpoint(
    meter_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeterResponse:
    try:
        return meter_service.get_meter(db, actor=current_user, meter_id=meter_id)
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
    ) as exc:
        raise_http_from_service_error(exc)


@router.patch(
    "/{meter_id}",
    response_model=MeterResponse,
    status_code=status.HTTP_200_OK,
    summary="Update meter details (admin or utility_engineer)",
)
def update_meter_endpoint(
    meter_id: uuid.UUID,
    payload: MeterUpdate,
    current_actor: User = Depends(require_meter_updater),
    db: Session = Depends(get_db),
) -> MeterResponse:
    try:
        return meter_service.update_meter(
            db,
            actor=current_actor,
            meter_id=meter_id,
            payload=payload,
        )
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
    ) as exc:
        raise_http_from_service_error(exc)


@router.post(
    "/{meter_id}/deactivate",
    response_model=MeterResponse,
    status_code=status.HTTP_200_OK,
    summary="Soft-deactivate a meter while preserving telemetry and calibration history (admin only)",
)
def deactivate_meter_endpoint(
    meter_id: uuid.UUID,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MeterResponse:
    try:
        return meter_service.deactivate_meter(
            db,
            actor=current_admin,
            meter_id=meter_id,
        )
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
    ) as exc:
        raise_http_from_service_error(exc)


@router.delete(
    "/{meter_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a meter only when zero telemetry, anomaly, or audit records exist (admin only)",
)
def delete_meter_endpoint(
    meter_id: uuid.UUID,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    try:
        meter_service.delete_meter(
            db,
            actor=current_admin,
            meter_id=meter_id,
        )
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
    ) as exc:
        raise_http_from_service_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
