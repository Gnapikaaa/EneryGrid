from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import math
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.constants import (
    AnomalySeverity,
    AnomalyStatus,
    BaselineStatus,
    CostEstimateStatus,
    QualityFlag,
    TariffPeriod,
    TelemetrySource,
)
from app.models.anomaly import Anomaly, AnomalyWorkflowLog
from app.models.facility import Facility, Meter
from app.models.telemetry import TelemetryReading
from app.models.user import User
from app.schemas.anomaly import AnomalyDetailResponse, AnomalyResponse, AnomalyWorkflowLogResponse
from app.schemas.common import DEFAULT_PAGE, DEFAULT_PAGE_SIZE, PaginatedResponse
from app.services.baselines import EvaluatedReadingItem
from app.services.exceptions import ConflictError, ResourceNotFoundError, ValidationFailureError
from app.services.permissions import (
    ALL_AUTHENTICATED_ROLES,
    ANALYTICS_OPERATIONS_ROLES,
    assert_actor_authorized,
)

_QUANT_2 = Decimal("0.01")
_MIN_PCT = Decimal("-9999.99")
_MAX_PCT = Decimal("9999.99")
_MIN_Z = Decimal("-9999.99")
_MAX_Z = Decimal("9999.99")


def _q2(val: Decimal) -> Decimal:
    return val.quantize(_QUANT_2, rounding=ROUND_HALF_UP)


def _clamp(val: Decimal, low: Decimal, high: Decimal) -> Decimal:
    if val < low:
        return low
    if val > high:
        return high
    return val


@dataclass(frozen=True)
class AnomalyMetrics:
    severity: AnomalySeverity
    z_score: Decimal
    actual_kw: Decimal
    expected_kw: Decimal
    deviation_pct: Decimal
    duration_min: int
    estimated_waste_kwh: Decimal
    estimated_cost: Decimal | None
    cost_estimate_status: CostEstimateStatus
    signature: str
    recommendation: str


@dataclass(frozen=True)
class ExistingAnomalySnapshot:
    status: AnomalyStatus
    severity: AnomalySeverity
    z_score: Decimal
    expected_kw: Decimal
    deviation_pct: Decimal
    estimated_waste_kwh: Decimal
    estimated_cost: Decimal | None
    cost_estimate_status: CostEstimateStatus
    waveform: list[float]
    baseline_waveform: list[float]


@dataclass(frozen=True)
class ReconciliationPlan:
    should_update: bool
    new_status: AnomalyStatus
    new_severity: AnomalySeverity
    new_z_score: Decimal
    new_expected_kw: Decimal
    new_deviation_pct: Decimal
    new_estimated_waste_kwh: Decimal
    new_estimated_cost: Decimal | None
    new_cost_estimate_status: CostEstimateStatus
    log_from_status: AnomalyStatus | None
    log_to_status: AnomalyStatus | None
    log_note: str | None


def classify_anomaly_severity(z_score: Decimal, settings: Settings) -> AnomalySeverity | None:
    if not z_score.is_finite():
        raise ValidationFailureError("z_score must be finite.")
    if z_score >= settings.anomaly_z_score_critical:
        return AnomalySeverity.CRITICAL
    if z_score >= settings.anomaly_z_score_high:
        return AnomalySeverity.HIGH
    if z_score >= settings.anomaly_z_score_elevated:
        return AnomalySeverity.ELEVATED
    return None


def resolve_tariff_rate(facility: Facility, tariff_period: str) -> Decimal | None:
    rate_map = {
        TariffPeriod.PEAK.value: facility.peak_tariff_rate,
        TariffPeriod.MID_PEAK.value: facility.mid_peak_tariff_rate,
        TariffPeriod.OFF_PEAK.value: facility.off_peak_tariff_rate,
    }
    rate = rate_map.get(tariff_period)
    if rate is None or not rate.is_finite() or rate < Decimal("0"):
        return None
    return rate


