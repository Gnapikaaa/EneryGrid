from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.constants import (
    AnomalySeverity,
    AnomalyStatus,
    BaselineStatus,
    CostEstimateStatus,
    Environment,
    HealthStatus,
    QualityFlag,
    TariffPeriod,
    TelemetrySource,
    UserRole,
)
from app.models.anomaly import Anomaly, AnomalyWorkflowLog
from app.models.facility import Facility, Meter, Zone
from app.models.telemetry import TelemetryReading
from app.models.user import User
from app.services import anomalies as anomaly_service
from app.services.anomalies import (
    ExistingAnomalySnapshot,
    build_reconciliation_plan,
    classify_anomaly_severity,
    evaluate_reading_anomaly_metrics,
)
from app.services.exceptions import ConflictError, PermissionDeniedError


def _unit_settings() -> Settings:
    # _env_file=None prevents pydantic-settings from loading the project .env
    # file, which contains ALLOWED_ORIGINS as a comma-separated string that
    # pydantic-settings cannot JSON-parse.  Explicit field values are still
    # accepted via kwargs.
    return Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url="postgresql+psycopg://postgres:pass@localhost:5432/test",
    )


def test_anomaly_positive_only_severity_and_deviation_bounds() -> None:
    s = _unit_settings()
    assert classify_anomaly_severity(Decimal("1.99"), s) is None
    assert classify_anomaly_severity(Decimal("2.00"), s) == AnomalySeverity.ELEVATED
    assert classify_anomaly_severity(Decimal("2.60"), s) == AnomalySeverity.HIGH
    assert classify_anomaly_severity(Decimal("3.40"), s) == AnomalySeverity.CRITICAL

    # Negative drop (high magnitude negative z-score) must never trigger positive-only anomaly
    neg = evaluate_reading_anomaly_metrics(
        actual_kw=Decimal("10.00"),
        interval_seconds=900,
        tariff_period=TariffPeriod.PEAK.value,
        quality_flag=QualityFlag.VALID.value,
        source=TelemetrySource.METER_FEED.value,
        baseline_status=BaselineStatus.READY,
        baseline_kw=Decimal("100.00"),
        raw_mean_kw=Decimal("100.00"),
        z_score=Decimal("-5.00"),
        applicable_rate=Decimal("0.2000"),
        meter_code="M-1",
        equipment_name="Compressor",
        settings=s,
    )
    assert neg is None

    # Small excess_kw (< 2.00 kW) suppressed even with elevated z_score
    tiny = evaluate_reading_anomaly_metrics(
        actual_kw=Decimal("11.50"),
        interval_seconds=900,
        tariff_period=TariffPeriod.PEAK.value,
        quality_flag=QualityFlag.VALID.value,
        source=TelemetrySource.METER_FEED.value,
        baseline_status=BaselineStatus.READY,
        baseline_kw=Decimal("10.00"),
        raw_mean_kw=Decimal("10.00"),
        z_score=Decimal("2.50"),
        applicable_rate=Decimal("0.2000"),
        meter_code="M-1",
        equipment_name="Compressor",
        settings=s,
    )
    assert tiny is None

    # Simulated reading never creates anomalies
    sim = evaluate_reading_anomaly_metrics(
        actual_kw=Decimal("250.00"),
        interval_seconds=900,
        tariff_period=TariffPeriod.PEAK.value,
        quality_flag=QualityFlag.VALID.value,
        source=TelemetrySource.SIMULATION.value,
        baseline_status=BaselineStatus.READY,
        baseline_kw=Decimal("100.00"),
        raw_mean_kw=Decimal("100.00"),
        z_score=Decimal("5.00"),
        applicable_rate=Decimal("0.2000"),
        meter_code="M-1",
        equipment_name="Compressor",
        settings=s,
    )
    assert sim is None


