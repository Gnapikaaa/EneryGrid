from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.constants import BaselineStatus, HealthStatus, QualityFlag, TelemetrySource
from app.models.facility import Facility, Meter, Zone
from app.models.telemetry import TelemetryReading
from app.services.baselines import (
    BaselineSample,
    compute_baseline_for_reading,
    compute_retry_state_update,
    process_meter_baseline_chunk,
)


def _sample_series(
    *,
    target_dt: datetime,
    days_back: list[int],
    values: list[Decimal],
    interval_seconds: int = 900,
) -> list[BaselineSample]:
    return [
        BaselineSample(
            reading_id=idx + 1,
            recorded_at=target_dt - timedelta(days=offset),
            interval_seconds=interval_seconds,
            actual_kw=val,
        )
        for idx, (offset, val) in enumerate(zip(days_back, values, strict=True))
    ]


def test_baseline_math_exact_mean_raw_std_dev_floor_and_zscore() -> None:
    target_dt = datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)
    # 14 samples alternating 100.00 and 100.50 -> mean = 100.25, raw sample std ~= 0.2594 -> stored 0.26
    # Floor = max(0.2594, 1.00, 100.25 * 0.02 = 2.005) = 2.005
    # Target = 106.265 -> excess = 6.015 -> z = 6.015 / 2.005 = 3.00
    days = [14 - i for i in range(14)]
    vals = [Decimal("100.00") if i % 2 == 0 else Decimal("100.50") for i in range(14)]
    samples = _sample_series(target_dt=target_dt, days_back=days, values=vals)

    res = compute_baseline_for_reading(
        target_recorded_at=target_dt,
        target_interval_seconds=900,
        target_actual_kw=Decimal("106.265"),
        facility_timezone="UTC",
        candidate_samples=samples,
        lookback_days=30,
        min_samples=14,
        allow_hour_only_fallback=True,
        require_matching_interval=True,
        max_window_samples_per_bucket=120,
        min_std_dev_kw=Decimal("1.00"),
        min_std_dev_pct=Decimal("0.02"),
    )

    assert res.baseline_status == BaselineStatus.READY
    assert res.baseline_kw == Decimal("100.25")
    assert res.std_dev_kw == Decimal("0.26")  # Raw Bessel std dev stored, NOT floored
    assert res.effective_std_dev_kw == Decimal("2.0050")
    assert res.z_score == Decimal("3.00")
    assert res.bucket_used == "hour_only_fallback"


def test_baseline_zero_baseline_and_zero_variance_edge_cases() -> None:
    target_dt = datetime(2026, 11, 20, 3, 0, tzinfo=timezone.utc)  # Friday 03:00 UTC

    # Case 1: Zero baseline (all 14 weekday samples at 0.00 kW)
    weekday_offsets = [1, 2, 3, 4, 7, 8, 9, 10, 11, 14, 15, 16, 17, 18]
    zero_samples = _sample_series(
        target_dt=target_dt,
        days_back=weekday_offsets,
        values=[Decimal("0.00")] * 14,
    )
    res_zero = compute_baseline_for_reading(
        target_recorded_at=target_dt,
        target_interval_seconds=900,
        target_actual_kw=Decimal("5.25"),
        facility_timezone="UTC",
        candidate_samples=zero_samples,
        lookback_days=30,
        min_samples=14,
        allow_hour_only_fallback=True,
        require_matching_interval=True,
        max_window_samples_per_bucket=120,
        min_std_dev_kw=Decimal("1.00"),
        min_std_dev_pct=Decimal("0.02"),
    )
    assert res_zero.baseline_status == BaselineStatus.READY
    assert res_zero.baseline_kw == Decimal("0.00")
    assert res_zero.std_dev_kw == Decimal("0.00")
    assert res_zero.effective_std_dev_kw == Decimal("1.00")
    assert res_zero.z_score == Decimal("5.25")
    assert res_zero.bucket_used == "hour_daytype"

    # Case 2: Non-zero constant load (std_dev = 0.00, pct floor 2% applies)
    const_samples = _sample_series(
        target_dt=target_dt,
        days_back=weekday_offsets,
        values=[Decimal("200.00")] * 14,
    )
    res_const = compute_baseline_for_reading(
        target_recorded_at=target_dt,
        target_interval_seconds=900,
        target_actual_kw=Decimal("200.05"),
        facility_timezone="UTC",
        candidate_samples=const_samples,
        lookback_days=30,
        min_samples=14,
        allow_hour_only_fallback=True,
        require_matching_interval=True,
        max_window_samples_per_bucket=120,
        min_std_dev_kw=Decimal("1.00"),
        min_std_dev_pct=Decimal("0.02"),
    )
    assert res_const.std_dev_kw == Decimal("0.00")
    assert res_const.effective_std_dev_kw == Decimal("4.0000")
    assert res_const.z_score == Decimal("0.01")


