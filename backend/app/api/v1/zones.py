import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.api.v1.errors import raise_http_from_service_error
from app.core.constants import HealthStatus
from app.core.database import get_db
from app.models.user import User
from app.schemas.common import DEFAULT_PAGE, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PaginatedResponse
from app.schemas.facility import ZoneCreate, ZoneResponse, ZoneUpdate
from app.services import zones as zone_service
from app.services.exceptions import (
    ConflictError,
    InvalidRelationError,
    PermissionDeniedError,
    ResourceNotFoundError,
)

router = APIRouter(prefix="/zones", tags=["zones"])


@router.get(
    "",
    response_model=PaginatedResponse[ZoneResponse],
    status_code=status.HTTP_200_OK,
    summary="List zones with pagination and optional facility/status filters",
)
def list_zones_endpoint(
    page: int = Query(default=DEFAULT_PAGE, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    facility_id: str | None = Query(default=None, min_length=2, max_length=64),
    status_filter: HealthStatus | None = Query(default=None, alias="status"),
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=160),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ZoneResponse]:
    try:
        return zone_service.list_zones(
            db,
            actor=current_user,
            page=page,
            page_size=page_size,
            facility_id=facility_id,
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
    response_model=ZoneResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a zone under an active facility (admin only)",
)
def create_zone_endpoint(
    payload: ZoneCreate,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ZoneResponse:
    try:
        return zone_service.create_zone(db, actor=current_admin, payload=payload)
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
    ) as exc:
        raise_http_from_service_error(exc)


@router.get(
    "/{zone_id}",
    response_model=ZoneResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a zone by ID",
)
def get_zone_endpoint(
    zone_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ZoneResponse:
    try:
        return zone_service.get_zone(db, actor=current_user, zone_id=zone_id)
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
    ) as exc:
        raise_http_from_service_error(exc)


@router.patch(
    "/{zone_id}",
    response_model=ZoneResponse,
    status_code=status.HTTP_200_OK,
    summary="Update zone details (admin only)",
)
def update_zone_endpoint(
    zone_id: uuid.UUID,
    payload: ZoneUpdate,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ZoneResponse:
    try:
        return zone_service.update_zone(
            db,
            actor=current_admin,
            zone_id=zone_id,
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
    "/{zone_id}/deactivate",
    response_model=ZoneResponse,
    status_code=status.HTTP_200_OK,
    summary="Soft-deactivate a zone when no active meters remain (admin only)",
)
def deactivate_zone_endpoint(
    zone_id: uuid.UUID,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ZoneResponse:
    try:
        return zone_service.deactivate_zone(
            db,
            actor=current_admin,
            zone_id=zone_id,
        )
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
    ) as exc:
        raise_http_from_service_error(exc)


@router.delete(
    "/{zone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a zone only when zero meters or dependent records exist (admin only)",
)
def delete_zone_endpoint(
    zone_id: uuid.UUID,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    try:
        zone_service.delete_zone(
            db,
            actor=current_admin,
            zone_id=zone_id,
        )
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
    ) as exc:
        raise_http_from_service_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
