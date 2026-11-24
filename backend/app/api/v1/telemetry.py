from datetime import datetime
import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_meter_updater
from app.api.v1.errors import raise_http_from_service_error
from app.core.config import Settings, get_settings
from app.core.constants import QualityFlag, TelemetrySource
from app.core.database import get_db
from app.models.user import User
from app.schemas.common import DEFAULT_PAGE, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PaginatedResponse
from app.schemas.telemetry import (
    TelemetryBulkIngestRequest,
    TelemetryIngestionSummary,
    TelemetryReadingCreate,
    TelemetryReadingResponse,
)
from app.services import telemetry as telemetry_service
from app.services.exceptions import (
    ConflictError,
    InvalidRelationError,
    PayloadTooLargeError,
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationFailureError,
)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

_HANDLED_SERVICE_ERRORS = (
    PermissionDeniedError,
    ResourceNotFoundError,
    ConflictError,
    InvalidRelationError,
    ValidationFailureError,
    PayloadTooLargeError,
)


@router.post(
    "/readings",
    response_model=TelemetryReadingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a single telemetry reading for an active meter (admin or utility_engineer)",
)
def ingest_single_reading_endpoint(
    payload: TelemetryReadingCreate,
    current_actor: User = Depends(require_meter_updater),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TelemetryReadingResponse:
    try:
        return telemetry_service.ingest_reading(
            db,
            actor=current_actor,
            payload=payload,
            settings=settings,
        )
    except _HANDLED_SERVICE_ERRORS as exc:
        raise_http_from_service_error(exc)


@router.post(
    "/readings/bulk",
    response_model=TelemetryIngestionSummary,
    status_code=status.HTTP_200_OK,
    summary="Ingest a batch of telemetry readings (defaults to atomic=false partial success)",
)
def ingest_bulk_readings_endpoint(
    payload: TelemetryBulkIngestRequest,
    current_actor: User = Depends(require_meter_updater),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TelemetryIngestionSummary:
    try:
        return telemetry_service.ingest_bulk_readings(
            db,
            actor=current_actor,
            payload=payload,
            settings=settings,
        )
    except _HANDLED_SERVICE_ERRORS as exc:
        raise_http_from_service_error(exc)


@router.post(
    "/readings/upload",
    response_model=TelemetryIngestionSummary,
    status_code=status.HTTP_200_OK,
    summary="Upload a CSV file of telemetry readings with streaming size and row limits",
)
async def upload_telemetry_csv_endpoint(
    file: UploadFile = File(...),
    atomic: bool = Query(default=False),
    current_actor: User = Depends(require_meter_updater),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TelemetryIngestionSummary:
    try:
        return await telemetry_service.ingest_csv_upload(
            db,
            actor=current_actor,
            upload_file=file,
            settings=settings,
            atomic=atomic,
        )
    except _HANDLED_SERVICE_ERRORS as exc:
        raise_http_from_service_error(exc)


@router.get(
    "/readings",
    response_model=PaginatedResponse[TelemetryReadingResponse],
    status_code=status.HTTP_200_OK,
    summary="Query stored telemetry readings with facility, zone, meter, and date-range filters",
)
def list_telemetry_readings_endpoint(
    page: int = Query(default=DEFAULT_PAGE, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    facility_id: str | None = Query(default=None, min_length=2, max_length=64),
    zone_id: uuid.UUID | None = Query(default=None),
    meter_id: uuid.UUID | None = Query(default=None),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    quality_flag: QualityFlag | None = Query(default=None),
    source: TelemetrySource | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[TelemetryReadingResponse]:
    try:
        return telemetry_service.list_telemetry_readings(
            db,
            actor=current_user,
            page=page,
            page_size=page_size,
            facility_id=facility_id,
            zone_id=zone_id,
            meter_id=meter_id,
            start_at=start_at,
            end_at=end_at,
            quality_flag=quality_flag,
            source=source,
        )
    except _HANDLED_SERVICE_ERRORS as exc:
        raise_http_from_service_error(exc)