def test_baseline_deterministic_120_sample_cap_and_mixed_interval_exclusion() -> None:
    target_dt = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)  # Friday
    # 12 intervals/hour at 300s across 15 recent weekdays -> 180 weekday samples inside 30 days.
    # Oldest 60 are 50.00 kW; newest 120 are 150.00 kW. Plus 20 non-comparable 3600s at 999.00 kW.
    samples: list[BaselineSample] = []
    rid = 1
    weekday_dates = [
        target_dt - timedelta(days=d)
        for d in range(1, 30)
        if (target_dt - timedelta(days=d)).weekday() < 5
    ][:15]
    for day_ts in weekday_dates:
        for slot in range(12):
            ts = day_ts.replace(minute=slot * 5)
            samples.append(
                BaselineSample(
                    reading_id=rid,
                    recorded_at=ts,
                    interval_seconds=300,
                    actual_kw=Decimal("150.00"),
                )
            )
            rid += 1

    samples.sort(key=lambda s: (s.recorded_at, s.reading_id))
    assert len(samples) == 180
    for i in range(60):
        samples[i] = BaselineSample(
            reading_id=samples[i].reading_id,
            recorded_at=samples[i].recorded_at,
            interval_seconds=300,
            actual_kw=Decimal("50.00"),
        )

    # Add non-comparable 3600s samples at 999.00 kW
    for day in range(1, 21):
        samples.append(
            BaselineSample(
                reading_id=rid,
                recorded_at=target_dt - timedelta(days=day),
                interval_seconds=3600,
                actual_kw=Decimal("999.00"),
            )
        )
        rid += 1

    res = compute_baseline_for_reading(
        target_recorded_at=target_dt,
        target_interval_seconds=300,
        target_actual_kw=Decimal("150.00"),
        facility_timezone="UTC",
        candidate_samples=samples,
        lookback_days=30,
        min_samples=14,
        allow_hour_only_fallback=True,
        require_matching_interval=True,
        max_window_samples_per_bucket=120,
        min_std_dev_kw=Decimal("1.00"),
        min_std_dev_pct=Decimal("0.02"),
    )
    assert res.sample_count == 120
    assert res.baseline_kw == Decimal("150.00")

    # Target at 3600s finds 20 matching 3600s samples -> mean 999.00, excluding 300s rows
    res_hour_interval = compute_baseline_for_reading(
        target_recorded_at=target_dt,
        target_interval_seconds=3600,
        target_actual_kw=Decimal("999.00"),
        facility_timezone="UTC",
        candidate_samples=samples,
        lookback_days=30,
        min_samples=14,
        allow_hour_only_fallback=True,
        require_matching_interval=True,
        max_window_samples_per_bucket=120,
        min_std_dev_kw=Decimal("1.00"),
        min_std_dev_pct=Decimal("0.02"),
    )
    assert res_hour_interval.baseline_kw == Decimal("999.00")

    # Target at 900s has 0 matching 900s intervals -> insufficient_history despite 300s/3600s rows
    res_mixed_missing = compute_baseline_for_reading(
        target_recorded_at=target_dt,
        target_interval_seconds=900,
        target_actual_kw=Decimal("150.00"),
        facility_timezone="UTC",
        candidate_samples=samples,
        lookback_days=30,
        min_samples=14,
        allow_hour_only_fallback=True,
        require_matching_interval=True,
        max_window_samples_per_bucket=120,
        min_std_dev_kw=Decimal("1.00"),
        min_std_dev_pct=Decimal("0.02"),
    )
    assert res_mixed_missing.baseline_status == BaselineStatus.INSUFFICIENT_HISTORY