def compute_deviation_pct(actual_kw: Decimal, raw_mean_kw: Decimal | None) -> Decimal:
    if raw_mean_kw is not None and raw_mean_kw > Decimal("0"):
        raw_pct = ((actual_kw - raw_mean_kw) / raw_mean_kw) * Decimal("100")
        return _q2(_clamp(raw_pct, _MIN_PCT, _MAX_PCT))
    if actual_kw > Decimal("0") and raw_mean_kw == Decimal("0"):
        return Decimal("100.00")
    return Decimal("0.00")


def compute_cost_estimate(
    *,
    raw_waste_kwh: Decimal,
    applicable_rate: Decimal | None,
) -> tuple[Decimal | None, CostEstimateStatus]:
    if applicable_rate is None or not applicable_rate.is_finite() or applicable_rate < Decimal("0"):
        return None, CostEstimateStatus.UNAVAILABLE_TARIFF
    cost = _q2(raw_waste_kwh * applicable_rate)
    return cost, CostEstimateStatus.AVAILABLE


def evaluate_reading_anomaly_metrics(
    *,
    actual_kw: Decimal,
    interval_seconds: int,
    tariff_period: str,
    quality_flag: str,
    source: str,
    baseline_status: BaselineStatus,
    baseline_kw: Decimal | None,
    raw_mean_kw: Decimal | None,
    z_score: Decimal | None,
    applicable_rate: Decimal | None,
    meter_code: str,
    equipment_name: str,
    settings: Settings,
) -> AnomalyMetrics | None:
    """Evaluate positive-deviation anomaly trigger, severity, waste kWh, and tariff cost."""
    if quality_flag != QualityFlag.VALID.value or source == TelemetrySource.SIMULATION.value:
        return None
    if (
        baseline_status != BaselineStatus.READY
        or baseline_kw is None
        or raw_mean_kw is None
        or z_score is None
    ):
        return None

    excess_kw = actual_kw - raw_mean_kw
    if excess_kw < settings.anomaly_min_excess_kw:
        return None

    severity = classify_anomaly_severity(z_score, settings)
    if severity is None:
        return None

    deviation_pct = compute_deviation_pct(actual_kw, raw_mean_kw)
    duration_min = max(1, round(interval_seconds / 60))
    raw_waste_kwh = max(Decimal("0"), excess_kw) * Decimal(interval_seconds) / Decimal("3600")
    estimated_waste_kwh = _q2(raw_waste_kwh)
    estimated_cost, cost_status = compute_cost_estimate(
        raw_waste_kwh=raw_waste_kwh,
        applicable_rate=applicable_rate,
    )

    signature = (
        f"Positive load deviation on {meter_code} ({equipment_name}): "
        f"{actual_kw} kW actual vs {baseline_kw} kW expected (+{deviation_pct}%, z={z_score}) during {tariff_period}."
    )
    recommendation = (
        f"Inspect {equipment_name} ({meter_code}) demand profile and operating schedule during this "
        f"{tariff_period} interval (+{estimated_waste_kwh} kWh estimated excess above baseline)."
    )

    return AnomalyMetrics(
        severity=severity,
        z_score=_q2(_clamp(z_score, _MIN_Z, _MAX_Z)),
        actual_kw=_q2(actual_kw),
        expected_kw=_q2(baseline_kw),
        deviation_pct=deviation_pct,
        duration_min=duration_min,
        estimated_waste_kwh=estimated_waste_kwh,
        estimated_cost=estimated_cost,
        cost_estimate_status=cost_status,
        signature=signature,
        recommendation=recommendation,
    )


