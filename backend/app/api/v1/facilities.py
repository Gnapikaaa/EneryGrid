from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.api.v1.errors import raise_http_from_service_error
from app.core.database import get_db
from app.models.user import User
from app.schemas.common import DEFAULT_PAGE, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PaginatedResponse
from app.schemas.facility import FacilityCreate, FacilityResponse, FacilityUpdate
from app.services import facilities as facility_service
from app.services.exceptions import (
    ConflictError,
    InvalidRelationError,
    PermissionDeniedError,
    ResourceNotFoundError,
)

router = APIRouter(prefix="/facilities", tags=["facilities"])


@router.get(
    "",
    response_model=PaginatedResponse[FacilityResponse],
    status_code=status.HTTP_200_OK,
    summary="List facilities with pagination and optional filters",
)
def list_facilities_endpoint(
    page: int = Query(default=DEFAULT_PAGE, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=160),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[FacilityResponse]:
    try:
        return facility_service.list_facilities(
            db,
            actor=current_user,
            page=page,
            page_size=page_size,
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
    response_model=FacilityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new facility (admin only)",
)
def create_facility_endpoint(
    payload: FacilityCreate,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FacilityResponse:
    try:
        return facility_service.create_facility(db, actor=current_admin, payload=payload)
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
    ) as exc:
        raise_http_from_service_error(exc)


@router.get(
    "/{facility_id}",
    response_model=FacilityResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve a facility by ID",
)
def get_facility_endpoint(
    facility_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FacilityResponse:
    try:
        return facility_service.get_facility(db, actor=current_user, facility_id=facility_id)
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
    ) as exc:
        raise_http_from_service_error(exc)


@router.patch(
    "/{facility_id}",
    response_model=FacilityResponse,
    status_code=status.HTTP_200_OK,
    summary="Update facility details (admin only)",
)
def update_facility_endpoint(
    facility_id: str,
    payload: FacilityUpdate,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FacilityResponse:
    try:
        return facility_service.update_facility(
            db,
            actor=current_admin,
            facility_id=facility_id,
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
    "/{facility_id}/deactivate",
    response_model=FacilityResponse,
    status_code=status.HTTP_200_OK,
    summary="Soft-deactivate a facility when no active zones or meters remain (admin only)",
)
def deactivate_facility_endpoint(
    facility_id: str,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> FacilityResponse:
    try:
        return facility_service.deactivate_facility(
            db,
            actor=current_admin,
            facility_id=facility_id,
        )
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
    ) as exc:
        raise_http_from_service_error(exc)


@router.delete(
    "/{facility_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a facility only when zero zones or dependent records exist (admin only)",
)
def delete_facility_endpoint(
    facility_id: str,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Response:
    try:
        facility_service.delete_facility(
            db,
            actor=current_admin,
            facility_id=facility_id,
        )
    except (
        PermissionDeniedError,
        ResourceNotFoundError,
        ConflictError,
        InvalidRelationError,
    ) as exc:
        raise_http_from_service_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
