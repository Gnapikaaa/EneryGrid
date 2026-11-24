from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import struct
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, exists, func, or_, select, text, tuple_
from sqlalchemy.orm import Session, aliased

from app.core.config import Settings
from app.core.constants import BaselineStatus, QualityFlag, TelemetrySource
from app.models.facility import Facility, Meter
from app.models.telemetry import TelemetryReading
from app.services.exceptions import ValidationFailureError

LOCK_NS_METER_ANALYTICS = 2001
_QUANT_2 = Decimal("0.01")
_MIN_Z = Decimal("-9999.99")
_MAX_Z = Decimal("9999.99")


def stable_lock_id(key: str) -> int:
    """Deterministic signed 32-bit integer lock key for pg_advisory_xact_lock(ns, id)."""
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int(struct.unpack(">i", digest[:4])[0])


def acquire_meter_advisory_lock(db: Session, meter_id: uuid.UUID) -> None:
    """Acquire transaction-scoped advisory lock serializing processing on a single meter."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :key)"),
        {"ns": LOCK_NS_METER_ANALYTICS, "key": stable_lock_id(str(meter_id))},
    )


def _quantize_2(value: Decimal) -> Decimal:
    return value.quantize(_QUANT_2, rounding=ROUND_HALF_UP)


def _clamp_decimal(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


def _require_finite(value: Decimal, label: str) -> Decimal:
    if not value.is_finite():
        raise ValidationFailureError(f"Non-finite decimal encountered for '{label}'.")
    return value


@dataclass(frozen=True)
class BaselineSample:
    reading_id: int
    recorded_at: datetime
    interval_seconds: int
    actual_kw: Decimal


@dataclass(frozen=True)
class BaselineCalculationResult:
    baseline_status: BaselineStatus
    baseline_kw: Decimal | None
    std_dev_kw: Decimal | None
    z_score: Decimal | None
    sample_count: int
    raw_mean_kw: Decimal | None
    raw_sample_std_kw: Decimal | None
    effective_std_dev_kw: Decimal | None
    bucket_used: str


@dataclass(frozen=True)
class RetryStateUpdate:
    baseline_computed_at: datetime | None
    baseline_last_attempt_at: datetime | None
    baseline_attempt_count: int
    baseline_retry_after: datetime | None
    baseline_attempt_max_meter_id: int | None


@dataclass(frozen=True)
class EvaluatedReadingItem:
    reading: TelemetryReading
    calculation: BaselineCalculationResult
    was_previously_ready: bool


@dataclass(frozen=True)
class MeterBaselineChunkOutcome:
    evaluated_items: list[EvaluatedReadingItem]
    baselines_ready: int
    baselines_insufficient: int
    last_recorded_at: datetime | None
    last_reading_id: int | None


def compute_baseline_for_reading(
    *,
    target_recorded_at: datetime,
    target_interval_seconds: int,
    target_actual_kw: Decimal,
    facility_timezone: str,
    candidate_samples: list[BaselineSample],
    lookback_days: int,
    min_samples: int,
    allow_hour_only_fallback: bool,
    require_matching_interval: bool,
    max_window_samples_per_bucket: int,
    min_std_dev_kw: Decimal,
    min_std_dev_pct: Decimal,
) -> BaselineCalculationResult:
    """Pure deterministic rolling baseline calculation matching the approved Phase 2E formulas."""
    if min_samples < 3:
        raise ValidationFailureError("baseline_min_samples must be at least 3.")
    _require_finite(target_actual_kw, "target_actual_kw")
    _require_finite(min_std_dev_kw, "min_std_dev_kw")
    _require_finite(min_std_dev_pct, "min_std_dev_pct")
    if min_std_dev_kw <= Decimal("0"):
        raise ValidationFailureError("baseline_min_std_dev_kw must be greater than 0.")

    tz = ZoneInfo(facility_timezone)
    target_utc = target_recorded_at.astimezone(UTC)
    target_local = target_utc.astimezone(tz)
    target_hour = target_local.hour
    target_is_weekend = target_local.weekday() >= 5
    window_start = target_utc - timedelta(days=lookback_days)

    primary_bucket: list[BaselineSample] = []
    hour_only_bucket: list[BaselineSample] = []

    for sample in candidate_samples:
        _require_finite(sample.actual_kw, "sample.actual_kw")
        sample_utc = sample.recorded_at.astimezone(UTC)
        if not (window_start <= sample_utc < target_utc):
            continue
        if require_matching_interval and sample.interval_seconds != target_interval_seconds:
            continue

        sample_local = sample_utc.astimezone(tz)
        if sample_local.hour != target_hour:
            continue

        hour_only_bucket.append(sample)
        if (sample_local.weekday() >= 5) == target_is_weekend:
            primary_bucket.append(sample)

    if len(primary_bucket) >= min_samples:
        selected = primary_bucket
        bucket_used = "hour_daytype"
    elif allow_hour_only_fallback and len(hour_only_bucket) >= min_samples:
        selected = hour_only_bucket
        bucket_used = "hour_only_fallback"
    else:
        return BaselineCalculationResult(
            baseline_status=BaselineStatus.INSUFFICIENT_HISTORY,
            baseline_kw=None,
            std_dev_kw=None,
            z_score=None,
            sample_count=max(len(primary_bucket), len(hour_only_bucket))
            if allow_hour_only_fallback
            else len(primary_bucket),
            raw_mean_kw=None,
            raw_sample_std_kw=None,
            effective_std_dev_kw=None,
            bucket_used="insufficient",
        )

    # Deterministic cap to newest N comparable historical samples in the selected bucket
    selected.sort(key=lambda item: (item.recorded_at.astimezone(UTC), item.reading_id), reverse=True)
    capped = selected[:max_window_samples_per_bucket]

    n = len(capped)
    mean_kw = sum((s.actual_kw for s in capped), Decimal("0")) / Decimal(n)
    _require_finite(mean_kw, "mean_kw")

    sample_variance = sum(((s.actual_kw - mean_kw) ** 2 for s in capped), Decimal("0")) / Decimal(
        n - 1
    )
    _require_finite(sample_variance, "sample_variance")
    sample_std_kw = sample_variance.sqrt()
    _require_finite(sample_std_kw, "sample_std_kw")

    pct_floor_kw = mean_kw * min_std_dev_pct
    effective_std_dev_kw = max(sample_std_kw, min_std_dev_kw, pct_floor_kw)
    _require_finite(effective_std_dev_kw, "effective_std_dev_kw")

    raw_z = (target_actual_kw - mean_kw) / effective_std_dev_kw
    _require_finite(raw_z, "raw_z")

    baseline_kw = _quantize_2(mean_kw)
    std_dev_kw = _quantize_2(sample_std_kw)
    z_score = _quantize_2(_clamp_decimal(raw_z, _MIN_Z, _MAX_Z))

    return BaselineCalculationResult(
        baseline_status=BaselineStatus.READY,
        baseline_kw=baseline_kw,
        std_dev_kw=std_dev_kw,
        z_score=z_score,
        sample_count=n,
        raw_mean_kw=mean_kw,
        raw_sample_std_kw=sample_std_kw,
        effective_std_dev_kw=effective_std_dev_kw,
        bucket_used=bucket_used,
    )


def compute_retry_state_update(
    *,
    is_ready: bool,
    reprocess: bool,
    retry_exhausted: bool,
    was_previously_ready: bool,
    prior_attempt_count: int,
    now_utc: datetime,
    meter_max_valid_id: int | None,
    max_attempts: int,
    base_cooldown_minutes: int,
    max_cooldown_minutes: int,
) -> RetryStateUpdate:
    """Compute deterministic retry/completion columns for a baseline evaluation pass."""
    if is_ready:
        return RetryStateUpdate(
            baseline_computed_at=now_utc,
            baseline_last_attempt_at=None,
            baseline_attempt_count=0,
            baseline_retry_after=None,
            baseline_attempt_max_meter_id=None,
        )

    def _next_retry_after(attempt_count: int) -> datetime | None:
        if attempt_count >= max_attempts:
            return None
        exponent = max(0, attempt_count - 1)
        cooldown_minutes = min(max_cooldown_minutes, base_cooldown_minutes * (2**exponent))
        return now_utc + timedelta(minutes=cooldown_minutes)

    if reprocess:
        if was_previously_ready:
            new_count = 1
        elif prior_attempt_count >= max_attempts:
            new_count = max_attempts
        else:
            new_count = min(max_attempts, prior_attempt_count + 1)

        return RetryStateUpdate(
            baseline_computed_at=None,
            baseline_last_attempt_at=now_utc,
            baseline_attempt_count=new_count,
            baseline_retry_after=_next_retry_after(new_count),
            baseline_attempt_max_meter_id=meter_max_valid_id,
        )

    if retry_exhausted:
        return RetryStateUpdate(
            baseline_computed_at=None,
            baseline_last_attempt_at=now_utc,
            baseline_attempt_count=1,
            baseline_retry_after=_next_retry_after(1),
            baseline_attempt_max_meter_id=meter_max_valid_id,
        )

    new_count = min(max_attempts, prior_attempt_count + 1)
    return RetryStateUpdate(
        baseline_computed_at=None,
        baseline_last_attempt_at=now_utc,
        baseline_attempt_count=new_count,
        baseline_retry_after=_next_retry_after(new_count),
        baseline_attempt_max_meter_id=meter_max_valid_id,
    )


def build_base_eligibility_clauses(
    *,
    facility_id: str | None = None,
    zone_id: uuid.UUID | None = None,
    meter_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = [
        TelemetryReading.quality_flag == QualityFlag.VALID.value,
        TelemetryReading.source != TelemetrySource.SIMULATION.value,
    ]
    if facility_id is not None:
        clauses.append(TelemetryReading.facility_id == facility_id)
    if zone_id is not None:
        clauses.append(TelemetryReading.zone_id == zone_id)
    if meter_id is not None:
        clauses.append(TelemetryReading.meter_id == meter_id)
    if start_at is not None:
        clauses.append(TelemetryReading.recorded_at >= start_at)
    if end_at is not None:
        clauses.append(TelemetryReading.recorded_at <= end_at)
    return clauses


def build_mode_eligibility_clause(
    *,
    reprocess: bool,
    retry_insufficient: bool,
    retry_exhausted: bool,
    now_utc: datetime,
    max_attempts: int,
) -> ColumnElement[bool] | None:
    """Build exact predicate separating pending incremental, exhausted recovery, and full reprocess."""
    if reprocess and retry_exhausted:
        raise ValidationFailureError("reprocess=True and retry_exhausted=True cannot be combined.")
    if retry_exhausted and retry_insufficient:
        raise ValidationFailureError(
            "retry_exhausted=True and retry_insufficient=True cannot be combined."
        )

    if reprocess:
        return None

    if retry_exhausted:
        return and_(
            TelemetryReading.baseline_computed_at.is_(None),
            TelemetryReading.baseline_attempt_count >= max_attempts,
        )

    prior = aliased(TelemetryReading)
    earlier_new_history = exists(
        select(1).where(
            prior.meter_id == TelemetryReading.meter_id,
            prior.quality_flag == QualityFlag.VALID.value,
            prior.source != TelemetrySource.SIMULATION.value,
            prior.id > func.coalesce(TelemetryReading.baseline_attempt_max_meter_id, 0),
            prior.recorded_at < TelemetryReading.recorded_at,
        )
    )

    wake_conditions: list[ColumnElement[bool]] = [
        TelemetryReading.baseline_last_attempt_at.is_(None),
        TelemetryReading.baseline_retry_after <= now_utc,
        earlier_new_history,
    ]

    return and_(
        TelemetryReading.baseline_computed_at.is_(None),
        TelemetryReading.baseline_attempt_count < max_attempts,
        or_(*wake_conditions),
    )


def count_exhausted_pending_readings(
    db: Session,
    *,
    settings: Settings,
    facility_id: str | None = None,
    zone_id: uuid.UUID | None = None,
    meter_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> int:
    clauses = build_base_eligibility_clauses(
        facility_id=facility_id,
        zone_id=zone_id,
        meter_id=meter_id,
        start_at=start_at,
        end_at=end_at,
    )
    clauses.append(TelemetryReading.baseline_computed_at.is_(None))
    clauses.append(
        TelemetryReading.baseline_attempt_count >= settings.analytics_insufficient_max_attempts
    )
    return int(db.scalar(select(func.count(TelemetryReading.id)).where(*clauses)) or 0)


def count_remaining_mode_eligible_readings(
    db: Session,
    *,
    settings: Settings,
    now_utc: datetime,
    reprocess: bool,
    retry_insufficient: bool,
    retry_exhausted: bool,
    facility_id: str | None = None,
    zone_id: uuid.UUID | None = None,
    meter_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    after_meter_id: uuid.UUID | None = None,
    after_recorded_at: datetime | None = None,
    after_reading_id: int | None = None,
) -> int:
    clauses = build_base_eligibility_clauses(
        facility_id=facility_id,
        zone_id=zone_id,
        meter_id=meter_id,
        start_at=start_at,
        end_at=end_at,
    )
    mode_clause = build_mode_eligibility_clause(
        reprocess=reprocess,
        retry_insufficient=retry_insufficient,
        retry_exhausted=retry_exhausted,
        now_utc=now_utc,
        max_attempts=settings.analytics_insufficient_max_attempts,
    )
    if mode_clause is not None:
        clauses.append(mode_clause)

    if after_meter_id is not None:
        assert after_recorded_at is not None and after_reading_id is not None
        clauses.append(
            or_(
                TelemetryReading.meter_id > after_meter_id,
                and_(
                    TelemetryReading.meter_id == after_meter_id,
                    tuple_(TelemetryReading.recorded_at, TelemetryReading.id)
                    > (after_recorded_at, after_reading_id),
                ),
            )
        )

    return int(db.scalar(select(func.count(TelemetryReading.id)).where(*clauses)) or 0)


def process_meter_baseline_chunk(
    db: Session,
    *,
    meter: Meter,
    facility: Facility,
    settings: Settings,
    now_utc: datetime,
    chunk_limit: int,
    reprocess: bool,
    retry_insufficient: bool,
    retry_exhausted: bool,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    after_recorded_at: datetime | None = None,
    after_reading_id: int | None = None,
) -> MeterBaselineChunkOutcome:
    """Process a single bounded keyset chunk of baseline calculations for one meter."""
    clauses = build_base_eligibility_clauses(
        facility_id=facility.id,
        zone_id=meter.zone_id,
        meter_id=meter.id,
        start_at=start_at,
        end_at=end_at,
    )
    mode_clause = build_mode_eligibility_clause(
        reprocess=reprocess,
        retry_insufficient=retry_insufficient,
        retry_exhausted=retry_exhausted,
        now_utc=now_utc,
        max_attempts=settings.analytics_insufficient_max_attempts,
    )
    if mode_clause is not None:
        clauses.append(mode_clause)

    if after_recorded_at is not None and after_reading_id is not None:
        clauses.append(
            tuple_(TelemetryReading.recorded_at, TelemetryReading.id)
            > (after_recorded_at, after_reading_id)
        )

    target_readings = list(
        db.scalars(
            select(TelemetryReading)
            .where(*clauses)
            .order_by(TelemetryReading.recorded_at.asc(), TelemetryReading.id.asc())
            .limit(chunk_limit)
        ).all()
    )
    if not target_readings:
        return MeterBaselineChunkOutcome(
            evaluated_items=[],
            baselines_ready=0,
            baselines_insufficient=0,
            last_recorded_at=None,
            last_reading_id=None,
        )

    min_ts = target_readings[0].recorded_at.astimezone(UTC)
    max_ts = target_readings[-1].recorded_at.astimezone(UTC)
    history_start = min_ts - timedelta(days=settings.baseline_lookback_days)

    candidate_rows = db.execute(
        select(
            TelemetryReading.id,
            TelemetryReading.recorded_at,
            TelemetryReading.interval_seconds,
            TelemetryReading.actual_kw,
        )
        .where(
            TelemetryReading.meter_id == meter.id,
            TelemetryReading.quality_flag == QualityFlag.VALID.value,
            TelemetryReading.source != TelemetrySource.SIMULATION.value,
            TelemetryReading.recorded_at >= history_start,
            TelemetryReading.recorded_at < max_ts,
        )
        .order_by(TelemetryReading.recorded_at.asc(), TelemetryReading.id.asc())
    ).all()

    candidates = [
        BaselineSample(
            reading_id=int(row[0]),
            recorded_at=row[1],
            interval_seconds=int(row[2]),
            actual_kw=row[3],
        )
        for row in candidate_rows
    ]

    meter_max_valid_id = db.scalar(
        select(func.max(TelemetryReading.id)).where(
            TelemetryReading.meter_id == meter.id,
            TelemetryReading.quality_flag == QualityFlag.VALID.value,
            TelemetryReading.source != TelemetrySource.SIMULATION.value,
        )
    )
    resolved_max_id = int(meter_max_valid_id) if meter_max_valid_id is not None else None

    evaluated_items: list[EvaluatedReadingItem] = []
    ready_count = 0
    insufficient_count = 0

    for reading in target_readings:
        was_ready = reading.baseline_computed_at is not None
        calc = compute_baseline_for_reading(
            target_recorded_at=reading.recorded_at,
            target_interval_seconds=reading.interval_seconds,
            target_actual_kw=reading.actual_kw,
            facility_timezone=facility.timezone,
            candidate_samples=candidates,
            lookback_days=settings.baseline_lookback_days,
            min_samples=settings.baseline_min_samples,
            allow_hour_only_fallback=settings.baseline_allow_hour_only_fallback,
            require_matching_interval=settings.baseline_require_matching_interval,
            max_window_samples_per_bucket=settings.baseline_max_window_samples_per_bucket,
            min_std_dev_kw=settings.baseline_min_std_dev_kw,
            min_std_dev_pct=settings.baseline_min_std_dev_pct,
        )

        is_ready = calc.baseline_status == BaselineStatus.READY
        retry_update = compute_retry_state_update(
            is_ready=is_ready,
            reprocess=reprocess,
            retry_exhausted=retry_exhausted,
            was_previously_ready=was_ready,
            prior_attempt_count=reading.baseline_attempt_count,
            now_utc=now_utc,
            meter_max_valid_id=resolved_max_id,
            max_attempts=settings.analytics_insufficient_max_attempts,
            base_cooldown_minutes=settings.analytics_insufficient_base_cooldown_minutes,
            max_cooldown_minutes=settings.analytics_insufficient_max_cooldown_minutes,
        )

        reading.baseline_status = calc.baseline_status.value
        reading.baseline_kw = calc.baseline_kw
        reading.std_dev_kw = calc.std_dev_kw
        reading.z_score = calc.z_score
        reading.baseline_computed_at = retry_update.baseline_computed_at
        reading.baseline_last_attempt_at = retry_update.baseline_last_attempt_at
        reading.baseline_attempt_count = retry_update.baseline_attempt_count
        reading.baseline_retry_after = retry_update.baseline_retry_after
        reading.baseline_attempt_max_meter_id = retry_update.baseline_attempt_max_meter_id

        if is_ready:
            ready_count += 1
        else:
            insufficient_count += 1

        evaluated_items.append(
            EvaluatedReadingItem(
                reading=reading,
                calculation=calc,
                was_previously_ready=was_ready,
            )
        )

    db.flush()

    last_reading = target_readings[-1]
    return MeterBaselineChunkOutcome(
        evaluated_items=evaluated_items,
        baselines_ready=ready_count,
        baselines_insufficient=insufficient_count,
        last_recorded_at=last_reading.recorded_at.astimezone(UTC),
        last_reading_id=last_reading.id,
    )
