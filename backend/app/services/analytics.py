from datetime import UTC, datetime
from decimal import Decimal
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.constants import AnomalySeverity, AnomalyStatus, QualityFlag, TelemetrySource
from app.models.anomaly import Anomaly
from app.models.facility import Facility, Meter, Zone
from app.models.insight import EnergyInsight
from app.models.telemetry import TelemetryReading
from app.models.user import User
from app.schemas.analytics import (
    AnalyticsCursor,
    AnalyticsProcessRequest,
    AnalyticsProcessSummary,
    AnalyticsSeriesBucketItem,
    AnalyticsSummaryResponse,
    MeterLiveSnapshotItem,
    ZoneAnalyticsSummaryItem,
)
from app.services.analytics_summary_math import (
    SummarySampleRow,
    SummaryWindow,
    build_series_and_heatmap,
    compute_interval_demand_stats,
    compute_trend_pct,
    derive_health_status,
    resolve_window_bounds,
)
from app.services.anomalies import reconcile_anomalies_for_chunk
from app.services.baselines import (
    acquire_meter_advisory_lock,
    count_exhausted_pending_readings,
    count_remaining_mode_eligible_readings,
    process_meter_baseline_chunk,
)
from app.services.exceptions import ResourceNotFoundError, ValidationFailureError
from app.services.insights import evaluate_meter_insights
from app.services.permissions import (
    ALL_AUTHENTICATED_ROLES,
    ANALYTICS_OPERATIONS_ROLES,
    assert_actor_authorized,
)


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
            meter_had_updates or (explicit_narrow_scope and payload.cursor is None)
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


