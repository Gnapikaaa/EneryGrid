from datetime import UTC, datetime
import math

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.anomaly import Anomaly
from app.models.facility import Facility, Meter, Zone
from app.models.insight import EnergyInsight
from app.models.telemetry import TelemetryReading
from app.models.user import User
from app.schemas.common import DEFAULT_PAGE, DEFAULT_PAGE_SIZE, PaginatedResponse
from app.schemas.facility import FacilityCreate, FacilityResponse, FacilityUpdate
from app.services.exceptions import ConflictError, ResourceNotFoundError
from app.services.permissions import (
    ADMIN_ONLY_ROLES,
    ALL_AUTHENTICATED_ROLES,
    assert_actor_authorized,
)


def _fetch_facility_counts(
    db: Session, facility_ids: list[str]
) -> tuple[dict[str, tuple[int, int]], dict[str, tuple[int, int]]]:
    if not facility_ids:
        return {}, {}

    zone_rows = db.execute(
        select(
            Zone.facility_id,
            func.count(Zone.id),
            func.coalesce(func.sum(case((Zone.is_active.is_(True), 1), else_=0)), 0),
        )
        .where(Zone.facility_id.in_(facility_ids))
        .group_by(Zone.facility_id)
    ).all()
    zone_counts = {
        row[0]: (int(row[1]), int(row[2]))
        for row in zone_rows
    }

    meter_rows = db.execute(
        select(
            Meter.facility_id,
            func.count(Meter.id),
            func.coalesce(func.sum(case((Meter.is_active.is_(True), 1), else_=0)), 0),
        )
        .where(Meter.facility_id.in_(facility_ids))
        .group_by(Meter.facility_id)
    ).all()
    meter_counts = {
        row[0]: (int(row[1]), int(row[2]))
        for row in meter_rows
    }
    return zone_counts, meter_counts


def _to_facility_response(
    facility: Facility,
    zone_counts: dict[str, tuple[int, int]],
    meter_counts: dict[str, tuple[int, int]],
) -> FacilityResponse:
    z_total, z_active = zone_counts.get(facility.id, (0, 0))
    m_total, m_active = meter_counts.get(facility.id, (0, 0))
    return FacilityResponse(
        id=facility.id,
        code=facility.code,
        name=facility.name,
        location=facility.location,
        timezone=facility.timezone,
        currency_code=facility.currency_code,
        contracted_demand_kw=facility.contracted_demand_kw,
        off_peak_tariff_rate=facility.off_peak_tariff_rate,
        mid_peak_tariff_rate=facility.mid_peak_tariff_rate,
        peak_tariff_rate=facility.peak_tariff_rate,
        is_active=facility.is_active,
        deactivated_at=facility.deactivated_at,
        created_at=facility.created_at,
        zone_count=z_total,
        active_zone_count=z_active,
        meter_count=m_total,
        active_meter_count=m_active,
    )