def test_anomaly_genuine_zero_tariff_vs_unavailable_tariff() -> None:
    s = _unit_settings()

    # Genuine $0.0000/kWh tariff -> status='available', estimated_cost=0.00
    zero_tariff = evaluate_reading_anomaly_metrics(
        actual_kw=Decimal("140.00"),
        interval_seconds=900,
        tariff_period=TariffPeriod.OFF_PEAK.value,
        quality_flag=QualityFlag.VALID.value,
        source=TelemetrySource.METER_FEED.value,
        baseline_status=BaselineStatus.READY,
        baseline_kw=Decimal("100.00"),
        raw_mean_kw=Decimal("100.00"),
        z_score=Decimal("3.00"),
        applicable_rate=Decimal("0.0000"),
        meter_code="M-1",
        equipment_name="Chiller",
        settings=s,
    )
    assert zero_tariff is not None
    assert zero_tariff.estimated_waste_kwh == Decimal("10.00")
    assert zero_tariff.cost_estimate_status == CostEstimateStatus.AVAILABLE
    assert zero_tariff.estimated_cost == Decimal("0.00")

    # Unavailable (None) tariff -> status='unavailable_tariff', estimated_cost=None
    missing_tariff = evaluate_reading_anomaly_metrics(
        actual_kw=Decimal("140.00"),
        interval_seconds=900,
        tariff_period=TariffPeriod.OFF_PEAK.value,
        quality_flag=QualityFlag.VALID.value,
        source=TelemetrySource.METER_FEED.value,
        baseline_status=BaselineStatus.READY,
        baseline_kw=Decimal("100.00"),
        raw_mean_kw=Decimal("100.00"),
        z_score=Decimal("3.00"),
        applicable_rate=None,
        meter_code="M-1",
        equipment_name="Chiller",
        settings=s,
    )
    assert missing_tariff is not None
    assert missing_tariff.estimated_waste_kwh == Decimal("10.00")
    assert missing_tariff.cost_estimate_status == CostEstimateStatus.UNAVAILABLE_TARIFF
    assert missing_tariff.estimated_cost is None

    # Zero baseline finite deviation_pct convention = 100.00%
    zero_base = evaluate_reading_anomaly_metrics(
        actual_kw=Decimal("8.00"),
        interval_seconds=1800,
        tariff_period=TariffPeriod.PEAK.value,
        quality_flag=QualityFlag.VALID.value,
        source=TelemetrySource.METER_FEED.value,
        baseline_status=BaselineStatus.READY,
        baseline_kw=Decimal("0.00"),
        raw_mean_kw=Decimal("0.00"),
        z_score=Decimal("8.00"),
        applicable_rate=Decimal("0.2500"),
        meter_code="M-1",
        equipment_name="Chiller",
        settings=s,
    )
    assert zero_base is not None
    assert zero_base.deviation_pct == Decimal("100.00")
    assert zero_base.estimated_waste_kwh == Decimal("4.00")
    assert zero_base.estimated_cost == Decimal("1.00")