def get_analytics_summary(
    db: Session,
    *,
    actor: User,
    facility_id: str,
    zone_id: uuid.UUID | None = None,
    time_window: SummaryWindow = "24h",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    include_simulated: bool = False,
) -> AnalyticsSummaryResponse:
    """Compute untruncated server-side facility analytics summary directly from PostgreSQL."""
    assert_actor_authorized(actor, ALL_AUTHENTICATED_ROLES)

    facility = db.get(Facility, facility_id)
    if facility is None:
        raise ResourceNotFoundError(f"Facility '{facility_id}' not found.")

    if zone_id is not None:
        zone = db.get(Zone, zone_id)
        if zone is None or zone.facility_id != facility_id:
            raise ResourceNotFoundError(f"Zone '{zone_id}' not found in facility '{facility_id}'.")

    if start_at is not None and (start_at.tzinfo is None or start_at.utcoffset() is None):
        raise ValidationFailureError("start_at must include an explicit timezone offset or 'Z'.")
    if end_at is not None and (end_at.tzinfo is None or end_at.utcoffset() is None):
        raise ValidationFailureError("end_at must include an explicit timezone offset or 'Z'.")
    if start_at is not None and end_at is not None and start_at.astimezone(UTC) > end_at.astimezone(UTC):
        raise ValidationFailureError("start_at cannot be later than end_at.")

    base_filters = [TelemetryReading.facility_id == facility_id]
    if not include_simulated:
        base_filters.append(TelemetryReading.quality_flag != QualityFlag.SIMULATED.value)
        base_filters.append(TelemetryReading.source != TelemetrySource.SIMULATION.value)

    latest_stmt = select(func.max(TelemetryReading.recorded_at)).where(*base_filters)
    if zone_id is not None:
        latest_stmt = latest_stmt.where(TelemetryReading.zone_id == zone_id)
    latest_recorded_at: datetime | None = db.scalar(latest_stmt)

    anchor_utc = latest_recorded_at or datetime.now(UTC)
    window_start, window_end, prev_start, prev_end = resolve_window_bounds(
        time_window=time_window,
        anchor_utc=anchor_utc,
        start_at=start_at,
        end_at=end_at,
    )

    zones = list(
        db.scalars(
            select(Zone)
            .where(Zone.facility_id == facility_id)
            .order_by(Zone.slug.asc(), Zone.id.asc())
        ).all()
    )
    meters = list(
        db.scalars(
            select(Meter)
            .where(Meter.facility_id == facility_id)
            .order_by(Meter.meter_code.asc(), Meter.id.asc())
        ).all()
    )

    # Query full facility window (needed so zone breakdown stays consistent even when zone_id filter is active)
    window_rows = db.execute(
        select(
            TelemetryReading.meter_id,
            TelemetryReading.zone_id,
            TelemetryReading.recorded_at,
            TelemetryReading.interval_seconds,
            TelemetryReading.actual_kw,
            TelemetryReading.energy_kwh,
            TelemetryReading.baseline_kw,
            TelemetryReading.std_dev_kw,
            TelemetryReading.z_score,
            TelemetryReading.power_factor,
            TelemetryReading.tariff_period,
            TelemetryReading.ambient_temp_c,
        )
        .where(
            *base_filters,
            TelemetryReading.recorded_at >= window_start,
            TelemetryReading.recorded_at <= window_end,
        )
        .order_by(TelemetryReading.recorded_at.asc(), TelemetryReading.id.asc())
    ).all()

    prev_filters = [*base_filters, TelemetryReading.recorded_at >= prev_start, TelemetryReading.recorded_at < prev_end]
    if zone_id is not None:
        prev_filters.append(TelemetryReading.zone_id == zone_id)
    prev_kwh_raw, prev_count_raw = db.execute(
        select(
            func.coalesce(func.sum(TelemetryReading.energy_kwh), Decimal("0")),
            func.count(TelemetryReading.id),
        ).where(*prev_filters)
    ).one()
    previous_total_kwh = round(float(prev_kwh_raw), 2)
    previous_count = int(prev_count_raw or 0)

    all_samples = [
        SummarySampleRow(
            meter_id=str(r[0]),
            zone_id=str(r[1]),
            recorded_at=r[2],
            interval_seconds=int(r[3]),
            actual_kw=r[4],
            energy_kwh=r[5],
            baseline_kw=r[6],
            std_dev_kw=r[7],
            z_score=r[8],
            power_factor=r[9],
            tariff_period=str(r[10]),
            ambient_temp_c=r[11],
        )
        for r in window_rows
    ]

    scoped_samples = (
        [s for s in all_samples if s.zone_id == str(zone_id)]
        if zone_id is not None
        else all_samples
    )

    series_dicts, heatmap = build_series_and_heatmap(
        scoped_samples,
        time_window=time_window,
        window_start=window_start,
        window_end=window_end,
        timezone_name=facility.timezone,
    )
    series = [
        AnalyticsSeriesBucketItem(
            timestamp=str(item["timestamp"]),
            label=str(item["label"]),
            actual_kw=float(item["actual_kw"]),
            baseline_kw=float(item["baseline_kw"]),
            std_dev_kw=float(item["std_dev_kw"]),
            has_baseline=bool(item["has_baseline"]),
            power_factor=float(item["power_factor"]),
            tariff_period=str(item["tariff_period"]),
            ambient_temp_c=float(item["ambient_temp_c"]),
            z_score=float(item["z_score"]),
            zone_id=uuid.UUID(str(item["zone_id"])),
        )
        for item in series_dicts
    ]

    total_kwh = round(sum(float(s.energy_kwh) for s in scoped_samples), 2)
    total_mwh = round(total_kwh / 1000.0, 4)
    reading_count = len(scoped_samples)
    baselined_count = sum(1 for s in scoped_samples if s.baseline_kw is not None)
    avg_demand_kw, peak_demand_kw = compute_interval_demand_stats(scoped_samples)
    avg_power_factor = (
        round(sum(float(s.power_factor) for s in scoped_samples) / reading_count, 3)
        if reading_count > 0
        else 0.0
    )

    if zone_id is not None:
        zone_meters = [m for m in meters if m.zone_id == zone_id and m.is_active] or [
            m for m in meters if m.zone_id == zone_id
        ]
        contracted_demand_kw = (
            round(sum(float(m.rated_kw) for m in zone_meters), 2)
            if zone_meters
            else float(facility.contracted_demand_kw)
        )
    else:
        contracted_demand_kw = float(facility.contracted_demand_kw)

    demand_headroom_pct = (
        round((peak_demand_kw / contracted_demand_kw) * 100.0, 1)
        if contracted_demand_kw > 0
        else 0.0
    )

    # Open anomalies & active insights inside facility (filtered by zone if selected)
    open_statuses = [
        AnomalyStatus.OPEN.value,
        AnomalyStatus.ACKNOWLEDGED.value,
        AnomalyStatus.ASSIGNED.value,
    ]
    open_anomalies = list(
        db.scalars(
            select(Anomaly).where(
                Anomaly.facility_id == facility_id,
                Anomaly.status.in_(open_statuses),
                Anomaly.detected_at >= window_start,
                Anomaly.detected_at <= window_end,
            )
        ).all()
    )
    scoped_anomalies = (
        [a for a in open_anomalies if a.zone_id == zone_id]
        if zone_id is not None
        else open_anomalies
    )
    open_anomalies_count = len(scoped_anomalies)
    critical_anomalies_count = sum(
        1 for a in scoped_anomalies if a.severity == AnomalySeverity.CRITICAL.value
    )

    insights_filters = [EnergyInsight.facility_id == facility_id]
    if zone_id is not None:
        insights_filters.append(EnergyInsight.zone_id == zone_id)
    facility_insights = list(db.scalars(select(EnergyInsight).where(*insights_filters)).all())
    potential_annual_savings = 0.0
    has_quantified_savings = False
    unquantified_insights_count = 0
    for ins in facility_insights:
        if ins.annual_cost_savings is not None:
            potential_annual_savings += float(ins.annual_cost_savings)
            has_quantified_savings = True
        else:
            unquantified_insights_count += 1

    # Zone breakdown over all facility samples in window
    samples_by_zone: dict[str, list[SummarySampleRow]] = {}
    samples_by_meter: dict[str, list[SummarySampleRow]] = {}
    for s in all_samples:
        samples_by_zone.setdefault(s.zone_id, []).append(s)
        samples_by_meter.setdefault(s.meter_id, []).append(s)

    total_facility_kwh = sum(float(s.energy_kwh) for s in all_samples)
    zone_breakdown: list[ZoneAnalyticsSummaryItem] = []
    for z in zones:
        z_str = str(z.id)
        z_rows = samples_by_zone.get(z_str, [])
        z_kwh = round(sum(float(r.energy_kwh) for r in z_rows), 1)
        z_by_ts: dict[datetime, float] = {}
        for r in z_rows:
            z_by_ts[r.recorded_at] = z_by_ts.get(r.recorded_at, 0.0) + float(r.actual_kw)
        z_peak = round(max(z_by_ts.values(), default=0.0), 1)
        z_avg = round(sum(z_by_ts.values()) / len(z_by_ts), 1) if z_by_ts else 0.0
        z_pf = (
            round(sum(float(r.power_factor) for r in z_rows) / len(z_rows), 2)
            if z_rows
            else 0.0
        )
        baselined_z = [r for r in z_rows if r.baseline_kw is not None]
        if baselined_z:
            act_sum = sum(float(r.actual_kw) for r in baselined_z)
            base_sum = sum(float(r.baseline_kw) for r in baselined_z if r.baseline_kw is not None)
            delta_pct = round(((act_sum - base_sum) / base_sum) * 100.0, 1) if base_sum > 0 else 0.0
        else:
            delta_pct = 0.0

        z_anoms = [a for a in open_anomalies if a.zone_id == z.id]
        z_crit_high = sum(
            1
            for a in z_anoms
            if a.severity in (AnomalySeverity.CRITICAL.value, AnomalySeverity.HIGH.value)
        )
        z_elev = sum(1 for a in z_anoms if a.severity == AnomalySeverity.ELEVATED.value)
        z_status = derive_health_status(
            latest_pf=z_pf if z_rows else None,
            open_critical_or_high=z_crit_high,
            open_elevated=z_elev,
            fallback_status=z.status,
        )
        share_pct = (
            round((z_kwh / total_facility_kwh) * 100.0, 1)
            if total_facility_kwh > 0
            else float(z.share_pct)
        )
        zone_breakdown.append(
            ZoneAnalyticsSummaryItem(
                zone_id=z.id,
                slug=z.slug,
                name=z.name,
                primary_meter_code=z.primary_meter_code,
                kwh_used=z_kwh,
                share_pct=share_pct,
                avg_kw=z_avg,
                peak_kw=z_peak,
                power_factor=z_pf,
                delta_vs_baseline_pct=delta_pct,
                derived_status=z_status,
                reading_count=len(z_rows),
            )
        )

    meter_snapshots: list[MeterLiveSnapshotItem] = []
    for m in meters:
        m_str = str(m.id)
        m_rows = samples_by_meter.get(m_str, [])
        m_anoms = [a for a in open_anomalies if a.meter_id == m.id]
        m_crit_high = sum(
            1
            for a in m_anoms
            if a.severity in (AnomalySeverity.CRITICAL.value, AnomalySeverity.HIGH.value)
        )
        m_elev = sum(1 for a in m_anoms if a.severity == AnomalySeverity.ELEVATED.value)

        if m_rows:
            latest_row = m_rows[-1]
            latest_kw = round(float(latest_row.actual_kw), 2)
            latest_pf = round(float(latest_row.power_factor), 3)
            latest_at = latest_row.recorded_at
            m_avg = round(sum(float(r.actual_kw) for r in m_rows) / len(m_rows), 2)
            m_peak = round(max(float(r.actual_kw) for r in m_rows), 2)
        else:
            latest_kw = float(m.current_kw)
            latest_pf = float(m.power_factor)
            latest_at = None
            m_avg = 0.0
            m_peak = 0.0

        m_status = derive_health_status(
            latest_pf=latest_pf if m_rows else None,
            open_critical_or_high=m_crit_high,
            open_elevated=m_elev,
            fallback_status=m.status,
        )
        meter_snapshots.append(
            MeterLiveSnapshotItem(
                meter_id=m.id,
                meter_code=m.meter_code,
                zone_id=m.zone_id,
                latest_recorded_at=latest_at,
                latest_kw=latest_kw,
                avg_kw=m_avg,
                peak_kw=m_peak,
                latest_power_factor=latest_pf,
                reading_count=len(m_rows),
                open_anomalies_count=len(m_anoms),
                derived_status=m_status,
            )
        )

    return AnalyticsSummaryResponse(
        facility_id=facility_id,
        zone_id=zone_id,
        time_window=time_window,
        include_simulated=include_simulated,
        window_start=window_start,
        window_end=window_end,
        latest_recorded_at=latest_recorded_at,
        reading_count=reading_count,
        baselined_reading_count=baselined_count,
        total_kwh=total_kwh,
        total_mwh=total_mwh,
        avg_demand_kw=avg_demand_kw,
        peak_demand_kw=peak_demand_kw,
        contracted_demand_kw=contracted_demand_kw,
        demand_headroom_pct=demand_headroom_pct,
        avg_power_factor=avg_power_factor,
        previous_total_kwh=previous_total_kwh,
        consumption_trend_pct=compute_trend_pct(total_kwh, previous_total_kwh, previous_count),
        open_anomalies_count=open_anomalies_count,
        critical_anomalies_count=critical_anomalies_count,
        potential_annual_savings=round(potential_annual_savings, 2),
        has_quantified_savings=has_quantified_savings,
        unquantified_insights_count=unquantified_insights_count,
        zone_breakdown=zone_breakdown,
        meter_snapshots=meter_snapshots,
        series=series,
        heatmap_matrix=heatmap,
    )

