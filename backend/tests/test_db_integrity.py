from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import (
    AnomalySeverity,
    AnomalyStatus,
    BaselineStatus,
    CostEstimateStatus,
    HealthStatus,
    InsightCategory,
    InsightPriority,
    InsightRuleCode,
    InsightSavingsBasis,
    InsightStatus,
    TariffPeriod,
    UserRole,
)
from app.models import (
    Anomaly,
    AnomalyWorkflowLog,
    EnergyInsight,
    Facility,
    InsightWorkflowLog,
    Meter,
    MeterCalibrationAudit,
    TelemetryReading,
    User,
    Zone,
)


def _create_facility_zone_meter(
    db: Session,
    *,
    facility_id: str = "fac-pune-01",
    facility_code: str = "PNQ-01",
    currency_code: str = "INR",
    zone_slug: str = "hvac",
    meter_code: str = "MTR-HVAC-01",
) -> tuple[Facility, Zone, Meter]:
    facility = Facility(
        id=facility_id,
        code=facility_code,
        name=f"Facility {facility_code}",
        location="Pune, India",
        timezone="Asia/Kolkata",
        currency_code=currency_code,
        contracted_demand_kw=Decimal("1200.00"),
        off_peak_tariff_rate=Decimal("6.2000"),
        mid_peak_tariff_rate=Decimal("8.4000"),
        peak_tariff_rate=Decimal("11.5000"),
    )
    zone = Zone(
        id=uuid.uuid4(),
        facility_id=facility.id,
        slug=zone_slug,
        name="HVAC & Cooling",
        primary_meter_code=meter_code,
        share_pct=Decimal("32.50"),
        status=HealthStatus.NOMINAL.value,
    )
    meter = Meter(
        id=uuid.uuid4(),
        facility_id=facility.id,
        zone_id=zone.id,
        meter_code=meter_code,
        equipment_name="Chiller Plant 1",
        rated_kw=Decimal("400.00"),
        nominal_interval_seconds=900,
        current_kw=Decimal("245.50"),
        power_factor=Decimal("0.960"),
        thd_pct=Decimal("2.40"),
        status=HealthStatus.NOMINAL.value,
        last_calibrated_at=date(2026, 9, 15),
    )
    db.add_all([facility, zone, meter])
    db.commit()
    return facility, zone, meter