def build_reconciliation_plan(
    *,
    existing: ExistingAnomalySnapshot,
    metrics: AnomalyMetrics | None,
    actual_kw: Decimal,
    interval_seconds: int,
    fallback_baseline_kw: Decimal | None,
    fallback_raw_mean_kw: Decimal | None,
    fallback_z_score: Decimal | None,
    applicable_rate: Decimal | None,
) -> ReconciliationPlan:
    """Pure reconciliation plan preserving human workflow states and keeping repeat runs idempotent."""
    if metrics is not None:
        target_severity = metrics.severity if existing.status == AnomalyStatus.OPEN else existing.severity
        changed = (
            existing.severity != target_severity
            or existing.z_score != metrics.z_score
            or existing.expected_kw != metrics.expected_kw
            or existing.deviation_pct != metrics.deviation_pct
            or existing.estimated_waste_kwh != metrics.estimated_waste_kwh
            or existing.estimated_cost != metrics.estimated_cost
            or existing.cost_estimate_status != metrics.cost_estimate_status
        )
        return ReconciliationPlan(
            should_update=changed,
            new_status=existing.status,
            new_severity=target_severity,
            new_z_score=metrics.z_score,
            new_expected_kw=metrics.expected_kw,
            new_deviation_pct=metrics.deviation_pct,
            new_estimated_waste_kwh=metrics.estimated_waste_kwh,
            new_estimated_cost=metrics.estimated_cost,
            new_cost_estimate_status=metrics.cost_estimate_status,
            log_from_status=None,
            log_to_status=None,
            log_note=None,
        )

    # Reading no longer meets anomaly threshold after baseline recalculation
    expected_kw = fallback_baseline_kw if fallback_baseline_kw is not None else _q2(actual_kw)
    raw_mean = fallback_raw_mean_kw if fallback_raw_mean_kw is not None else actual_kw
    z_val = _q2(_clamp(fallback_z_score, _MIN_Z, _MAX_Z)) if fallback_z_score is not None else Decimal("0.00")
    dev_pct = (
        compute_deviation_pct(actual_kw, raw_mean)
        if fallback_raw_mean_kw is not None
        else Decimal("0.00")
    )
    excess_kw = max(Decimal("0"), actual_kw - raw_mean)
    raw_waste = excess_kw * Decimal(interval_seconds) / Decimal("3600")
    waste_kwh = _q2(raw_waste)
    est_cost, cost_status = compute_cost_estimate(
        raw_waste_kwh=raw_waste,
        applicable_rate=applicable_rate,
    )

    fields_changed = (
        existing.z_score != z_val
        or existing.expected_kw != expected_kw
        or existing.deviation_pct != dev_pct
        or existing.estimated_waste_kwh != waste_kwh
        or existing.estimated_cost != est_cost
        or existing.cost_estimate_status != cost_status
    )

    if existing.status == AnomalyStatus.OPEN:
        return ReconciliationPlan(
            should_update=True,
            new_status=AnomalyStatus.RESOLVED,
            new_severity=existing.severity,
            new_z_score=z_val,
            new_expected_kw=expected_kw,
            new_deviation_pct=dev_pct,
            new_estimated_waste_kwh=waste_kwh,
            new_estimated_cost=est_cost,
            new_cost_estimate_status=cost_status,
            log_from_status=AnomalyStatus.OPEN,
            log_to_status=AnomalyStatus.RESOLVED,
            log_note="Auto-resolved during baseline recalculation: reading no longer exceeds detection thresholds.",
        )

    if existing.status in (AnomalyStatus.ACKNOWLEDGED, AnomalyStatus.ASSIGNED):
        return ReconciliationPlan(
            should_update=fields_changed,
            new_status=existing.status,
            new_severity=existing.severity,
            new_z_score=z_val,
            new_expected_kw=expected_kw,
            new_deviation_pct=dev_pct,
            new_estimated_waste_kwh=waste_kwh,
            new_estimated_cost=est_cost,
            new_cost_estimate_status=cost_status,
            log_from_status=existing.status if fields_changed else None,
            log_to_status=existing.status if fields_changed else None,
            log_note=(
                "Baseline recalculated: reading no longer exceeds detection thresholds; human workflow status preserved."
                if fields_changed
                else None
            ),
        )

    # Already Resolved: preserve status and emit zero extra workflow logs
    return ReconciliationPlan(
        should_update=fields_changed,
        new_status=AnomalyStatus.RESOLVED,
        new_severity=existing.severity,
        new_z_score=z_val,
        new_expected_kw=expected_kw,
        new_deviation_pct=dev_pct,
        new_estimated_waste_kwh=waste_kwh,
        new_estimated_cost=est_cost,
        new_cost_estimate_status=cost_status,
        log_from_status=None,
        log_to_status=None,
        log_note=None,
    )


