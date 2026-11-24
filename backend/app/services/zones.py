from datetime import UTC, datetime
import math
import uuid

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.anomaly import Anomaly
from app.models.facility import Facility, Meter, Zone
from app.models.insight import EnergyInsight
from app.models.telemetry import TelemetryReading
from app.models.user import User
from app.schemas.common import DEFAULT_PAGE, DEFAULT_PAGE_SIZE, PaginatedResponse
from app.schemas.facility import ZoneCreate, ZoneResponse, ZoneUpdate
from app.services.exceptions import ConflictError, ResourceNotFoundError
from app.services.permissions import (
    ADMIN_ONLY_ROLES,
    ALL_AUTHENTICATED_ROLES,
    assert_actor_authorized,
)


def _fetch_zone_meter_counts(
    db: Session, zone_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    if not zone_ids:
        return {}

    rows = db.execute(
        select(
            Meter.zone_id,
            func.count(Meter.id),
            func.coalesce(func.sum(case((Meter.is_active.is_(True), 1), else_=0)), 0),
        )
        .where(Meter.zone_id.in_(zone_ids))
        .group_by(Meter.zone_id)
    ).all()
    return {row[0]: (int(row[1]), int(row[2])) for row in rows}


def _to_zone_response(
    zone: Zone, meter_counts: dict[uuid.UUID, tuple[int, int]]
) -> ZoneResponse:
    m_total, m_active = meter_counts.get(zone.id, (0, 0))
    return ZoneResponse(
        id=zone.id,
        facility_id=zone.facility_id,
        slug=zone.slug,
        name=zone.name,
        primary_meter_code=zone.primary_meter_code,
        share_pct=zone.share_pct,
        status=zone.status,
        is_active=zone.is_active,
        deactivated_at=zone.deactivated_at,
        meter_count=m_total,
        active_meter_count=m_active,
    )


def list_zones(
    db: Session,
    *,
    actor: User,
    page: int = DEFAULT_PAGE,
    page_size: int = DEFAULT_PAGE_SIZE,
    facility_id: str | None = None,
    status: str | None = None,
    is_active: bool | None = None,
    search: str | None = None,
) -> PaginatedResponse[ZoneResponse]:
    assert_actor_authorized(actor, ALL_AUTHENTICATED_ROLES)

    filters = []
    if facility_id is not None:
        filters.append(Zone.facility_id == facility_id)
    if status is not None:
        filters.append(Zone.status == status)
    if is_active is not None:
        filters.append(Zone.is_active.is_(is_active))
    if search is not None:
        term = search.strip()
        if term:
            pattern = f"%{term}%"
            filters.append(
                Zone.name.ilike(pattern)
                | Zone.slug.ilike(pattern)
                | Zone.primary_meter_code.ilike(pattern)
            )

    total = int(db.scalar(select(func.count(Zone.id)).where(*filters)) or 0)
    offset = (page - 1) * page_size
    zones = list(
        db.scalars(
            select(Zone)
            .where(*filters)
            .order_by(Zone.facility_id.asc(), Zone.slug.asc(), Zone.id.asc())
            .offset(offset)
            .limit(page_size)
        ).all()
    )

    meter_counts = _fetch_zone_meter_counts(db, [zone.id for zone in zones])
    items = [_to_zone_response(zone, meter_counts) for zone in zones]
    pages = math.ceil(total / page_size) if total > 0 else 0
    return PaginatedResponse[ZoneResponse](
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


def get_zone(
    db: Session,
    *,
    actor: User,
    zone_id: uuid.UUID,
) -> ZoneResponse:
    assert_actor_authorized(actor, ALL_AUTHENTICATED_ROLES)

    zone = db.get(Zone, zone_id)
    if zone is None:
        raise ResourceNotFoundError(f"Zone '{zone_id}' not found.")

    meter_counts = _fetch_zone_meter_counts(db, [zone.id])
    return _to_zone_response(zone, meter_counts)


def create_zone(
    db: Session,
    *,
    actor: User,
    payload: ZoneCreate,
) -> ZoneResponse:
    assert_actor_authorized(actor, ADMIN_ONLY_ROLES)

    # Lock parent facility row first so concurrent facility deactivation serializes cleanly
    facility = db.scalar(
        select(Facility)
        .where(Facility.id == payload.facility_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if facility is None:
        db.rollback()
        raise ResourceNotFoundError(f"Facility '{payload.facility_id}' not found.")

    if not facility.is_active:
        db.rollback()
        raise ConflictError(
            f"Cannot create zone under deactivated facility '{payload.facility_id}'."
        )

    duplicate_slug = db.scalar(
        select(Zone.id).where(
            Zone.facility_id == payload.facility_id,
            Zone.slug == payload.slug,
        )
    )
    if duplicate_slug is not None:
        db.rollback()
        raise ConflictError(
            f"A zone with slug '{payload.slug}' already exists in facility '{payload.facility_id}'."
        )

    zone = Zone(
        facility_id=payload.facility_id,
        slug=payload.slug,
        name=payload.name,
        primary_meter_code=payload.primary_meter_code,
        share_pct=payload.share_pct,
        status=payload.status.value,
        is_active=True,
        deactivated_at=None,
    )
    db.add(zone)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Zone slug already exists in this facility.") from exc

    db.refresh(zone)
    return _to_zone_response(zone, {})


def update_zone(
    db: Session,
    *,
    actor: User,
    zone_id: uuid.UUID,
    payload: ZoneUpdate,
) -> ZoneResponse:
    assert_actor_authorized(actor, ADMIN_ONLY_ROLES)

    zone = db.scalar(
        select(Zone)
        .where(Zone.id == zone_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if zone is None:
        db.rollback()
        raise ResourceNotFoundError(f"Zone '{zone_id}' not found.")

    if payload.slug is not None and payload.slug != zone.slug:
        conflict_id = db.scalar(
            select(Zone.id).where(
                Zone.facility_id == zone.facility_id,
                Zone.slug == payload.slug,
                Zone.id != zone_id,
            )
        )
        if conflict_id is not None:
            db.rollback()
            raise ConflictError(
                f"A zone with slug '{payload.slug}' already exists in facility '{zone.facility_id}'."
            )

    for field_name in payload.model_fields_set:
        value = getattr(payload, field_name)
        if field_name == "status" and value is not None:
            value = value.value
        setattr(zone, field_name, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Zone update conflicts with existing zone data.") from exc

    db.refresh(zone)
    meter_counts = _fetch_zone_meter_counts(db, [zone.id])
    return _to_zone_response(zone, meter_counts)


def deactivate_zone(
    db: Session,
    *,
    actor: User,
    zone_id: uuid.UUID,
) -> ZoneResponse:
    assert_actor_authorized(actor, ADMIN_ONLY_ROLES)

    # Lock zone row so concurrent meter registration against this zone serializes cleanly
    zone = db.scalar(
        select(Zone)
        .where(Zone.id == zone_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if zone is None:
        db.rollback()
        raise ResourceNotFoundError(f"Zone '{zone_id}' not found.")

    if not zone.is_active:
        db.rollback()
        raise ConflictError(f"Zone '{zone_id}' is already deactivated.")

    active_meters = int(
        db.scalar(
            select(func.count(Meter.id)).where(
                Meter.zone_id == zone_id,
                Meter.is_active.is_(True),
            )
        )
        or 0
    )
    if active_meters > 0:
        db.rollback()
        raise ConflictError(
            "Cannot deactivate zone while active meters still exist."
        )

    zone.is_active = False
    zone.deactivated_at = datetime.now(UTC)
    db.commit()
    db.refresh(zone)

    meter_counts = _fetch_zone_meter_counts(db, [zone.id])
    return _to_zone_response(zone, meter_counts)


def delete_zone(
    db: Session,
    *,
    actor: User,
    zone_id: uuid.UUID,
) -> None:
    assert_actor_authorized(actor, ADMIN_ONLY_ROLES)

    zone = db.scalar(
        select(Zone)
        .where(Zone.id == zone_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if zone is None:
        db.rollback()
        raise ResourceNotFoundError(f"Zone '{zone_id}' not found.")

    has_meters = db.scalar(select(Meter.id).where(Meter.zone_id == zone_id).limit(1))
    has_insights = db.scalar(
        select(EnergyInsight.id).where(EnergyInsight.zone_id == zone_id).limit(1)
    )
    has_telemetry = db.scalar(
        select(TelemetryReading.id).where(TelemetryReading.zone_id == zone_id).limit(1)
    )
    has_anomalies = db.scalar(
        select(Anomaly.id).where(Anomaly.zone_id == zone_id).limit(1)
    )

    if any(
        dep is not None
        for dep in (has_meters, has_insights, has_telemetry, has_anomalies)
    ):
        db.rollback()
        raise ConflictError(
            "Cannot delete zone with existing meters, insights, or historical records. "
            "Use soft deactivation instead."
        )

    db.delete(zone)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "Cannot delete zone because dependent records exist."
        ) from exc
