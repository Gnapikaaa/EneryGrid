from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.constants import (
    CostEstimateStatus,
    Environment,
    HealthStatus,
    InsightCategory,
    InsightPriority,
    InsightSavingsBasis,
    InsightStatus,
)
from app.core.database import build_session_factory
from app.models.anomaly import Anomaly
from app.models.facility import Facility, Meter, Zone
from app.models.insight import EnergyInsight, InsightWorkflowLog
from app.models.telemetry import TelemetryReading

_BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def test_phase2e_settings_validation() -> None:
    with pytest.raises(ValueError, match="elevated < high < critical"):
        Settings(
            environment=Environment.TEST,
            database_url="postgresql+psycopg://postgres:pass@localhost:5432/test",
            anomaly_z_score_elevated=Decimal("2.80"),
            anomaly_z_score_high=Decimal("2.60"),
            anomaly_z_score_critical=Decimal("3.40"),
        )

    with pytest.raises(ValueError, match="ANALYTICS_DEFAULT_MAX_READINGS"):
        Settings(
            environment=Environment.TEST,
            database_url="postgresql+psycopg://postgres:pass@localhost:5432/test",
            analytics_default_max_readings=5000,
            analytics_hard_max_readings=2000,
        )


def test_migration_0003_populated_legacy_preservation_and_roundtrip(
    db_engine: Engine,
    test_database_url: str,
) -> None:
    """Verify 0002 -> 0003 against populated tables, legacy preservation, and downgrade/upgrade."""
    cfg = _alembic_config(test_database_url)
    session_factory = build_session_factory(db_engine)

    # Step 1: Downgrade cleanly to 0002_soft_deactivation and seed legacy populated rows
    command.downgrade(cfg, "0002_soft_deactivation")
    with session_factory() as s:
        s.execute(text("""
            TRUNCATE TABLE
                meter_calibration_audits,
                insight_workflow_logs,
                energy_insights,
                anomaly_workflow_logs,
                anomalies,
                telemetry_readings,
                meters,
                zones,
                facilities,
                users
            RESTART IDENTITY CASCADE
        """))
        s.commit()

    try:
        with session_factory() as s:
            fac_id = "FAC-LEGACY-01"
            zone_id = uuid.uuid4()
            meter_id = uuid.uuid4()
            s.execute(
                text(
                    """
                    INSERT INTO facilities (
                        id, code, name, location, timezone, currency_code,
                        contracted_demand_kw, off_peak_tariff_rate, mid_peak_tariff_rate, peak_tariff_rate
                    ) VALUES (
                        :id, 'LEG01', 'Legacy Plant', 'Austin, TX', 'UTC', 'USD',
                        1000.00, 0.0500, 0.1000, 0.2000
                    )
                    """
                ),
                {"id": fac_id},
            )
            s.execute(
                text(
                    """
                    INSERT INTO zones (id, facility_id, slug, name, primary_meter_code, share_pct, status)
                    VALUES (:zid, :fid, 'legacy-zone', 'Legacy Zone', 'M-LEG-01', 100.00, 'Nominal')
                    """
                ),
                {"zid": zone_id, "fid": fac_id},
            )
            s.execute(
                text(
                    """
                    INSERT INTO meters (
                        id, facility_id, zone_id, meter_code, equipment_name,
                        rated_kw, nominal_interval_seconds, current_kw, power_factor, thd_pct, status, last_calibrated_at
                    ) VALUES (
                        :mid, :fid, :zid, 'M-LEG-01', 'Main Compressor',
                        500.00, 900, 120.00, 0.950, 2.10, 'Nominal', :cal_date
                    )
                    """
                ),
                {"mid": meter_id, "fid": fac_id, "zid": zone_id, "cal_date": date(2026, 10, 1)},
            )

            # Seed two legacy anomalies: one with 0.00 (unknown tariff provenance), one with 125.50
            zero_anom_id = uuid.uuid4()
            paid_anom_id = uuid.uuid4()
            now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
            for idx, (aid, code, cost) in enumerate(
                [
                    (zero_anom_id, "EVT-LEG-0", Decimal("0.00")),
                    (paid_anom_id, "EVT-LEG-1", Decimal("125.50")),
                ]
            ):
                s.execute(
                    text(
                        """
                        INSERT INTO anomalies (
                            id, event_code, facility_id, zone_id, meter_id, reading_id,
                            detected_at, severity, status, z_score, actual_kw, expected_kw,
                            deviation_pct, duration_min, estimated_waste_kwh, estimated_cost,
                            signature, recommendation, waveform, baseline_waveform
                        ) VALUES (
                            :id, :code, :fid, :zid, :mid, NULL,
                            :dt, 'High', 'Open', 2.80, 250.00, 150.00,
                            66.67, 15, 25.00, :cost,
                            'Legacy spike', 'Check load', '[250.0]'::jsonb, '[150.0]'::jsonb
                        )
                        """
                    ),
                    {
                        "id": aid,
                        "code": code,
                        "fid": fac_id,
                        "zid": zone_id,
                        "mid": meter_id,
                        "dt": now + timedelta(minutes=15 * idx),
                        "cost": cost,
                    },
                )

            # Seed duplicate active insights + an Implemented insight + workflow log
            ins_old = uuid.uuid4()
            ins_new = uuid.uuid4()
            ins_impl = uuid.uuid4()
            for iid, title, st, updated_at in [
                (ins_old, "Older Active Shift", "Recommended", now - timedelta(days=2)),
                (ins_new, "Newer Active Shift", "In Progress", now),
                (ins_impl, "Completed Shift", "Implemented", now - timedelta(days=10)),
            ]:
                s.execute(
                    text(
                        """
                        INSERT INTO energy_insights (
                            id, facility_id, zone_id, title, category, summary,
                            monthly_kwh_savings, annual_cost_savings, payback_months, priority, status, updated_at
                        ) VALUES (
                            :id, :fid, :zid, :title, 'Load Shifting', 'Legacy insight summary',
                            100.00, 500.00, 6.00, 'High', :st, :upd
                        )
                        """
                    ),
                    {"id": iid, "fid": fac_id, "zid": zone_id, "title": title, "st": st, "upd": updated_at},
                )
            s.execute(
                text(
                    """
                    INSERT INTO insight_workflow_logs (id, insight_id, from_status, to_status, note)
                    VALUES (:lid, :iid, 'Recommended', 'In Progress', 'Legacy log')
                    """
                ),
                {"lid": uuid.uuid4(), "iid": ins_new},
            )
            s.commit()

        # Step 2: Upgrade to head (0003) with populated legacy rows
        command.upgrade(cfg, "head")

        with session_factory() as s:
            zero_anom = s.get(Anomaly, zero_anom_id)
            paid_anom = s.get(Anomaly, paid_anom_id)
            assert zero_anom is not None and paid_anom is not None
            assert zero_anom.estimated_cost == Decimal("0.00")
            assert zero_anom.cost_estimate_status == CostEstimateStatus.LEGACY_UNVERIFIED.value
            assert paid_anom.estimated_cost == Decimal("125.50")
            assert paid_anom.cost_estimate_status == CostEstimateStatus.LEGACY_UNVERIFIED.value

            # All 3 insights and their workflow log must survive with valid constraints
            insights = s.scalars(select(EnergyInsight)).all()
            assert len(insights) == 3
            for ins in insights:
                assert ins.cost_estimate_status == CostEstimateStatus.LEGACY_UNVERIFIED.value
                assert ins.savings_basis == InsightSavingsBasis.LEGACY_MIGRATED.value
                assert ins.rule_code == "LEGACY_LOAD_SHIFTING"
                assert ins.dedupe_key
            old_row = s.get(EnergyInsight, ins_old)
            new_row = s.get(EnergyInsight, ins_new)
            assert old_row is not None and new_row is not None
            assert old_row.dedupe_key != new_row.dedupe_key
            assert ":legacy=" in old_row.dedupe_key
            assert s.scalar(select(InsightWorkflowLog).where(InsightWorkflowLog.insight_id == ins_new)) is not None

        # Step 3: Verify downgrade back to 0002 and re-upgrade to head cleanly
        command.downgrade(cfg, "0002_soft_deactivation")
        command.upgrade(cfg, "head")
    finally:
        command.upgrade(cfg, "head")
        with session_factory() as s:
            s.execute(
                text(
                    """
                    TRUNCATE TABLE
                        meter_calibration_audits,
                        insight_workflow_logs,
                        energy_insights,
                        anomaly_workflow_logs,
                        anomalies,
                        telemetry_readings,
                        meters,
                        zones,
                        facilities,
                        users
                    RESTART IDENTITY CASCADE
                    """
                )
            )
            s.commit()