def test_anomaly_reprocessing_reconciliation_preserves_human_states_and_is_idempotent() -> None:
    snap_open = ExistingAnomalySnapshot(
        status=AnomalyStatus.OPEN,
        severity=AnomalySeverity.ELEVATED,
        z_score=Decimal("2.30"),
        expected_kw=Decimal("100.00"),
        deviation_pct=Decimal("20.00"),
        estimated_waste_kwh=Decimal("5.00"),
        estimated_cost=Decimal("1.00"),
        cost_estimate_status=CostEstimateStatus.AVAILABLE,
        waveform=[120.0],
        baseline_waveform=[100.0],
    )
    plan_open_drop = build_reconciliation_plan(
        existing=snap_open,
        metrics=None,
        actual_kw=Decimal("120.00"),
        interval_seconds=900,
        fallback_baseline_kw=Decimal("115.00"),
        fallback_raw_mean_kw=Decimal("115.00"),
        fallback_z_score=Decimal("1.10"),
        applicable_rate=Decimal("0.2000"),
        new_waveform=[120.0],
        new_baseline_waveform=[115.0],
    )
    assert plan_open_drop.new_status == AnomalyStatus.RESOLVED
    assert plan_open_drop.log_from_status == AnomalyStatus.OPEN
    assert plan_open_drop.log_to_status == AnomalyStatus.RESOLVED

    # Acknowledged anomaly falling below threshold keeps ACKNOWLEDGED and emits one same-status audit log
    snap_ack = ExistingAnomalySnapshot(
        status=AnomalyStatus.ACKNOWLEDGED,
        severity=AnomalySeverity.HIGH,
        z_score=Decimal("2.80"),
        expected_kw=Decimal("100.00"),
        deviation_pct=Decimal("30.00"),
        estimated_waste_kwh=Decimal("7.50"),
        estimated_cost=Decimal("1.50"),
        cost_estimate_status=CostEstimateStatus.AVAILABLE,
        waveform=[130.0],
        baseline_waveform=[100.0],
    )
    plan_ack = build_reconciliation_plan(
        existing=snap_ack,
        metrics=None,
        actual_kw=Decimal("130.00"),
        interval_seconds=900,
        fallback_baseline_kw=Decimal("122.00"),
        fallback_raw_mean_kw=Decimal("122.00"),
        fallback_z_score=Decimal("1.60"),
        applicable_rate=Decimal("0.2000"),
        new_waveform=[130.0],
        new_baseline_waveform=[100.0],
    )
    assert plan_ack.should_update is True
    assert plan_ack.new_status == AnomalyStatus.ACKNOWLEDGED
    assert plan_ack.log_from_status == AnomalyStatus.ACKNOWLEDGED
    assert plan_ack.log_to_status == AnomalyStatus.ACKNOWLEDGED

    # Second run with identical recalculated metrics -> should_update=False, zero logs (idempotent)
    snap_ack_updated = ExistingAnomalySnapshot(
        status=AnomalyStatus.ACKNOWLEDGED,
        severity=AnomalySeverity.HIGH,
        z_score=plan_ack.new_z_score,
        expected_kw=plan_ack.new_expected_kw,
        deviation_pct=plan_ack.new_deviation_pct,
        estimated_waste_kwh=plan_ack.new_estimated_waste_kwh,
        estimated_cost=plan_ack.new_estimated_cost,
        cost_estimate_status=plan_ack.new_cost_estimate_status,
        waveform=[130.0],
        baseline_waveform=[100.0],
    )
    plan_ack_repeat = build_reconciliation_plan(
        existing=snap_ack_updated,
        metrics=None,
        actual_kw=Decimal("130.00"),
        interval_seconds=900,
        fallback_baseline_kw=Decimal("122.00"),
        fallback_raw_mean_kw=Decimal("122.00"),
        fallback_z_score=Decimal("1.60"),
        applicable_rate=Decimal("0.2000"),
        new_waveform=[130.0],
        new_baseline_waveform=[100.0],
    )
    assert plan_ack_repeat.should_update is False
    assert plan_ack_repeat.log_to_status is None


