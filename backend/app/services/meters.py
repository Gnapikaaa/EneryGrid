from datetime import UTC, datetime
import math
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.anomaly import Anomaly
from app.models.audit import MeterCalibrationAudit
from app.models.facility import Facility, Meter, Zone
from app.models.telemetry import TelemetryReading
from app.models.user import User
from app.schemas.common import DEFAULT_PAGE, DEFAULT_PAGE_SIZE, PaginatedResponse
from app.schemas.facility import MeterCreate, MeterResponse, MeterUpdate
from app.services.exceptions import (
    ConflictError,
    InvalidRelationError,
    ResourceNotFoundError,
)
from app.services.permissions import (
    ADMIN_ONLY_ROLES,
    ALL_AUTHENTICATED_ROLES,
    METER_UPDATE_ROLES,
    assert_actor_authorized,
)


def list_meters(
    db: Session,
    *,
    actor: User,
    page: int = DEFAULT_PAGE,
    page_size: int = DEFAULT_PAGE_SIZE,
    facility_id: str | None = None,
    zone_id: uuid.UUID | None = None,
    status: str | None = None,
    is_active: bool | None = None,
    search: str | None = None,
) -> PaginatedResponse[MeterResponse]:
    assert_actor_authorized(actor, ALL_AUTHENTICATED_ROLES)

    filters = []
    if facility_id is not None:
        filters.append(Meter.facility_id == facility_id)
    if zone_id is not None:
        filters.append(Meter.zone_id == zone_id)
    if status is not None:
        filters.append(Meter.status == status)
    if is_active is not None:
        filters.append(Meter.is_active.is_(is_active))
    if search is not None:
        term = search.strip()
        if term:
            pattern = f"%{term}%"
            filters.append(
                Meter.meter_code.ilike(pattern) | Meter.equipment_name.ilike(pattern)
            )

    total = int(db.scalar(select(func.count(Meter.id)).where(*filters)) or 0)
    offset = (page - 1) * page_size
    meters = list(
        db.scalars(
            select(Meter)
            .where(*filters)
            .order_by(Meter.facility_id.asc(), Meter.meter_code.asc(), Meter.id.asc())
            .offset(offset)
            .limit(page_size)
        ).all()
    )

    items = [MeterResponse.model_validate(meter) for meter in meters]
    pages = math.ceil(total / page_size) if total > 0 else 0
    return PaginatedResponse[MeterResponse](
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


def get_meter(
    db: Session,
    *,
    actor: User,
    meter_id: uuid.UUID,
) -> MeterResponse:
    assert_actor_authorized(actor, ALL_AUTHENTICATED_ROLES)

    meter = db.get(Meter, meter_id)
    if meter is None:
        raise ResourceNotFoundError(f"Meter '{meter_id}' not found.")

    return MeterResponse.model_validate(meter)


def register_meter(
    db: Session,
    *,
    actor: User,
    payload: MeterCreate,
) -> MeterResponse:
    assert_actor_authorized(actor, ADMIN_ONLY_ROLES)

    # Consistent top-down lock order: Facility -> Zone
    facility = db.scalar(
        select(Facility)
        .where(Facility.id == payload.facility_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if facility is None:
        db.rollback()
        raise ResourceNotFoundError(f"Facility '{payload.facility_id}' not found.")

    zone = db.scalar(
        select(Zone)
        .where(Zone.id == payload.zone_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if zone is None:
        db.rollback()
        raise ResourceNotFoundError(f"Zone '{payload.zone_id}' not found.")

    if zone.facility_id != payload.facility_id:
        db.rollback()
        raise InvalidRelationError(
            f"Zone '{payload.zone_id}' does not belong to facility '{payload.facility_id}'."
        )

    if not facility.is_active:
        db.rollback()
        raise ConflictError(
            f"Cannot register meter under deactivated facility '{payload.facility_id}'."
        )

    if not zone.is_active:
        db.rollback()
        raise ConflictError(
            f"Cannot register meter under deactivated zone '{payload.zone_id}'."
        )

    duplicate_code = db.scalar(
        select(Meter.id).where(func.lower(Meter.meter_code) == payload.meter_code.lower())
    )
    if duplicate_code is not None:
        db.rollback()
        raise ConflictError(f"A meter with code '{payload.meter_code}' already exists.")

    meter = Meter(
        facility_id=payload.facility_id,
        zone_id=payload.zone_id,
        meter_code=payload.meter_code,
        equipment_name=payload.equipment_name,
        rated_kw=payload.rated_kw,
        nominal_interval_seconds=payload.nominal_interval_seconds,
        current_kw=payload.current_kw,
        power_factor=payload.power_factor,
        thd_pct=payload.thd_pct,
        status=payload.status.value,
        last_calibrated_at=payload.last_calibrated_at,
        is_active=True,
        deactivated_at=None,
    )
    db.add(meter)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Meter code already exists.") from exc

    db.refresh(meter)
    return MeterResponse.model_validate(meter)


def update_meter(
    db: Session,
    *,
    actor: User,
    meter_id: uuid.UUID,
    payload: MeterUpdate,
) -> MeterResponse:
    assert_actor_authorized(actor, METER_UPDATE_ROLES)

    # Acquire locks in consistent top-down order if zone reassignment is requested
    if payload.zone_id is not None:
        target_zone = db.scalar(
            select(Zone)
            .where(Zone.id == payload.zone_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if target_zone is None:
            db.rollback()
            raise ResourceNotFoundError(f"Zone '{payload.zone_id}' not found.")
    else:
        target_zone = None

    meter = db.scalar(
        select(Meter)
        .where(Meter.id == meter_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meter is None:
        db.rollback()
        raise ResourceNotFoundError(f"Meter '{meter_id}' not found.")

    if target_zone is not None and target_zone.id != meter.zone_id:
        if target_zone.facility_id != meter.facility_id:
            db.rollback()
            raise InvalidRelationError(
                f"Target zone '{target_zone.id}' does not belong to meter facility '{meter.facility_id}'."
            )
        if not target_zone.is_active:
            db.rollback()
            raise ConflictError(
                f"Cannot move meter into deactivated zone '{target_zone.id}'."
            )
        has_telemetry = db.scalar(
            select(TelemetryReading.id).where(TelemetryReading.meter_id == meter_id).limit(1)
        )
        has_anomalies = db.scalar(
            select(Anomaly.id).where(Anomaly.meter_id == meter_id).limit(1)
        )
        if has_telemetry is not None or has_anomalies is not None:
            db.rollback()
            raise ConflictError(
                "Cannot reassign meter zone while telemetry or anomaly history exists."
            )

    if payload.meter_code is not None and payload.meter_code.lower() != meter.meter_code.lower():
        conflict_id = db.scalar(
            select(Meter.id).where(
                func.lower(Meter.meter_code) == payload.meter_code.lower(),
                Meter.id != meter_id,
            )
        )
        if conflict_id is not None:
            db.rollback()
            raise ConflictError(f"A meter with code '{payload.meter_code}' already exists.")

    for field_name in payload.model_fields_set:
        value = getattr(payload, field_name)
        if field_name == "status" and value is not None:
            value = value.value
        setattr(meter, field_name, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Meter update conflicts with existing meter data.") from exc

    db.refresh(meter)
    return MeterResponse.model_validate(meter)


def deactivate_meter(
    db: Session,
    *,
    actor: User,
    meter_id: uuid.UUID,
) -> MeterResponse:
    assert_actor_authorized(actor, ADMIN_ONLY_ROLES)

    meter = db.scalar(
        select(Meter)
        .where(Meter.id == meter_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meter is None:
        db.rollback()
        raise ResourceNotFoundError(f"Meter '{meter_id}' not found.")

    if not meter.is_active:
        db.rollback()
        raise ConflictError(f"Meter '{meter_id}' is already deactivated.")

    meter.is_active = False
    meter.deactivated_at = datetime.now(UTC)
    db.commit()
    db.refresh(meter)
    return MeterResponse.model_validate(meter)


def delete_meter(
    db: Session,
    *,
    actor: User,
    meter_id: uuid.UUID,
) -> None:
    assert_actor_authorized(actor, ADMIN_ONLY_ROLES)

    meter = db.scalar(
        select(Meter)
        .where(Meter.id == meter_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meter is None:
        db.rollback()
        raise ResourceNotFoundError(f"Meter '{meter_id}' not found.")

    has_telemetry = db.scalar(
        select(TelemetryReading.id).where(TelemetryReading.meter_id == meter_id).limit(1)
    )
    has_anomalies = db.scalar(
        select(Anomaly.id).where(Anomaly.meter_id == meter_id).limit(1)
    )
    has_audits = db.scalar(
        select(MeterCalibrationAudit.id)
        .where(MeterCalibrationAudit.meter_id == meter_id)
        .limit(1)
    )
    if any(dep is not None for dep in (has_telemetry, has_anomalies, has_audits)):
        db.rollback()
        raise ConflictError(
            "Cannot delete meter with existing telemetry, anomaly, or calibration audit history. "
            "Use soft deactivation instead."
        )

    db.delete(meter)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "Cannot delete meter because dependent historical records exist."
        ) from exc