def test_reprocess_retry_state_clamps_at_max_and_resets_when_ready() -> None:
    now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)

    # Repeated reprocess=True on chronic insufficient-history increments up to max=3 then clamps
    st1 = compute_retry_state_update(
        is_ready=False,
        reprocess=True,
        retry_exhausted=False,
        was_previously_ready=False,
        prior_attempt_count=2,
        now_utc=now,
        meter_max_valid_id=100,
        max_attempts=3,
        base_cooldown_minutes=60,
        max_cooldown_minutes=1440,
    )
    assert st1.baseline_attempt_count == 3
    assert st1.baseline_retry_after is None

    st2 = compute_retry_state_update(
        is_ready=False,
        reprocess=True,
        retry_exhausted=False,
        was_previously_ready=False,
        prior_attempt_count=3,
        now_utc=now + timedelta(hours=1),
        meter_max_valid_id=105,
        max_attempts=3,
        base_cooldown_minutes=60,
        max_cooldown_minutes=1440,
    )
    assert st2.baseline_attempt_count == 3  # Never reaches 4
    assert st2.baseline_retry_after is None
    assert st2.baseline_attempt_max_meter_id == 105

    # Lowered max_attempts config clamps stale higher counter cleanly
    st_clamp = compute_retry_state_update(
        is_ready=False,
        reprocess=True,
        retry_exhausted=False,
        was_previously_ready=False,
        prior_attempt_count=15,
        now_utc=now,
        meter_max_valid_id=110,
        max_attempts=5,
        base_cooldown_minutes=60,
        max_cooldown_minutes=1440,
    )
    assert st_clamp.baseline_attempt_count == 5

    # Previously ready dropping back to insufficient_history initializes count=1 with cooldown
    st_demote = compute_retry_state_update(
        is_ready=False,
        reprocess=True,
        retry_exhausted=False,
        was_previously_ready=True,
        prior_attempt_count=0,
        now_utc=now,
        meter_max_valid_id=120,
        max_attempts=20,
        base_cooldown_minutes=60,
        max_cooldown_minutes=1440,
    )
    assert st_demote.baseline_attempt_count == 1
    assert st_demote.baseline_retry_after == now + timedelta(minutes=60)

    # Becoming ready clears all retry tracking state cleanly
    st_ready = compute_retry_state_update(
        is_ready=True,
        reprocess=True,
        retry_exhausted=False,
        was_previously_ready=False,
        prior_attempt_count=20,
        now_utc=now,
        meter_max_valid_id=120,
        max_attempts=20,
        base_cooldown_minutes=60,
        max_cooldown_minutes=1440,
    )
    assert st_ready.baseline_computed_at == now
    assert st_ready.baseline_attempt_count == 0
    assert st_ready.baseline_retry_after is None
    assert st_ready.baseline_last_attempt_at is None
    assert st_ready.baseline_attempt_max_meter_id is None


def _seed_meter_with_readings(
    db_session: Session,
    *,
    timestamps: list[datetime],
    actual_kw: Decimal = Decimal("120.00"),
    quality_flag: str = QualityFlag.VALID.value,
    source: str = TelemetrySource.METER_FEED.value,
    interval_seconds: int = 900,
) -> tuple[Facility, Meter, list[TelemetryReading]]:
    fac = Facility(
        id="FAC-BASE-1",
        code="B1",
        name="Baseline Plant",
        location="Austin, TX",
        timezone="America/Chicago",
        currency_code="USD",
        contracted_demand_kw=Decimal("1000.00"),
        off_peak_tariff_rate=Decimal("0.0600"),
        mid_peak_tariff_rate=Decimal("0.1100"),
        peak_tariff_rate=Decimal("0.2200"),
    )
    zone = Zone(
        facility_id=fac.id,
        slug="main",
        name="Main Zone",
        primary_meter_code="M-B1",
        share_pct=Decimal("100.00"),
        status=HealthStatus.NOMINAL.value,
    )
    db_session.add_all([fac, zone])
    db_session.flush()

    meter = Meter(
        facility_id=fac.id,
        zone_id=zone.id,
        meter_code="M-B1",
        equipment_name="Main Feeder",
        rated_kw=Decimal("500.00"),
        nominal_interval_seconds=interval_seconds,
        power_factor=Decimal("0.950"),
        thd_pct=Decimal("2.00"),
        status=HealthStatus.NOMINAL.value,
        last_calibrated_at=date(2026, 11, 1),
    )
    db_session.add(meter)
    db_session.flush()

    energy = (actual_kw * Decimal(interval_seconds) / Decimal("3600")).quantize(Decimal("0.0001"))
    rows: list[TelemetryReading] = []
    for ts in timestamps:
        r = TelemetryReading(
            facility_id=fac.id,
            zone_id=zone.id,
            meter_id=meter.id,
            interval_start=ts - timedelta(seconds=interval_seconds),
            recorded_at=ts,
            interval_seconds=interval_seconds,
            actual_kw=actual_kw,
            energy_kwh=energy,
            baseline_status=BaselineStatus.INSUFFICIENT_HISTORY.value,
            power_factor=Decimal("0.950"),
            tariff_period="Peak",
            quality_flag=quality_flag,
            source=source,
        )
        db_session.add(r)
        rows.append(r)
    db_session.flush()
    return fac, meter, rows