def test_db_anomaly_workflow_transitions_audit_logs_and_permissions(
    db_session: Session,
) -> None:
    eng = User(
        email="eng@energygrid.test",
        full_name="Utility Engineer",
        password_hash="hash",
        role=UserRole.UTILITY_ENGINEER.value,
        is_active=True,
    )
    fm = User(
        email="fm@energygrid.test",
        full_name="Facility Manager",
        password_hash="hash",
        role=UserRole.FACILITY_MANAGER.value,
        is_active=True,
    )
    inactive_user = User(
        email="inactive@energygrid.test",
        full_name="Inactive User",
        password_hash="hash",
        role=UserRole.UTILITY_ENGINEER.value,
        is_active=False,
    )
    db_session.add_all([eng, fm, inactive_user])

    fac = Facility(
        id="FAC-ANOM",
        code="AN1",
        name="Anomaly Plant",
        location="Chicago, IL",
        timezone="UTC",
        currency_code="USD",
        contracted_demand_kw=Decimal("500.00"),
        off_peak_tariff_rate=Decimal("0.0500"),
        mid_peak_tariff_rate=Decimal("0.1000"),
        peak_tariff_rate=Decimal("0.2000"),
    )
    zone = Zone(
        facility_id=fac.id,
        slug="z1",
        name="Z1",
        primary_meter_code="M-AN1",
        share_pct=Decimal("100.00"),
        status=HealthStatus.NOMINAL.value,
    )
    db_session.add_all([fac, zone])
    db_session.flush()

    meter = Meter(
        facility_id=fac.id,
        zone_id=zone.id,
        meter_code="M-AN1",
        equipment_name="Air Handler",
        rated_kw=Decimal("200.00"),
        power_factor=Decimal("0.940"),
        thd_pct=Decimal("2.00"),
        status=HealthStatus.NOMINAL.value,
        last_calibrated_at=date(2026, 11, 1),
    )
    db_session.add(meter)
    db_session.flush()

    t = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    r = TelemetryReading(
        facility_id=fac.id,
        zone_id=zone.id,
        meter_id=meter.id,
        interval_start=t - timedelta(seconds=900),
        recorded_at=t,
        interval_seconds=900,
        actual_kw=Decimal("180.00"),
        energy_kwh=Decimal("45.0000"),
        baseline_kw=Decimal("100.00"),
        std_dev_kw=Decimal("10.00"),
        z_score=Decimal("8.00"),
        baseline_status=BaselineStatus.READY.value,
        power_factor=Decimal("0.940"),
        tariff_period=TariffPeriod.PEAK.value,
    )
    db_session.add(r)
    db_session.flush()

    anomaly = Anomaly(
        event_code=f"EG-{r.id}",
        facility_id=fac.id,
        zone_id=zone.id,
        meter_id=meter.id,
        reading_id=r.id,
        detected_at=t,
        severity=AnomalySeverity.CRITICAL.value,
        status=AnomalyStatus.OPEN.value,
        z_score=Decimal("8.00"),
        actual_kw=Decimal("180.00"),
        expected_kw=Decimal("100.00"),
        deviation_pct=Decimal("80.00"),
        duration_min=15,
        estimated_waste_kwh=Decimal("20.00"),
        estimated_cost=Decimal("4.00"),
        cost_estimate_status=CostEstimateStatus.AVAILABLE.value,
        signature="Spike",
        recommendation="Check",
        waveform=[180.0],
        baseline_waveform=[100.0],
    )
    db_session.add(anomaly)
    db_session.commit()

    # Facility manager strictly read-only
    with pytest.raises(PermissionDeniedError):
        anomaly_service.acknowledge_anomaly(db_session, actor=fm, anomaly_id=anomaly.id)

    # Full lifecycle: Open -> Acknowledged -> Assigned (defaults to actor) -> Resolved -> Open
    ack = anomaly_service.acknowledge_anomaly(db_session, actor=eng, anomaly_id=anomaly.id, note="Seen")
    assert ack.status == AnomalyStatus.ACKNOWLEDGED

    with pytest.raises(ConflictError):
        anomaly_service.investigate_anomaly(
            db_session, actor=eng, anomaly_id=anomaly.id, assigned_to_user_id=inactive_user.id
        )

    assigned = anomaly_service.investigate_anomaly(
        db_session, actor=eng, anomaly_id=anomaly.id, note="Checking breaker"
    )
    assert assigned.status == AnomalyStatus.ASSIGNED
    assert assigned.assigned_to_user_id == eng.id

    resolved = anomaly_service.resolve_anomaly(
        db_session, actor=eng, anomaly_id=anomaly.id, note="Fixed valve"
    )
    assert resolved.status == AnomalyStatus.RESOLVED

    with pytest.raises(ConflictError):
        anomaly_service.acknowledge_anomaly(db_session, actor=eng, anomaly_id=anomaly.id)

    reopened = anomaly_service.reopen_anomaly(
        db_session, actor=eng, anomaly_id=anomaly.id, note="Spike returned"
    )
    assert reopened.status == AnomalyStatus.OPEN
    assert reopened.assigned_to_user_id is None

    history = anomaly_service.get_anomaly_history(db_session, actor=fm, anomaly_id=anomaly.id)
    assert [(h.from_status, h.to_status) for h in history] == [
        (AnomalyStatus.OPEN, AnomalyStatus.ACKNOWLEDGED),
        (AnomalyStatus.ACKNOWLEDGED, AnomalyStatus.ASSIGNED),
        (AnomalyStatus.ASSIGNED, AnomalyStatus.RESOLVED),
        (AnomalyStatus.RESOLVED, AnomalyStatus.OPEN),
    ]