def list_facilities(
    db: Session,
    *,
    actor: User,
    page: int = DEFAULT_PAGE,
    page_size: int = DEFAULT_PAGE_SIZE,
    is_active: bool | None = None,
    search: str | None = None,
) -> PaginatedResponse[FacilityResponse]:
    assert_actor_authorized(actor, ALL_AUTHENTICATED_ROLES)

    filters = []
    if is_active is not None:
        filters.append(Facility.is_active.is_(is_active))
    if search is not None:
        term = search.strip()
        if term:
            pattern = f"%{term}%"
            filters.append(
                Facility.name.ilike(pattern)
                | Facility.code.ilike(pattern)
                | Facility.location.ilike(pattern)
                | Facility.id.ilike(pattern)
            )

    total = int(
        db.scalar(select(func.count(Facility.id)).where(*filters)) or 0
    )
    offset = (page - 1) * page_size
    facilities = list(
        db.scalars(
            select(Facility)
            .where(*filters)
            .order_by(Facility.created_at.asc(), Facility.id.asc())
            .offset(offset)
            .limit(page_size)
        ).all()
    )

    zone_counts, meter_counts = _fetch_facility_counts(
        db, [facility.id for facility in facilities]
    )
    items = [
        _to_facility_response(facility, zone_counts, meter_counts)
        for facility in facilities
    ]
    pages = math.ceil(total / page_size) if total > 0 else 0
    return PaginatedResponse[FacilityResponse](
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


def get_facility(
    db: Session,
    *,
    actor: User,
    facility_id: str,
) -> FacilityResponse:
    assert_actor_authorized(actor, ALL_AUTHENTICATED_ROLES)

    facility = db.get(Facility, facility_id)
    if facility is None:
        raise ResourceNotFoundError(f"Facility '{facility_id}' not found.")

    zone_counts, meter_counts = _fetch_facility_counts(db, [facility.id])
    return _to_facility_response(facility, zone_counts, meter_counts)


def create_facility(
    db: Session,
    *,
    actor: User,
    payload: FacilityCreate,
) -> FacilityResponse:
    assert_actor_authorized(actor, ADMIN_ONLY_ROLES)

    if db.get(Facility, payload.id) is not None:
        raise ConflictError(f"A facility with id '{payload.id}' already exists.")

    existing_code = db.scalar(
        select(Facility.id).where(func.lower(Facility.code) == payload.code.lower())
    )
    if existing_code is not None:
        raise ConflictError(f"A facility with code '{payload.code}' already exists.")

    facility = Facility(
        id=payload.id,
        code=payload.code,
        name=payload.name,
        location=payload.location,
        timezone=payload.timezone,
        currency_code=payload.currency_code,
        contracted_demand_kw=payload.contracted_demand_kw,
        off_peak_tariff_rate=payload.off_peak_tariff_rate,
        mid_peak_tariff_rate=payload.mid_peak_tariff_rate,
        peak_tariff_rate=payload.peak_tariff_rate,
        is_active=True,
        deactivated_at=None,
    )
    db.add(facility)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Facility ID or code already exists.") from exc

    db.refresh(facility)
    return _to_facility_response(facility, {}, {})


def update_facility(
    db: Session,
    *,
    actor: User,
    facility_id: str,
    payload: FacilityUpdate,
) -> FacilityResponse:
    assert_actor_authorized(actor, ADMIN_ONLY_ROLES)

    facility = db.scalar(
        select(Facility)
        .where(Facility.id == facility_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if facility is None:
        db.rollback()
        raise ResourceNotFoundError(f"Facility '{facility_id}' not found.")

    if payload.code is not None and payload.code.lower() != facility.code.lower():
        conflict_id = db.scalar(
            select(Facility.id).where(
                func.lower(Facility.code) == payload.code.lower(),
                Facility.id != facility_id,
            )
        )
        if conflict_id is not None:
            db.rollback()
            raise ConflictError(f"A facility with code '{payload.code}' already exists.")

    for field_name in payload.model_fields_set:
        setattr(facility, field_name, getattr(payload, field_name))

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Facility update conflicts with existing facility data.") from exc

    db.refresh(facility)
    zone_counts, meter_counts = _fetch_facility_counts(db, [facility.id])
    return _to_facility_response(facility, zone_counts, meter_counts)


def deactivate_facility(
    db: Session,
    *,
    actor: User,
    facility_id: str,
) -> FacilityResponse:
    assert_actor_authorized(actor, ADMIN_ONLY_ROLES)

    # Lock parent facility row first so concurrent zone/meter creation serializes cleanly
    facility = db.scalar(
        select(Facility)
        .where(Facility.id == facility_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if facility is None:
        db.rollback()
        raise ResourceNotFoundError(f"Facility '{facility_id}' not found.")

    if not facility.is_active:
        db.rollback()
        raise ConflictError(f"Facility '{facility_id}' is already deactivated.")

    active_zones = int(
        db.scalar(
            select(func.count(Zone.id)).where(
                Zone.facility_id == facility_id,
                Zone.is_active.is_(True),
            )
        )
        or 0
    )
    active_meters = int(
        db.scalar(
            select(func.count(Meter.id)).where(
                Meter.facility_id == facility_id,
                Meter.is_active.is_(True),
            )
        )
        or 0
    )
    if active_zones > 0 or active_meters > 0:
        db.rollback()
        raise ConflictError(
            "Cannot deactivate facility while active zones or meters still exist."
        )

    facility.is_active = False
    facility.deactivated_at = datetime.now(UTC)
    db.commit()
    db.refresh(facility)

    zone_counts, meter_counts = _fetch_facility_counts(db, [facility.id])
    return _to_facility_response(facility, zone_counts, meter_counts)


def delete_facility(
    db: Session,
    *,
    actor: User,
    facility_id: str,
) -> None:
    assert_actor_authorized(actor, ADMIN_ONLY_ROLES)

    facility = db.scalar(
        select(Facility)
        .where(Facility.id == facility_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if facility is None:
        db.rollback()
        raise ResourceNotFoundError(f"Facility '{facility_id}' not found.")

    # Guard explicitly against zones.facility_id ON DELETE CASCADE and dependent history
    has_zones = db.scalar(select(Zone.id).where(Zone.facility_id == facility_id).limit(1))
    has_meters = db.scalar(select(Meter.id).where(Meter.facility_id == facility_id).limit(1))
    has_telemetry = db.scalar(
        select(TelemetryReading.id).where(TelemetryReading.facility_id == facility_id).limit(1)
    )
    has_anomalies = db.scalar(
        select(Anomaly.id).where(Anomaly.facility_id == facility_id).limit(1)
    )
    has_insights = db.scalar(
        select(EnergyInsight.id).where(EnergyInsight.facility_id == facility_id).limit(1)
    )

    if any(
        dep is not None
        for dep in (has_zones, has_meters, has_telemetry, has_anomalies, has_insights)
    ):
        db.rollback()
        raise ConflictError(
            "Cannot delete facility with existing zones, meters, or historical records. "
            "Use soft deactivation instead."
        )

    db.delete(facility)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "Cannot delete facility because dependent records exist."
        ) from exc