def test_db_insufficient_history_wakeup_on_earlier_backfill_and_immutability(
    db_session: Session,
    test_settings: Settings,
) -> None:
    # Seed Day 20 only first -> insufficient_history, baseline_computed_at IS NULL
    day20 = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)
    fac, meter, initial_rows = _seed_meter_with_readings(
        db_session,
        timestamps=[day20],
        actual_kw=Decimal("130.00"),
    )
    target = initial_rows[0]
    original_actual = target.actual_kw
    original_energy = target.energy_kwh
    original_recorded = target.recorded_at

    t0 = datetime(2026, 11, 20, 16, 0, tzinfo=timezone.utc)
    out1 = process_meter_baseline_chunk(
        db_session,
        meter=meter,
        facility=fac,
        settings=test_settings,
        now_utc=t0,
        chunk_limit=50,
        reprocess=False,
        retry_insufficient=False,
        retry_exhausted=False,
    )
    assert out1.baselines_insufficient == 1
    assert target.baseline_computed_at is None
    assert target.baseline_attempt_count == 1
    assert target.baseline_retry_after == t0 + timedelta(minutes=60)

    # Immediate rerun without new earlier data skips it due to cooldown
    out_noop = process_meter_baseline_chunk(
        db_session,
        meter=meter,
        facility=fac,
        settings=test_settings,
        now_utc=t0 + timedelta(minutes=5),
        chunk_limit=50,
        reprocess=False,
        retry_insufficient=False,
        retry_exhausted=False,
    )
    assert len(out_noop.evaluated_items) == 0

    # Backfill 14 earlier days (Days 1..14) BEFORE Day 20
    for d in range(1, 15):
        ts = day20 - timedelta(days=d)
        r = TelemetryReading(
            facility_id=fac.id,
            zone_id=meter.zone_id,
            meter_id=meter.id,
            interval_start=ts - timedelta(seconds=900),
            recorded_at=ts,
            interval_seconds=900,
            actual_kw=Decimal("100.00"),
            energy_kwh=Decimal("25.0000"),
            baseline_status=BaselineStatus.INSUFFICIENT_HISTORY.value,
            power_factor=Decimal("0.950"),
            tariff_period="Peak",
            quality_flag=QualityFlag.VALID.value,
            source=TelemetrySource.CSV_IMPORT.value,
        )
        db_session.add(r)
    db_session.flush()

    # Running incremental reprocess=False immediately wakes up Day 20 via earlier_new_history EXISTS
    out2 = process_meter_baseline_chunk(
        db_session,
        meter=meter,
        facility=fac,
        settings=test_settings,
        now_utc=t0 + timedelta(minutes=10),
        chunk_limit=50,
        reprocess=False,
        retry_insufficient=False,
        retry_exhausted=False,
    )
    assert out2.baselines_ready == 1
    db_session.refresh(target)
    assert target.baseline_status == BaselineStatus.READY.value
    assert target.baseline_kw == Decimal("100.00")
    assert target.baseline_computed_at == t0 + timedelta(minutes=10)
    assert target.baseline_attempt_count == 0
    # Immutability verified
    assert target.actual_kw == original_actual
    assert target.energy_kwh == original_energy
    assert target.recorded_at == original_recorded


def test_db_exhausted_retry_recovery_excludes_non_exhausted_rows(
    db_session: Session,
    test_settings: Settings,
) -> None:
    cfg = test_settings.model_copy(update={"analytics_insufficient_max_attempts": 3})
    day20 = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)
    day21 = datetime(2026, 11, 21, 15, 0, tzinfo=timezone.utc)
    fac, meter, rows = _seed_meter_with_readings(db_session, timestamps=[day20, day21])
    exhausted_row, cooldown_row = rows

    now = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)
    exhausted_row.baseline_attempt_count = 3
    exhausted_row.baseline_last_attempt_at = now - timedelta(hours=5)
    exhausted_row.baseline_retry_after = None

    cooldown_row.baseline_attempt_count = 1
    cooldown_row.baseline_last_attempt_at = now - timedelta(minutes=5)
    cooldown_row.baseline_retry_after = now + timedelta(minutes=55)
    db_session.flush()

    # Run retry_exhausted=True without enough history yet -> ONLY exhausted_row resets; cooldown_row untouched
    out = process_meter_baseline_chunk(
        db_session,
        meter=meter,
        facility=fac,
        settings=cfg,
        now_utc=now,
        chunk_limit=50,
        reprocess=False,
        retry_insufficient=False,
        retry_exhausted=True,
    )
    assert [item.reading.id for item in out.evaluated_items] == [exhausted_row.id]
    assert exhausted_row.baseline_attempt_count == 1
    assert exhausted_row.baseline_retry_after == now + timedelta(minutes=60)
    assert cooldown_row.baseline_attempt_count == 1
    assert cooldown_row.baseline_retry_after == now + timedelta(minutes=55)