# ---------------------------------------------------------------------------
# Regression: waveform propagation through build_reconciliation_plan
# ---------------------------------------------------------------------------

def test_reconciliation_plan_waveform_propagation() -> None:
    """new_waveform and new_baseline_waveform must be stored on the returned plan."""
    snap = ExistingAnomalySnapshot(
        status=AnomalyStatus.OPEN,
        severity=AnomalySeverity.HIGH,
        z_score=Decimal("3.00"),
        expected_kw=Decimal("100.00"),
        deviation_pct=Decimal("40.00"),
        estimated_waste_kwh=Decimal("10.00"),
        estimated_cost=Decimal("2.00"),
        cost_estimate_status=CostEstimateStatus.AVAILABLE,
        waveform=[140.0, 141.0],
        baseline_waveform=[100.0, 100.0],
    )
    new_w = [150.0, 152.0]
    new_bw = [100.0, 101.0]
    plan = build_reconciliation_plan(
        existing=snap,
        metrics=None,
        actual_kw=Decimal("140.00"),
        interval_seconds=900,
        fallback_baseline_kw=Decimal("95.00"),  # still anomalous → OPEN stays
        fallback_raw_mean_kw=Decimal("95.00"),
        fallback_z_score=Decimal("3.20"),
        applicable_rate=Decimal("0.15"),
        new_waveform=new_w,
        new_baseline_waveform=new_bw,
    )
    assert plan.new_waveform == new_w
    assert plan.new_baseline_waveform == new_bw


def test_reconciliation_plan_waveform_change_triggers_update() -> None:
    """When only waveform arrays change, should_update must be True."""
    snap = ExistingAnomalySnapshot(
        status=AnomalyStatus.OPEN,
        severity=AnomalySeverity.HIGH,
        z_score=Decimal("3.00"),
        expected_kw=Decimal("100.00"),
        deviation_pct=Decimal("40.00"),
        estimated_waste_kwh=Decimal("10.00"),
        estimated_cost=Decimal("2.00"),
        cost_estimate_status=CostEstimateStatus.AVAILABLE,
        waveform=[140.0],
        baseline_waveform=[100.0],
    )
    # Pass same numeric metrics but different waveform
    plan = build_reconciliation_plan(
        existing=snap,
        metrics=None,
        actual_kw=Decimal("140.00"),
        interval_seconds=900,
        fallback_baseline_kw=Decimal("95.00"),
        fallback_raw_mean_kw=Decimal("95.00"),
        fallback_z_score=Decimal("3.00"),
        applicable_rate=None,
        new_waveform=[140.0, 141.0],      # changed
        new_baseline_waveform=[100.0],
    )
    assert plan.should_update is True


def test_reconciliation_plan_identical_waveform_no_update() -> None:
    """Idempotency: passing identical waveforms and metrics to ACKNOWLEDGED anomaly must not force an update.

    The snapshot must hold the values that build_reconciliation_plan actually computes
    from the given fallback inputs, otherwise the numeric fields alone cause should_update=True.

    With actual_kw=140, raw_mean=95:
      deviation_pct = round((140-95)/95 * 100, 2) = 47.37
      waste_kwh     = round((140-95) * 900 / 3600, 2) = 11.25
      expected_kw   = fallback_baseline_kw = 95.00
      z_score       = clamp(3.00) = 3.00
      cost          = None (applicable_rate=None → UNAVAILABLE_TARIFF)
    """
    wf = [140.0, 141.0]
    bwf = [100.0, 100.5]
    snap = ExistingAnomalySnapshot(
        status=AnomalyStatus.ACKNOWLEDGED,
        severity=AnomalySeverity.HIGH,
        z_score=Decimal("3.00"),
        expected_kw=Decimal("95.00"),        # = fallback_baseline_kw
        deviation_pct=Decimal("47.37"),      # = (140-95)/95*100 rounded to 2dp
        estimated_waste_kwh=Decimal("11.25"),  # = (140-95)*900/3600 rounded to 2dp
        estimated_cost=None,
        cost_estimate_status=CostEstimateStatus.UNAVAILABLE_TARIFF,
        waveform=wf,
        baseline_waveform=bwf,
    )
    plan = build_reconciliation_plan(
        existing=snap,
        metrics=None,
        actual_kw=Decimal("140.00"),
        interval_seconds=900,
        fallback_baseline_kw=Decimal("95.00"),
        fallback_raw_mean_kw=Decimal("95.00"),
        fallback_z_score=Decimal("3.00"),
        applicable_rate=None,
        new_waveform=list(wf),          # identical copy
        new_baseline_waveform=list(bwf),
    )
    # Nothing changed: no update needed
    assert plan.should_update is False
    assert plan.new_status == AnomalyStatus.ACKNOWLEDGED