def test_facility_enforces_explicit_iso4217_currency_at_orm_and_db(db_session: Session) -> None:
    with pytest.raises(ValueError, match="Unsupported currency code"):
        Facility(
            id="fac-bad",
            code="BAD-01",
            name="Invalid Currency Facility",
            location="Nowhere",
            timezone="UTC",
            currency_code="XYZ",
            contracted_demand_kw=Decimal("500.00"),
            off_peak_tariff_rate=Decimal("5.0000"),
            mid_peak_tariff_rate=Decimal("7.0000"),
            peak_tariff_rate=Decimal("9.0000"),
        )

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO facilities (
                    id, code, name, location, timezone, currency_code,
                    contracted_demand_kw, off_peak_tariff_rate, mid_peak_tariff_rate, peak_tariff_rate
                ) VALUES (
                    'fac-sql-bad', 'SQL-BAD', 'SQL Bad', 'Nowhere', 'UTC', 'ZZZ',
                    500.00, 5.0, 7.0, 9.0
                )
                """
            )
        )
        db_session.commit()
    db_session.rollback()

    facility, _, _ = _create_facility_zone_meter(db_session, currency_code="INR")
    assert facility.currency_code == "INR"


def test_composite_fk_prevents_cross_facility_zone_meter_mismatch(db_session: Session) -> None:
    fac1, zone1, _ = _create_facility_zone_meter(
        db_session,
        facility_id="fac-1",
        facility_code="F-01",
        zone_slug="zone-1",
        meter_code="MTR-01",
    )
    fac2, _, _ = _create_facility_zone_meter(
        db_session,
        facility_id="fac-2",
        facility_code="F-02",
        zone_slug="zone-2",
        meter_code="MTR-02",
    )

    mismatched_meter = Meter(
        facility_id=fac2.id,
        zone_id=zone1.id,  # belongs to fac1, not fac2
        meter_code="MTR-MISMATCH",
        equipment_name="Cross-Facility Invalid Meter",
        rated_kw=Decimal("100.00"),
        power_factor=Decimal("0.950"),
        thd_pct=Decimal("1.50"),
        status=HealthStatus.NOMINAL.value,
        last_calibrated_at=date(2026, 10, 1),
    )
    db_session.add(mismatched_meter)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Mismatched telemetry facility_id against meter's facility_id also fails
    _, _, meter1 = _create_facility_zone_meter(
        db_session,
        facility_id="fac-3",
        facility_code="F-03",
        zone_slug="zone-3",
        meter_code="MTR-03",
    )
    t_end = datetime(2026, 11, 1, 9, 15, tzinfo=UTC)
    t_start = t_end - timedelta(seconds=900)
    bad_telemetry = TelemetryReading(
        facility_id=fac1.id,  # mismatch with meter1 (fac-3)
        zone_id=meter1.zone_id,
        meter_id=meter1.id,
        interval_start=t_start,
        recorded_at=t_end,
        interval_seconds=900,
        actual_kw=Decimal("120.00"),
        energy_kwh=Decimal("30.0000"),
        baseline_status=BaselineStatus.INSUFFICIENT_HISTORY.value,
        power_factor=Decimal("0.950"),
        tariff_period=TariffPeriod.MID_PEAK.value,
    )
    db_session.add(bad_telemetry)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_telemetry_interval_bounds_and_gist_overlap_exclusion(db_session: Session) -> None:
    facility, zone, meter = _create_facility_zone_meter(db_session)

    r1_start = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    r1_end = datetime(2026, 11, 1, 9, 15, tzinfo=UTC)
    r2_start = datetime(2026, 11, 1, 9, 15, tzinfo=UTC)
    r2_end = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)

    # Adjacent half-open intervals [09:00, 09:15) and [09:15, 09:30) are valid
    reading1 = TelemetryReading(
        facility_id=facility.id,
        zone_id=zone.id,
        meter_id=meter.id,
        interval_start=r1_start,
        recorded_at=r1_end,
        interval_seconds=900,
        actual_kw=Decimal("200.00"),
        energy_kwh=Decimal("50.0000"),
        baseline_status=BaselineStatus.INSUFFICIENT_HISTORY.value,
        power_factor=Decimal("0.960"),
        tariff_period=TariffPeriod.PEAK.value,
    )
    reading2 = TelemetryReading(
        facility_id=facility.id,
        zone_id=zone.id,
        meter_id=meter.id,
        interval_start=r2_start,
        recorded_at=r2_end,
        interval_seconds=900,
        actual_kw=Decimal("220.00"),
        energy_kwh=Decimal("55.0000"),
        baseline_status=BaselineStatus.INSUFFICIENT_HISTORY.value,
        power_factor=Decimal("0.960"),
        tariff_period=TariffPeriod.PEAK.value,
    )
    db_session.add_all([reading1, reading2])
    db_session.commit()

    # Overlapping [09:10, 09:25) on same meter must fail GiST exclusion constraint
    overlap = TelemetryReading(
        facility_id=facility.id,
        zone_id=zone.id,
        meter_id=meter.id,
        interval_start=datetime(2026, 11, 1, 9, 10, tzinfo=UTC),
        recorded_at=datetime(2026, 11, 1, 9, 25, tzinfo=UTC),
        interval_seconds=900,
        actual_kw=Decimal("210.00"),
        energy_kwh=Decimal("52.5000"),
        baseline_status=BaselineStatus.INSUFFICIENT_HISTORY.value,
        power_factor=Decimal("0.960"),
        tariff_period=TariffPeriod.PEAK.value,
    )
    db_session.add(overlap)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Mismatched interval_start vs interval_seconds must fail check constraint
    bad_bounds = TelemetryReading(
        facility_id=facility.id,
        zone_id=zone.id,
        meter_id=meter.id,
        interval_start=datetime(2026, 11, 1, 9, 30, tzinfo=UTC),
        recorded_at=datetime(2026, 11, 1, 9, 45, tzinfo=UTC),
        interval_seconds=600,  # does not match 15 minutes
        actual_kw=Decimal("210.00"),
        energy_kwh=Decimal("35.0000"),
        baseline_status=BaselineStatus.INSUFFICIENT_HISTORY.value,
        power_factor=Decimal("0.960"),
        tariff_period=TariffPeriod.PEAK.value,
    )
    db_session.add(bad_bounds)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_meter_soft_deactivation_and_hard_delete_restriction(db_session: Session) -> None:
    facility, zone, meter = _create_facility_zone_meter(db_session)
    audit = MeterCalibrationAudit(
        meter_id=meter.id,
        audited_on=date(2026, 11, 1),
        notes="Quarterly clamp and CT verification",
    )
    db_session.add(audit)
    db_session.commit()

    # Deactivation without timestamp violates consistent_deactivation_state
    meter.is_active = False
    meter.deactivated_at = None
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Proper soft deactivation preserves history
    meter.is_active = False
    meter.deactivated_at = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    db_session.commit()

    refreshed_meter = db_session.get(Meter, meter.id)
    assert refreshed_meter is not None
    assert refreshed_meter.is_active is False
    assert refreshed_meter.deactivated_at is not None

    # Hard deleting a meter with calibration audits / telemetry is blocked (ON DELETE RESTRICT)
    db_session.delete(refreshed_meter)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    assert zone.id == refreshed_meter.zone_id
    assert facility.id == refreshed_meter.facility_id


def test_anomaly_column_scoped_set_null_and_workflow_logs(db_session: Session) -> None:
    facility, zone, meter = _create_facility_zone_meter(db_session)
    user = User(
        email="engineer@energygrid.local",
        full_name="Aarav Mehta",
        password_hash="argon2id$stubhash",
        role=UserRole.UTILITY_ENGINEER.value,
    )
    db_session.add(user)
    db_session.flush()

    reading = TelemetryReading(
        facility_id=facility.id,
        zone_id=zone.id,
        meter_id=meter.id,
        interval_start=datetime(2026, 11, 1, 10, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 11, 1, 10, 15, tzinfo=UTC),
        interval_seconds=900,
        actual_kw=Decimal("380.00"),
        energy_kwh=Decimal("95.0000"),
        baseline_kw=Decimal("220.00"),
        std_dev_kw=Decimal("20.00"),
        z_score=Decimal("8.00"),
        baseline_status=BaselineStatus.READY.value,
        power_factor=Decimal("0.910"),
        tariff_period=TariffPeriod.PEAK.value,
    )
    db_session.add(reading)
    db_session.flush()

    # Assigned status without user violates ck_anomalies_assigned_requires_user
    bad_anomaly = Anomaly(
        event_code="EVT-BAD-01",
        facility_id=facility.id,
        zone_id=zone.id,
        meter_id=meter.id,
        reading_id=reading.id,
        detected_at=reading.recorded_at,
        severity=AnomalySeverity.CRITICAL.value,
        status=AnomalyStatus.ASSIGNED.value,
        z_score=Decimal("8.00"),
        actual_kw=Decimal("380.00"),
        expected_kw=Decimal("220.00"),
        deviation_pct=Decimal("72.73"),
        duration_min=15,
        estimated_waste_kwh=Decimal("40.00"),
        estimated_cost=Decimal("460.00"),
        signature="Sustained chiller surge",
        recommendation="Inspect VFD pressure setpoint",
        waveform=[220.0, 380.0],
        baseline_waveform=[220.0, 220.0],
        assigned_to_user_id=None,
    )
    db_session.add(bad_anomaly)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Re-seed uncommitted user + reading after rollback (facility/zone/meter already committed)
    user = User(
        email="engineer@energygrid.local",
        full_name="Aarav Mehta",
        password_hash="argon2id$stubhash",
        role=UserRole.UTILITY_ENGINEER.value,
    )
    db_session.add(user)
    db_session.flush()

    reading = TelemetryReading(
        facility_id=facility.id,
        zone_id=zone.id,
        meter_id=meter.id,
        interval_start=datetime(2026, 11, 1, 10, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 11, 1, 10, 15, tzinfo=UTC),
        interval_seconds=900,
        actual_kw=Decimal("380.00"),
        energy_kwh=Decimal("95.0000"),
        baseline_kw=Decimal("220.00"),
        std_dev_kw=Decimal("20.00"),
        z_score=Decimal("8.00"),
        baseline_status=BaselineStatus.READY.value,
        power_factor=Decimal("0.910"),
        tariff_period=TariffPeriod.PEAK.value,
    )
    db_session.add(reading)
    db_session.flush()

    anomaly = Anomaly(
        event_code="EVT-001",
        facility_id=facility.id,
        zone_id=zone.id,
        meter_id=meter.id,
        reading_id=reading.id,
        detected_at=reading.recorded_at,
        severity=AnomalySeverity.CRITICAL.value,
        status=AnomalyStatus.ASSIGNED.value,
        z_score=Decimal("8.00"),
        actual_kw=Decimal("380.00"),
        expected_kw=Decimal("220.00"),
        deviation_pct=Decimal("72.73"),
        duration_min=15,
        estimated_waste_kwh=Decimal("40.00"),
        estimated_cost=Decimal("460.00"),
        signature="Sustained chiller surge",
        recommendation="Inspect VFD pressure setpoint",
        waveform=[220.0, 380.0],
        baseline_waveform=[220.0, 220.0],
        assigned_to_user_id=user.id,
    )
    db_session.add(anomaly)
    db_session.flush()

    anomaly_log = AnomalyWorkflowLog(
        anomaly_id=anomaly.id,
        from_status=AnomalyStatus.OPEN.value,
        to_status=AnomalyStatus.ASSIGNED.value,
        to_assignee_id=user.id,
        changed_by_user_id=user.id,
        note="Assigned to cooling reliability engineer",
    )
    insight = EnergyInsight(
        facility_id=facility.id,
        zone_id=zone.id,
        rule_code=InsightRuleCode.THERMAL_CORRELATED_LOAD.value,
        dedupe_key=(
            f"{InsightRuleCode.THERMAL_CORRELATED_LOAD.value}"
            f":facility={facility.id}:zone={zone.id}:meter=none"
        ),
        title="Optimize Chiller Condenser Approach",
        category=InsightCategory.HVAC_THERMAL.value,
        summary="Raise condenser water setpoint during off-peak hours.",
        monthly_kwh_savings=Decimal("4200.00"),
        annual_cost_savings=Decimal("425000.00"),
        payback_months=Decimal("3.50"),
        cost_estimate_status=CostEstimateStatus.AVAILABLE.value,
        savings_basis=InsightSavingsBasis.ESTIMATED_EXCESS_AVOIDANCE.value,
        priority=InsightPriority.HIGH.value,
        status=InsightStatus.IN_PROGRESS.value,
    )
    db_session.add(insight)
    db_session.flush()

    insight_log = InsightWorkflowLog(
        insight_id=insight.id,
        from_status=InsightStatus.RECOMMENDED.value,
        to_status=InsightStatus.IN_PROGRESS.value,
        changed_by_user_id=user.id,
        note="Approved during weekly energy review",
    )
    db_session.add_all([anomaly_log, insight_log])
    db_session.commit()

    # Deleting archived telemetry reading must null ONLY reading_id while keeping meter_id intact
    db_session.delete(reading)
    db_session.commit()
    db_session.expire_all()

    persisted_anomaly = db_session.get(Anomaly, anomaly.id)
    assert persisted_anomaly is not None
    assert persisted_anomaly.reading_id is None
    assert persisted_anomaly.meter_id == meter.id