def test_stage1_cost_and_dedupe_constraints(db_session: Session) -> None:
    fac = Facility(
        id="FAC-S1",
        code="S1",
        name="Stage 1 Plant",
        location="Denver, CO",
        timezone="UTC",
        currency_code="USD",
        contracted_demand_kw=Decimal("800.00"),
        off_peak_tariff_rate=Decimal("0.0500"),
        mid_peak_tariff_rate=Decimal("0.1000"),
        peak_tariff_rate=Decimal("0.2000"),
    )
    zone = Zone(
        facility_id=fac.id,
        slug="zone-a",
        name="Zone A",
        primary_meter_code="M-S1",
        share_pct=Decimal("100.00"),
        status=HealthStatus.NOMINAL.value,
    )
    other_zone = Zone(
        facility_id=fac.id,
        slug="zone-b",
        name="Zone B",
        primary_meter_code="M-S2",
        share_pct=Decimal("0.00"),
        status=HealthStatus.NOMINAL.value,
    )
    db_session.add_all([fac, zone, other_zone])
    db_session.flush()

    meter = Meter(
        facility_id=fac.id,
        zone_id=zone.id,
        meter_code="M-S1",
        equipment_name="Chiller 1",
        rated_kw=Decimal("300.00"),
        power_factor=Decimal("0.940"),
        thd_pct=Decimal("2.50"),
        status=HealthStatus.NOMINAL.value,
        last_calibrated_at=date(2026, 11, 1),
    )
    db_session.add(meter)
    db_session.flush()

    t1 = datetime(2026, 11, 10, 10, 15, tzinfo=timezone.utc)
    r1 = TelemetryReading(
        facility_id=fac.id,
        zone_id=zone.id,
        meter_id=meter.id,
        interval_start=t1 - timedelta(seconds=900),
        recorded_at=t1,
        interval_seconds=900,
        actual_kw=Decimal("200.00"),
        energy_kwh=Decimal("50.0000"),
        baseline_status="insufficient_history",
        power_factor=Decimal("0.950"),
        tariff_period="Peak",
    )
    db_session.add(r1)
    db_session.flush()
    assert r1.baseline_attempt_count == 0
    assert r1.baseline_computed_at is None

    # Anomaly unavailable_tariff requires NULL estimated_cost
    bad_anom = Anomaly(
        event_code="EVT-BAD-01",
        facility_id=fac.id,
        zone_id=zone.id,
        meter_id=meter.id,
        reading_id=r1.id,
        detected_at=t1,
        severity="Elevated",
        status="Open",
        z_score=Decimal("2.20"),
        actual_kw=Decimal("200.00"),
        expected_kw=Decimal("140.00"),
        deviation_pct=Decimal("42.86"),
        duration_min=15,
        estimated_waste_kwh=Decimal("15.00"),
        estimated_cost=Decimal("0.00"),
        cost_estimate_status=CostEstimateStatus.UNAVAILABLE_TARIFF.value,
        signature="Spike",
        recommendation="Inspect",
        waveform=[200.0],
        baseline_waveform=[140.0],
    )
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(bad_anom)
            db_session.flush()

    # Valid unavailable_tariff anomaly with NULL cost succeeds; duplicate reading_id rejected
    good_anom = Anomaly(
        event_code="EVT-OK-01",
        facility_id=fac.id,
        zone_id=zone.id,
        meter_id=meter.id,
        reading_id=r1.id,
        detected_at=t1,
        severity="Elevated",
        status="Open",
        z_score=Decimal("2.20"),
        actual_kw=Decimal("200.00"),
        expected_kw=Decimal("140.00"),
        deviation_pct=Decimal("42.86"),
        duration_min=15,
        estimated_waste_kwh=Decimal("15.00"),
        estimated_cost=None,
        cost_estimate_status=CostEstimateStatus.UNAVAILABLE_TARIFF.value,
        signature="Spike",
        recommendation="Inspect",
        waveform=[200.0],
        baseline_waveform=[140.0],
    )
    db_session.add(good_anom)
    db_session.flush()

    dup_anom = Anomaly(
        event_code="EVT-DUP-01",
        facility_id=fac.id,
        zone_id=zone.id,
        meter_id=meter.id,
        reading_id=r1.id,
        detected_at=t1,
        severity="Elevated",
        status="Open",
        z_score=Decimal("2.20"),
        actual_kw=Decimal("200.00"),
        expected_kw=Decimal("140.00"),
        deviation_pct=Decimal("42.86"),
        duration_min=15,
        estimated_waste_kwh=Decimal("15.00"),
        estimated_cost=None,
        cost_estimate_status=CostEstimateStatus.UNAVAILABLE_TARIFF.value,
        signature="Spike",
        recommendation="Inspect",
        waveform=[200.0],
        baseline_waveform=[140.0],
    )
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(dup_anom)
            db_session.flush()

    # EnergyInsight consistent cost checks, active dedupe uniqueness, and Implemented allowance
    dedupe = f"PEAK_LOAD_SHIFT:facility={fac.id}:zone={zone.id}:meter={meter.id}"
    ins_impl = EnergyInsight(
        facility_id=fac.id,
        zone_id=zone.id,
        meter_id=meter.id,
        rule_code="PEAK_LOAD_SHIFT",
        dedupe_key=dedupe,
        title="Peak Shift Implemented",
        category=InsightCategory.LOAD_SHIFTING.value,
        summary="Prior shift completed.",
        monthly_kwh_savings=Decimal("0.00"),
        annual_cost_savings=Decimal("1200.00"),
        payback_months=None,
        cost_estimate_status=CostEstimateStatus.AVAILABLE.value,
        savings_basis=InsightSavingsBasis.TARIFF_ARBITRAGE_ONLY.value,
        priority=InsightPriority.MEDIUM.value,
        status=InsightStatus.IMPLEMENTED.value,
    )
    ins_active = EnergyInsight(
        facility_id=fac.id,
        zone_id=zone.id,
        meter_id=meter.id,
        rule_code="PEAK_LOAD_SHIFT",
        dedupe_key=dedupe,
        title="Peak Shift Active",
        category=InsightCategory.LOAD_SHIFTING.value,
        summary="Current active shift opportunity.",
        monthly_kwh_savings=Decimal("0.00"),
        annual_cost_savings=Decimal("1500.00"),
        payback_months=None,
        cost_estimate_status=CostEstimateStatus.AVAILABLE.value,
        savings_basis=InsightSavingsBasis.TARIFF_ARBITRAGE_ONLY.value,
        priority=InsightPriority.MEDIUM.value,
        status=InsightStatus.RECOMMENDED.value,
    )
    db_session.add_all([ins_impl, ins_active])
    db_session.flush()

    # Second active insight with same dedupe_key must fail
    ins_dup_active = EnergyInsight(
        facility_id=fac.id,
        zone_id=zone.id,
        meter_id=meter.id,
        rule_code="PEAK_LOAD_SHIFT",
        dedupe_key=dedupe,
        title="Duplicate Active",
        category=InsightCategory.LOAD_SHIFTING.value,
        summary="Duplicate.",
        monthly_kwh_savings=Decimal("0.00"),
        annual_cost_savings=Decimal("1600.00"),
        payback_months=None,
        cost_estimate_status=CostEstimateStatus.AVAILABLE.value,
        savings_basis=InsightSavingsBasis.TARIFF_ARBITRAGE_ONLY.value,
        priority=InsightPriority.MEDIUM.value,
        status=InsightStatus.IN_PROGRESS.value,
    )
    db_session.add(ins_dup_active)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    # Cross-zone meter_id rejected by fk_insights_meter_facility_zone
    bad_fk_ins = EnergyInsight(
        facility_id=fac.id,
        zone_id=other_zone.id,
        meter_id=meter.id,
        rule_code="LOW_POWER_FACTOR",
        dedupe_key=f"LOW_POWER_FACTOR:facility={fac.id}:zone={other_zone.id}:meter={meter.id}",
        title="Bad Meter FK",
        category=InsightCategory.POWER_QUALITY.value,
        summary="Mismatched zone.",
        monthly_kwh_savings=Decimal("0.00"),
        annual_cost_savings=None,
        payback_months=None,
        cost_estimate_status=CostEstimateStatus.NOT_QUANTIFIABLE.value,
        savings_basis=InsightSavingsBasis.UNQUANTIFIED_TELEMETRY.value,
        priority=InsightPriority.MEDIUM.value,
        status=InsightStatus.RECOMMENDED.value,
    )
    db_session.add(bad_fk_ins)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
