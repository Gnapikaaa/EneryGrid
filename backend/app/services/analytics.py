from datetime import UTC, datetime
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.facility import Facility, Meter, Zone
from app.models.telemetry import TelemetryReading
from app.models.user import User
from app.schemas.analytics import AnalyticsCursor, AnalyticsProcessRequest, AnalyticsProcessSummary
from app.services.anomalies import reconcile_anomalies_for_chunk
from app.services.baselines import (
    acquire_meter_advisory_lock,
    count_exhausted_pending_readings,
    count_remaining_mode_eligible_readings,
    process_meter_baseline_chunk,
)
from app.services.exceptions import ResourceNotFoundError, ValidationFailureError
from app.services.insights import evaluate_meter_insights
from app.services.permissions import ANALYTICS_OPERATIONS_ROLES, assert_actor_authorized


def _validate_scope_and_cursor(
    db: Session,
    *,
    payload: AnalyticsProcessRequest,
    settings: Settings,
) -> int:
    if payload.max_readings is None:
        effective_max = settings.analytics_default_max_readings
    elif payload.max_readings > settings.analytics_hard_max_readings:
        raise ValidationFailureError(
            f"max_readings cannot exceed ANALYTICS_HARD_MAX_READINGS ({settings.analytics_hard_max_readings})."
        )
    else:
        effective_max = payload.max_readings

    if payload.facility_id is not None:
        if db.get(Facility, payload.facility_id) is None:
            raise ResourceNotFoundError(f"Facility '{payload.facility_id}' was not found.")

    if payload.zone_id is not None:
        zone = db.get(Zone, payload.zone_id)
        if zone is None:
            raise ResourceNotFoundError(f"Zone '{payload.zone_id}' was not found.")
        if payload.facility_id is not None and zone.facility_id != payload.facility_id:
            raise ValidationFailureError(
                "Requested zone_id does not belong to the requested facility_id."
            )

    if payload.meter_id is not None:
        meter = db.get(Meter, payload.meter_id)
        if meter is None:
            raise ResourceNotFoundError(f"Meter '{payload.meter_id}' was not found.")
        if payload.facility_id is not None and meter.facility_id != payload.facility_id:
            raise ValidationFailureError(
                "Requested meter_id does not belong to the requested facility_id."
            )
        if payload.zone_id is not None and meter.zone_id != payload.zone_id:
            raise ValidationFailureError(
                "Requested meter_id does not belong to the requested zone_id."
            )

    if payload.cursor is not None:
        cursor_reading = db.get(TelemetryReading, payload.cursor.last_reading_id)
        if cursor_reading is None:
            raise ValidationFailureError("Invalid cursor: referenced reading_id does not exist.")
        if cursor_reading.meter_id != payload.cursor.last_meter_id:
            raise ValidationFailureError(
                "Invalid cursor: last_meter_id does not match referenced reading_id."
            )
        if cursor_reading.recorded_at.astimezone(UTC) != payload.cursor.last_recorded_at.astimezone(UTC):
            raise ValidationFailureError(
                "Invalid cursor: last_recorded_at does not match referenced reading_id."
            )
        if payload.facility_id is not None and cursor_reading.facility_id != payload.facility_id:
            raise ValidationFailureError(
                "Invalid cursor: cursor reading falls outside requested facility_id scope."
            )
        if payload.zone_id is not None and cursor_reading.zone_id != payload.zone_id:
            raise ValidationFailureError(
                "Invalid cursor: cursor reading falls outside requested zone_id scope."
            )
        if payload.meter_id is not None and cursor_reading.meter_id != payload.meter_id:
            raise ValidationFailureError(
                "Invalid cursor: cursor reading falls outside requested meter_id scope."
            )
        if payload.start_at is not None and cursor_reading.recorded_at.astimezone(UTC) < payload.start_at:
            raise ValidationFailureError(
                "Invalid cursor: cursor timestamp precedes requested start_at."
            )
        if payload.end_at is not None and cursor_reading.recorded_at.astimezone(UTC) > payload.end_at:
            raise ValidationFailureError(
                "Invalid cursor: cursor timestamp exceeds requested end_at."
            )

    return effective_max