def _build_waveforms(
    history_rows: list[tuple[datetime, Decimal, Decimal | None]],
    target_recorded_at: datetime,
    target_actual: Decimal,
    target_expected: Decimal,
) -> tuple[list[float], list[float]]:
    prior = [row for row in history_rows if row[0] <= target_recorded_at][-12:]
    actual_pts = [float(row[1]) for row in prior]
    base_pts = [float(row[2] if row[2] is not None else row[1]) for row in prior]
    if not actual_pts:
        actual_pts = [float(target_actual)]
        base_pts = [float(target_expected)]
    while len(actual_pts) < 12:
        actual_pts.insert(0, actual_pts[0])
        base_pts.insert(0, base_pts[0])
    return actual_pts[-12:], base_pts[-12:]


def reconcile_anomalies_for_chunk(
    db: Session,
    *,
    meter: Meter,
    facility: Facility,
    actor: User,
    evaluated_items: list[EvaluatedReadingItem],
    settings: Settings,
) -> tuple[int, int, int]:
    """Create and reconcile anomalies inside an already-locked meter chunk transaction."""
    if not evaluated_items:
        return 0, 0, 0

    reading_ids = [item.reading.id for item in evaluated_items]
    existing_rows = list(
        db.scalars(
            select(Anomaly)
            .where(Anomaly.reading_id.in_(reading_ids))
            .with_for_update()
        ).all()
    )
    existing_by_reading_id = {row.reading_id: row for row in existing_rows if row.reading_id is not None}

    min_ts = evaluated_items[0].reading.recorded_at
    max_ts = evaluated_items[-1].reading.recorded_at
    recent_rows = db.execute(
        select(
            TelemetryReading.recorded_at,
            TelemetryReading.actual_kw,
            TelemetryReading.baseline_kw,
        )
        .where(
            TelemetryReading.meter_id == meter.id,
            TelemetryReading.recorded_at <= max_ts,
            TelemetryReading.quality_flag == QualityFlag.VALID.value,
            TelemetryReading.source != TelemetrySource.SIMULATION.value,
        )
        .order_by(TelemetryReading.recorded_at.desc(), TelemetryReading.id.desc())
        .limit(len(evaluated_items) + 12)
    ).all()
    recent_chron = [(r[0], r[1], r[2]) for r in reversed(recent_rows) if r[0] >= min_ts or len(recent_rows) <= 24]
    recent_all = [(r[0], r[1], r[2]) for r in reversed(recent_rows)]
    waveform_source = recent_all if len(recent_all) >= len(recent_chron) else recent_chron

    created = 0
    reconciled = 0
    unchanged = 0

    for item in evaluated_items:
        reading = item.reading
        calc = item.calculation
        rate = resolve_tariff_rate(facility, reading.tariff_period)
        metrics = evaluate_reading_anomaly_metrics(
            actual_kw=reading.actual_kw,
            interval_seconds=reading.interval_seconds,
            tariff_period=reading.tariff_period,
            quality_flag=reading.quality_flag,
            source=reading.source,
            baseline_status=calc.baseline_status,
            baseline_kw=calc.baseline_kw,
            raw_mean_kw=calc.raw_mean_kw,
            z_score=calc.z_score,
            applicable_rate=rate,
            meter_code=meter.meter_code,
            equipment_name=meter.equipment_name,
            settings=settings,
        )

        existing = existing_by_reading_id.get(reading.id)
        if existing is None:
            if metrics is None:
                continue
            waveform, baseline_waveform = _build_waveforms(
                waveform_source,
                reading.recorded_at,
                metrics.actual_kw,
                metrics.expected_kw,
            )
            anomaly = Anomaly(
                event_code=f"EG-{reading.id}",
                facility_id=facility.id,
                zone_id=meter.zone_id,
                meter_id=meter.id,
                reading_id=reading.id,
                detected_at=reading.recorded_at,
                severity=metrics.severity.value,
                status=AnomalyStatus.OPEN.value,
                z_score=metrics.z_score,
                actual_kw=metrics.actual_kw,
                expected_kw=metrics.expected_kw,
                deviation_pct=metrics.deviation_pct,
                duration_min=metrics.duration_min,
                estimated_waste_kwh=metrics.estimated_waste_kwh,
                estimated_cost=metrics.estimated_cost,
                cost_estimate_status=metrics.cost_estimate_status.value,
                signature=metrics.signature,
                recommendation=metrics.recommendation,
                waveform=waveform,
                baseline_waveform=baseline_waveform,
            )
            db.add(anomaly)
            db.flush()
            db.add(
                AnomalyWorkflowLog(
                    anomaly_id=anomaly.id,
                    from_status=None,
                    to_status=AnomalyStatus.OPEN.value,
                    from_assignee_id=None,
                    to_assignee_id=None,
                    changed_by_user_id=actor.id,
                    note="Detected during analytics baseline evaluation.",
                )
            )
            created += 1
            continue

        snap = ExistingAnomalySnapshot(
            status=AnomalyStatus(existing.status),
            severity=AnomalySeverity(existing.severity),
            z_score=existing.z_score,
            expected_kw=existing.expected_kw,
            deviation_pct=existing.deviation_pct,
            estimated_waste_kwh=existing.estimated_waste_kwh,
            estimated_cost=existing.estimated_cost,
            cost_estimate_status=CostEstimateStatus(existing.cost_estimate_status),
            waveform=list(existing.waveform),
            baseline_waveform=list(existing.baseline_waveform),
        )
        plan = build_reconciliation_plan(
            existing=snap,
            metrics=metrics,
            actual_kw=reading.actual_kw,
            interval_seconds=reading.interval_seconds,
            fallback_baseline_kw=calc.baseline_kw,
            fallback_raw_mean_kw=calc.raw_mean_kw,
            fallback_z_score=calc.z_score,
            applicable_rate=rate,
        )
        if not plan.should_update:
            unchanged += 1
            continue

        existing.status = plan.new_status.value
        existing.severity = plan.new_severity.value
        existing.z_score = plan.new_z_score
        existing.expected_kw = plan.new_expected_kw
        existing.deviation_pct = plan.new_deviation_pct
        existing.estimated_waste_kwh = plan.new_estimated_waste_kwh
        existing.estimated_cost = plan.new_estimated_cost
        existing.cost_estimate_status = plan.new_cost_estimate_status.value
        if metrics is not None:
            existing.signature = metrics.signature
            existing.recommendation = metrics.recommendation
        if plan.log_to_status is not None:
            db.add(
                AnomalyWorkflowLog(
                    anomaly_id=existing.id,
                    from_status=plan.log_from_status.value if plan.log_from_status else None,
                    to_status=plan.log_to_status.value,
                    from_assignee_id=existing.assigned_to_user_id,
                    to_assignee_id=existing.assigned_to_user_id,
                    changed_by_user_id=actor.id,
                    note=plan.log_note,
                )
            )
        reconciled += 1

    return created, reconciled, unchanged