# ---------------------------------------------------------------------------
# Regression: anomaly assignment role restriction (Defect #7)
# ---------------------------------------------------------------------------

def test_investigate_anomaly_rejects_facility_manager_assignee(
    db_session: Session,
) -> None:
    """Facility managers must not be assignable as anomaly investigators."""
    import uuid as _uuid
    from decimal import Decimal as _Decimal

    from app.models.facility import Facility, Meter, Zone
    from app.models.anomaly import Anomaly
    from app.core.constants import (
        AnomalySeverity,
        AnomalyStatus,
        BaselineStatus,
        CostEstimateStatus,
        Environment,
        HealthStatus,
        QualityFlag,
        TariffPeriod,
        TelemetrySource,
    )

    # Minimal facility/zone/meter
    fac = Facility(
        id="role-test",
        code="TST-RR01",
        name="Role Test Plant",
        location="Test",
        timezone="UTC",
        is_active=True,
        health_status=HealthStatus.NOMINAL.value,
        contracted_demand_kw=_Decimal("100"),
        currency_code="USD",
        peak_tariff_rate=_Decimal("0.20"),
        mid_peak_tariff_rate=_Decimal("0.15"),
        off_peak_tariff_rate=_Decimal("0.10"),
    )
    zone = Zone(
        facility_id=fac.id,
        name="Z1",
        code="Z1",
        is_active=True,
        health_status=HealthStatus.NOMINAL.value,
    )
    db_session.add_all([fac, zone])
    db_session.flush()
    meter = Meter(
        facility_id=fac.id,
        zone_id=zone.id,
        code="MTR-RR01",
        equipment_name="Role Test Meter",
        is_active=True,
        health_status=HealthStatus.NOMINAL.value,
        manufacturer="X",
        model="Y",
        installed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(meter)
    db_session.flush()

    eng = User(
        email="eng.rr@energygrid.test",
        full_name="Engineer RR",
        password_hash="hash",
        role=UserRole.UTILITY_ENGINEER.value,
        is_active=True,
    )
    fm_user = User(
        email="fm.rr@energygrid.test",
        full_name="Facility Mgr RR",
        password_hash="hash",
        role=UserRole.FACILITY_MANAGER.value,
        is_active=True,
    )
    db_session.add_all([eng, fm_user])
    db_session.flush()

    anomaly = Anomaly(
        event_code="EVT-RR-001",
        facility_id=fac.id,
        zone_id=zone.id,
        meter_id=meter.id,
        detected_at=datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc),
        severity=AnomalySeverity.HIGH.value,
        status=AnomalyStatus.ACKNOWLEDGED.value,
        z_score=_Decimal("3.0"),
        actual_kw=_Decimal("150.0"),
        expected_kw=_Decimal("100.0"),
        deviation_pct=_Decimal("50.0"),
        duration_min=15,
        estimated_waste_kwh=_Decimal("3.0"),
        estimated_cost=None,
        cost_estimate_status=CostEstimateStatus.UNAVAILABLE_TARIFF.value,
        signature="sig",
        recommendation="Check it",
        waveform=[150.0],
        baseline_waveform=[100.0],
    )
    db_session.add(anomaly)
    db_session.flush()

    import pytest as _pytest
    with _pytest.raises(ConflictError, match="role"):
        anomaly_service.investigate_anomaly(
            db_session,
            actor=eng,
            anomaly_id=anomaly.id,
            assigned_to_user_id=fm_user.id,
        )