def process_analytics_batch(
    db: Session,
    *,
    actor: User,
    payload: AnalyticsProcessRequest,
    settings: Settings,
) -> AnalyticsProcessSummary:
    """Bounded synchronous coordinator executing baselines, anomalies, and insights per meter chunk."""
    assert_actor_authorized(actor, ANALYTICS_OPERATIONS_ROLES)
    effective_max = _validate_scope_and_cursor(db, payload=payload, settings=settings)

    now_utc = datetime.now(UTC)

    meter_stmt = select(Meter.id, Meter.facility_id).join(
        Facility, Meter.facility_id == Facility.id
    ).where(
        Meter.is_active.is_(True),
        Facility.is_active.is_(True),
    )
    if payload.facility_id is not None:
        meter_stmt = meter_stmt.where(Meter.facility_id == payload.facility_id)
    if payload.zone_id is not None:
        meter_stmt = meter_stmt.where(Meter.zone_id == payload.zone_id)
    if payload.meter_id is not None:
        meter_stmt = meter_stmt.where(Meter.id == payload.meter_id)
    if payload.cursor is not None:
        meter_stmt = meter_stmt.where(Meter.id >= payload.cursor.last_meter_id)
    meter_stmt = meter_stmt.order_by(Meter.id.asc())

    scoped_meter_ids: list[uuid.UUID] = [row[0] for row in db.execute(meter_stmt).all()]

    # End read-only validation/snapshot transaction before per-chunk lock transactions
    db.commit()

    processed_readings = 0
    baselines_ready = 0
    baselines_insufficient = 0
    anomalies_created = 0
    anomalies_reconciled = 0
    anomalies_unchanged = 0
    insights_created = 0
    insights_updated = 0

    remaining_budget = effective_max
    last_cursor: AnalyticsCursor | None = payload.cursor
    explicit_narrow_scope = (
        payload.meter_id is not None
        or payload.zone_id is not None
        or payload.facility_id is not None
    )

    for meter_id in scoped_meter_ids:
        if remaining_budget <= 0:
            break

        meter_had_updates = False
        after_recorded_at: datetime | None = (
            payload.cursor.last_recorded_at
            if payload.cursor is not None and meter_id == payload.cursor.last_meter_id
            else None
        )
        after_reading_id: int | None = (
            payload.cursor.last_reading_id
            if payload.cursor is not None and meter_id == payload.cursor.last_meter_id
            else None
        )

        while remaining_budget > 0:
            chunk_limit = min(settings.analytics_chunk_size, remaining_budget)
            meter = db.get(Meter, meter_id)
            if meter is None:
                db.rollback()
                break
            facility = db.get(Facility, meter.facility_id)
            if facility is None:
                db.rollback()
                break

            acquire_meter_advisory_lock(db, meter.id)
            chunk_outcome = process_meter_baseline_chunk(
                db,
                meter=meter,
                facility=facility,
                settings=settings,
                now_utc=now_utc,
                chunk_limit=chunk_limit,
                reprocess=payload.reprocess,
                retry_insufficient=payload.retry_insufficient,
                retry_exhausted=payload.retry_exhausted,
                start_at=payload.start_at,
                end_at=payload.end_at,
                after_recorded_at=after_recorded_at,
                after_reading_id=after_reading_id,
            )
            if not chunk_outcome.evaluated_items:
                db.commit()
                break

            created, reconciled, unchanged = reconcile_anomalies_for_chunk(
                db,
                meter=meter,
                facility=facility,
                actor=actor,
                evaluated_items=chunk_outcome.evaluated_items,
                settings=settings,
            )
            db.commit()

            count_in_chunk = len(chunk_outcome.evaluated_items)
            processed_readings += count_in_chunk
            baselines_ready += chunk_outcome.baselines_ready
            baselines_insufficient += chunk_outcome.baselines_insufficient
            anomalies_created += created
            anomalies_reconciled += reconciled
            anomalies_unchanged += unchanged
            remaining_budget -= count_in_chunk
            meter_had_updates = True

            assert chunk_outcome.last_recorded_at is not None
            assert chunk_outcome.last_reading_id is not None
            after_recorded_at = chunk_outcome.last_recorded_at
            after_reading_id = chunk_outcome.last_reading_id
            last_cursor = AnalyticsCursor(
                last_meter_id=meter.id,
                last_recorded_at=after_recorded_at,
                last_reading_id=after_reading_id,
            )

            if count_in_chunk < chunk_limit:
                break

        should_evaluate_insights = payload.include_insights and (
            meter_had_updates
            or payload.force_insights
            or (explicit_narrow_scope and payload.cursor is None)
            or (not meter_had_updates and payload.cursor is None)
        )
        if should_evaluate_insights:
            meter = db.get(Meter, meter_id)
            facility = db.get(Facility, meter.facility_id) if meter is not None else None
            if meter is not None and facility is not None:
                acquire_meter_advisory_lock(db, meter.id)
                ins_created, ins_updated = evaluate_meter_insights(
                    db,
                    meter=meter,
                    facility=facility,
                    actor=actor,
                    now_utc=now_utc,
                    settings=settings,
                )
                db.commit()
                insights_created += ins_created
                insights_updated += ins_updated
            else:
                db.rollback()

    after_m = last_cursor.last_meter_id if last_cursor is not None else None
    after_t = last_cursor.last_recorded_at if last_cursor is not None else None
    after_id = last_cursor.last_reading_id if last_cursor is not None else None

    remaining_eligible = count_remaining_mode_eligible_readings(
        db,
        settings=settings,
        now_utc=now_utc,
        reprocess=payload.reprocess,
        retry_insufficient=payload.retry_insufficient,
        retry_exhausted=payload.retry_exhausted,
        facility_id=payload.facility_id,
        zone_id=payload.zone_id,
        meter_id=payload.meter_id,
        start_at=payload.start_at,
        end_at=payload.end_at,
        after_meter_id=after_m,
        after_recorded_at=after_t,
        after_reading_id=after_id,
    )
    exhausted_skipped = (
        0
        if (payload.reprocess or payload.retry_exhausted)
        else count_exhausted_pending_readings(
            db,
            settings=settings,
            facility_id=payload.facility_id,
            zone_id=payload.zone_id,
            meter_id=payload.meter_id,
            start_at=payload.start_at,
            end_at=payload.end_at,
        )
    )
    db.commit()

    has_more = remaining_eligible > 0
    return AnalyticsProcessSummary(
        processed_readings=processed_readings,
        baselines_ready=baselines_ready,
        baselines_insufficient=baselines_insufficient,
        anomalies_created=anomalies_created,
        anomalies_reconciled=anomalies_reconciled,
        anomalies_unchanged=anomalies_unchanged,
        insights_created=insights_created,
        insights_updated=insights_updated,
        exhausted_skipped_count=exhausted_skipped,
        remaining_eligible_readings=remaining_eligible,
        has_more=has_more,
        next_cursor=last_cursor if has_more else None,
    )