def list_anomalies(
    db: Session,
    *,
    actor: User,
    page: int = DEFAULT_PAGE,
    page_size: int = DEFAULT_PAGE_SIZE,
    facility_id: str | None = None,
    zone_id: uuid.UUID | None = None,
    meter_id: uuid.UUID | None = None,
    status: AnomalyStatus | None = None,
    severity: AnomalySeverity | None = None,
    min_z_score: Decimal | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> PaginatedResponse[AnomalyResponse]:
    assert_actor_authorized(actor, ALL_AUTHENTICATED_ROLES)
    if start_at is not None and end_at is not None and start_at > end_at:
        raise ValidationFailureError("start_at cannot be after end_at.")

    filters = []
    if facility_id is not None:
        filters.append(Anomaly.facility_id == facility_id)
    if zone_id is not None:
        filters.append(Anomaly.zone_id == zone_id)
    if meter_id is not None:
        filters.append(Anomaly.meter_id == meter_id)
    if status is not None:
        filters.append(Anomaly.status == status.value)
    if severity is not None:
        filters.append(Anomaly.severity == severity.value)
    if min_z_score is not None:
        filters.append(Anomaly.z_score >= min_z_score)
    if start_at is not None:
        filters.append(Anomaly.detected_at >= start_at)
    if end_at is not None:
        filters.append(Anomaly.detected_at <= end_at)

    total = int(db.scalar(select(func.count(Anomaly.id)).where(*filters)) or 0)
    pages = math.ceil(total / page_size) if total > 0 else 0
    rows = list(
        db.scalars(
            select(Anomaly)
            .where(*filters)
            .order_by(Anomaly.detected_at.desc(), Anomaly.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return PaginatedResponse[AnomalyResponse](
        items=[AnomalyResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


def get_anomaly(
    db: Session,
    *,
    actor: User,
    anomaly_id: uuid.UUID,
) -> AnomalyDetailResponse:
    assert_actor_authorized(actor, ALL_AUTHENTICATED_ROLES)
    anomaly = db.get(Anomaly, anomaly_id)
    if anomaly is None:
        raise ResourceNotFoundError(f"Anomaly '{anomaly_id}' was not found.")
    return AnomalyDetailResponse.model_validate(anomaly)


def get_anomaly_history(
    db: Session,
    *,
    actor: User,
    anomaly_id: uuid.UUID,
) -> list[AnomalyWorkflowLogResponse]:
    assert_actor_authorized(actor, ALL_AUTHENTICATED_ROLES)
    if db.get(Anomaly, anomaly_id) is None:
        raise ResourceNotFoundError(f"Anomaly '{anomaly_id}' was not found.")
    logs = list(
        db.scalars(
            select(AnomalyWorkflowLog)
            .where(AnomalyWorkflowLog.anomaly_id == anomaly_id)
            .order_by(AnomalyWorkflowLog.changed_at.asc(), AnomalyWorkflowLog.id.asc())
        ).all()
    )
    return [AnomalyWorkflowLogResponse.model_validate(log) for log in logs]


def acknowledge_anomaly(
    db: Session,
    *,
    actor: User,
    anomaly_id: uuid.UUID,
    note: str | None = None,
) -> AnomalyDetailResponse:
    assert_actor_authorized(actor, ANALYTICS_OPERATIONS_ROLES)
    anomaly = db.scalar(select(Anomaly).where(Anomaly.id == anomaly_id).with_for_update())
    if anomaly is None:
        raise ResourceNotFoundError(f"Anomaly '{anomaly_id}' was not found.")
    if anomaly.status != AnomalyStatus.OPEN.value:
        raise ConflictError(
            f"Cannot acknowledge anomaly in '{anomaly.status}' status; expected 'Open'."
        )

    prev_status = anomaly.status
    anomaly.status = AnomalyStatus.ACKNOWLEDGED.value
    db.add(
        AnomalyWorkflowLog(
            anomaly_id=anomaly.id,
            from_status=prev_status,
            to_status=AnomalyStatus.ACKNOWLEDGED.value,
            from_assignee_id=anomaly.assigned_to_user_id,
            to_assignee_id=anomaly.assigned_to_user_id,
            changed_by_user_id=actor.id,
            note=note,
        )
    )
    db.commit()
    db.refresh(anomaly)
    return AnomalyDetailResponse.model_validate(anomaly)


def investigate_anomaly(
    db: Session,
    *,
    actor: User,
    anomaly_id: uuid.UUID,
    assigned_to_user_id: uuid.UUID | None = None,
    note: str | None = None,
) -> AnomalyDetailResponse:
    assert_actor_authorized(actor, ANALYTICS_OPERATIONS_ROLES)
    anomaly = db.scalar(select(Anomaly).where(Anomaly.id == anomaly_id).with_for_update())
    if anomaly is None:
        raise ResourceNotFoundError(f"Anomaly '{anomaly_id}' was not found.")
    if anomaly.status not in (AnomalyStatus.OPEN.value, AnomalyStatus.ACKNOWLEDGED.value):
        raise ConflictError(
            f"Cannot start investigation from '{anomaly.status}' status; expected 'Open' or 'Acknowledged'."
        )

    target_user_id = assigned_to_user_id or actor.id
    assignee = db.scalar(
    select(User).where(User.id == target_user_id).with_for_update(read=True)
)
    if assignee is None:
        raise ResourceNotFoundError(f"Assignee user '{target_user_id}' was not found.")
    if not assignee.is_active:
        raise ConflictError("Cannot assign anomaly to an inactive user account.")

    prev_status = anomaly.status
    prev_assignee = anomaly.assigned_to_user_id
    anomaly.status = AnomalyStatus.ASSIGNED.value
    anomaly.assigned_to_user_id = assignee.id
    db.add(
        AnomalyWorkflowLog(
            anomaly_id=anomaly.id,
            from_status=prev_status,
            to_status=AnomalyStatus.ASSIGNED.value,
            from_assignee_id=prev_assignee,
            to_assignee_id=assignee.id,
            changed_by_user_id=actor.id,
            note=note,
        )
    )
    db.commit()
    db.refresh(anomaly)
    return AnomalyDetailResponse.model_validate(anomaly)


def resolve_anomaly(
    db: Session,
    *,
    actor: User,
    anomaly_id: uuid.UUID,
    note: str,
) -> AnomalyDetailResponse:
    assert_actor_authorized(actor, ANALYTICS_OPERATIONS_ROLES)
    anomaly = db.scalar(select(Anomaly).where(Anomaly.id == anomaly_id).with_for_update())
    if anomaly is None:
        raise ResourceNotFoundError(f"Anomaly '{anomaly_id}' was not found.")
    if anomaly.status == AnomalyStatus.RESOLVED.value:
        raise ConflictError("Anomaly is already 'Resolved'.")

    prev_status = anomaly.status
    anomaly.status = AnomalyStatus.RESOLVED.value
    db.add(
        AnomalyWorkflowLog(
            anomaly_id=anomaly.id,
            from_status=prev_status,
            to_status=AnomalyStatus.RESOLVED.value,
            from_assignee_id=anomaly.assigned_to_user_id,
            to_assignee_id=anomaly.assigned_to_user_id,
            changed_by_user_id=actor.id,
            note=note,
        )
    )
    db.commit()
    db.refresh(anomaly)
    return AnomalyDetailResponse.model_validate(anomaly)


def reopen_anomaly(
    db: Session,
    *,
    actor: User,
    anomaly_id: uuid.UUID,
    note: str,
) -> AnomalyDetailResponse:
    assert_actor_authorized(actor, ANALYTICS_OPERATIONS_ROLES)
    anomaly = db.scalar(select(Anomaly).where(Anomaly.id == anomaly_id).with_for_update())
    if anomaly is None:
        raise ResourceNotFoundError(f"Anomaly '{anomaly_id}' was not found.")
    if anomaly.status != AnomalyStatus.RESOLVED.value:
        raise ConflictError(
            f"Cannot reopen anomaly from '{anomaly.status}' status; expected 'Resolved'."
        )

    prev_status = anomaly.status
    prev_assignee = anomaly.assigned_to_user_id
    anomaly.status = AnomalyStatus.OPEN.value
    anomaly.assigned_to_user_id = None
    db.add(
        AnomalyWorkflowLog(
            anomaly_id=anomaly.id,
            from_status=prev_status,
            to_status=AnomalyStatus.OPEN.value,
            from_assignee_id=prev_assignee,
            to_assignee_id=None,
            changed_by_user_id=actor.id,
            note=note,
        )
    )
    db.commit()
    db.refresh(anomaly)
    return AnomalyDetailResponse.model_validate(anomaly)
