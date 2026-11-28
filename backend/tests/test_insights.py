from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.constants import (
    CostEstimateStatus,
    Environment,
    HealthStatus,
    InsightCategory,
    InsightPriority,
    InsightRuleCode,
    InsightSavingsBasis,
    InsightStatus,
    TariffPeriod,
    UserRole,
)
from app.models.facility import Facility, Meter, Zone
from app.models.insight import EnergyInsight, InsightWorkflowLog
from app.models.user import User
from app.services import insights as insight_service
from app.services.exceptions import ConflictError, PermissionDeniedError
from app.services.insights import InsightSample, compute_meter_insight_candidates


def _unit_settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_url="postgresql+psycopg://postgres:pass@localhost:5432/test",
    )


def test_insight_window_gates_and_zero_variance_thermal_guard() -> None:
    s = _unit_settings()
    meter_id = uuid.uuid4()
    zone_id = uuid.uuid4()

    # Too few distinct days (96 readings in 2 days < min 7 distinct days) -> returns empty
    base = datetime(2026, 11, 1, 0, 15, tzinfo=timezone.utc)
    two_days = [
        InsightSample(
            recorded_at=base + timedelta(minutes=15 * i),
            interval_seconds=900,
            actual_kw=Decimal("100.00"),
            energy_kwh=Decimal("25.0000"),
            power_factor=Decimal("0.950"),
            tariff_period=TariffPeriod.PEAK.value,
            ambient_temp_c=Decimal("25.00"),
        )
        for i in range(96)
    ]
    assert (
        compute_meter_insight_candidates(
            readings=two_days,
            facility_id="FAC-1",
            facility_timezone="UTC",
            currency_code="USD",
            zone_id=zone_id,
            meter_id=meter_id,
            meter_code="M-1",
            equipment_name="Chiller-1",
            tariff_rates={
                TariffPeriod.PEAK.value: Decimal("0.2000"),
                TariffPeriod.MID_PEAK.value: Decimal("0.1200"),
                TariffPeriod.OFF_PEAK.value: Decimal("0.0600"),
            },
            settings=s,
        )
        == []
    )

    # Constant ambient temp (zero variance) across 10 days -> Pearson undefined, thermal must NOT fire
    ten_days_constant_temp: list[InsightSample] = []
    for day in range(10):
        for slot in range(10):
            ts = datetime(2026, 11, 1 + day, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=15 * slot)
            ten_days_constant_temp.append(
                InsightSample(
                    recorded_at=ts,
                    interval_seconds=900,
                    actual_kw=Decimal("100.00") + Decimal(slot),
                    energy_kwh=(Decimal("100.00") + Decimal(slot)) * Decimal("0.25"),
                    power_factor=Decimal("0.950"),
                    tariff_period=TariffPeriod.MID_PEAK.value,
                    ambient_temp_c=Decimal("22.00"),  # constant temp -> zero variance
                )
            )
    cands = compute_meter_insight_candidates(
        readings=ten_days_constant_temp,
        facility_id="FAC-1",
        facility_timezone="UTC",
        currency_code="USD",
        zone_id=zone_id,
        meter_id=meter_id,
        meter_code="M-1",
        equipment_name="Chiller-1",
        tariff_rates={
            TariffPeriod.PEAK.value: Decimal("0.2000"),
            TariffPeriod.MID_PEAK.value: Decimal("0.1200"),
            TariffPeriod.OFF_PEAK.value: Decimal("0.0600"),
        },
        settings=s,
    )
    assert all(c.rule_code != InsightRuleCode.THERMAL_CORRELATED_LOAD for c in cands)


def test_insight_all_four_rules_and_mixed_tariff_thermal_savings() -> None:
    s = _unit_settings()
    meter_id = uuid.uuid4()
    zone_id = uuid.uuid4()

    # Build 10 distinct days * 14 readings/day = 140 readings covering Off-Peak, Mid-Peak, Peak
    samples: list[InsightSample] = []
    for day in range(10):
        day_dt = datetime(2026, 11, 1 + day, 0, 0, tzinfo=timezone.utc)
        # 7 Off-Peak readings: cool (15C), high baseload 90 kW, low PF (0.800)
        for h in range(0, 7):
            samples.append(
                InsightSample(
                    recorded_at=day_dt + timedelta(hours=h),
                    interval_seconds=3600,
                    actual_kw=Decimal("90.00"),
                    energy_kwh=Decimal("90.0000"),
                    power_factor=Decimal("0.800"),
                    tariff_period=TariffPeriod.OFF_PEAK.value,
                    ambient_temp_c=Decimal("15.00"),
                )
            )
        # 2 Mid-Peak readings: warm (30C > median 22.5C), 105 kW (> 90 kW cool baseline)
        for h in (9, 10):
            samples.append(
                InsightSample(
                    recorded_at=day_dt + timedelta(hours=h),
                    interval_seconds=3600,
                    actual_kw=Decimal("105.00"),
                    energy_kwh=Decimal("105.0000"),
                    power_factor=Decimal("0.940"),
                    tariff_period=TariffPeriod.MID_PEAK.value,
                    ambient_temp_c=Decimal("30.00"),
                )
            )
        # 5 Peak readings: hottest (35C), 150 kW -> drives thermal correlation AND peak share > 45%
        for h in (13, 14, 15, 16, 17):
            samples.append(
                InsightSample(
                    recorded_at=day_dt + timedelta(hours=h),
                    interval_seconds=3600,
                    actual_kw=Decimal("150.00"),
                    energy_kwh=Decimal("150.0000"),
                    power_factor=Decimal("0.930"),
                    tariff_period=TariffPeriod.PEAK.value,
                    ambient_temp_c=Decimal("35.00"),
                )
            )

    complete_rates = {
        TariffPeriod.PEAK.value: Decimal("0.2000"),
        TariffPeriod.MID_PEAK.value: Decimal("0.1000"),
        TariffPeriod.OFF_PEAK.value: Decimal("0.0500"),
    }
    candidates = compute_meter_insight_candidates(
        readings=samples,
        facility_id="FAC-1",
        facility_timezone="UTC",
        currency_code="USD",
        zone_id=zone_id,
        meter_id=meter_id,
        meter_code="COMP-1",
        equipment_name="Main Air Compressor",
        tariff_rates=complete_rates,
        settings=s,
    )
    by_rule = {c.rule_code: c for c in candidates}
    assert set(by_rule.keys()) == {
        InsightRuleCode.PEAK_LOAD_SHIFT,
        InsightRuleCode.LOW_POWER_FACTOR,
        InsightRuleCode.OFF_PEAK_BASELOAD_PATTERN,
        InsightRuleCode.THERMAL_CORRELATED_LOAD,
    }

    # Verify TARIFF_ARBITRAGE_ONLY keeps monthly_kwh_savings = 0.00 and payback_months = None
    peak_cand = by_rule[InsightRuleCode.PEAK_LOAD_SHIFT]
    assert peak_cand.monthly_kwh_savings == Decimal("0.00")
    assert peak_cand.cost_estimate_status == CostEstimateStatus.AVAILABLE
    assert peak_cand.savings_basis == InsightSavingsBasis.TARIFF_ARBITRAGE_ONLY
    assert peak_cand.annual_cost_savings is not None and peak_cand.annual_cost_savings > 0
    assert peak_cand.payback_months is None

    # Verify LOW_POWER_FACTOR is explicitly NOT_QUANTIFIABLE
    pf_cand = by_rule[InsightRuleCode.LOW_POWER_FACTOR]
    assert pf_cand.cost_estimate_status == CostEstimateStatus.NOT_QUANTIFIABLE
    assert pf_cand.savings_basis == InsightSavingsBasis.UNQUANTIFIED_TELEMETRY
    assert pf_cand.annual_cost_savings is None
    assert pf_cand.monthly_kwh_savings == Decimal("0.00")

    # Verify OFF_PEAK_BASELOAD categorizes compressed air and gives positive excess avoidance
    base_cand = by_rule[InsightRuleCode.OFF_PEAK_BASELOAD_PATTERN]
    assert base_cand.category == InsightCategory.COMPRESSED_AIR
    assert base_cand.cost_estimate_status == CostEstimateStatus.AVAILABLE
    assert base_cand.savings_basis == InsightSavingsBasis.ESTIMATED_EXCESS_AVOIDANCE
    assert base_cand.monthly_kwh_savings > 0
    assert base_cand.annual_cost_savings is not None and base_cand.annual_cost_savings > 0

    # Verify THERMAL mixed-tariff calculation & missing-tariff behavior
    therm = by_rule[InsightRuleCode.THERMAL_CORRELATED_LOAD]
    assert therm.cost_estimate_status == CostEstimateStatus.AVAILABLE
    assert therm.annual_cost_savings is not None and therm.annual_cost_savings > 0
    assert therm.evidence["mixed_tariff_rates_complete"] is True

    # If Mid-Peak tariff is missing in mixed-tariff thermal excess -> UNAVAILABLE_TARIFF and NULL cost
    partial_rates = {
        TariffPeriod.PEAK.value: Decimal("0.2000"),
        TariffPeriod.MID_PEAK.value: None,
        TariffPeriod.OFF_PEAK.value: Decimal("0.0500"),
    }
    cands_missing = compute_meter_insight_candidates(
        readings=samples,
        facility_id="FAC-1",
        facility_timezone="UTC",
        currency_code="USD",
        zone_id=zone_id,
        meter_id=meter_id,
        meter_code="COMP-1",
        equipment_name="Main Air Compressor",
        tariff_rates=partial_rates,
        settings=s,
    )
    therm_missing = {c.rule_code: c for c in cands_missing}[InsightRuleCode.THERMAL_CORRELATED_LOAD]
    assert therm_missing.cost_estimate_status == CostEstimateStatus.UNAVAILABLE_TARIFF
    assert therm_missing.annual_cost_savings is None
    assert therm_missing.monthly_kwh_savings == therm.monthly_kwh_savings


def test_db_insight_reactivation_conflict_and_rbac(db_session: Session) -> None:
    eng = User(
        email="eng_ins@energygrid.test",
        full_name="Engineer",
        password_hash="hash",
        role=UserRole.UTILITY_ENGINEER.value,
        is_active=True,
    )
    fm = User(
        email="fm_ins@energygrid.test",
        full_name="FM",
        password_hash="hash",
        role=UserRole.FACILITY_MANAGER.value,
        is_active=True,
    )
    fac = Facility(
        id="FAC-INS",
        code="INS",
        name="Insight Plant",
        location="Denver, CO",
        timezone="UTC",
        currency_code="USD",
        contracted_demand_kw=Decimal("400.00"),
        off_peak_tariff_rate=Decimal("0.0500"),
        mid_peak_tariff_rate=Decimal("0.1000"),
        peak_tariff_rate=Decimal("0.2000"),
    )
    zone = Zone(
        facility_id=fac.id,
        slug="z1",
        name="Z1",
        primary_meter_code="M-INS",
        share_pct=Decimal("100.00"),
        status=HealthStatus.NOMINAL.value,
    )
    db_session.add_all([eng, fm, fac, zone])
    db_session.flush()

    meter = Meter(
        facility_id=fac.id,
        zone_id=zone.id,
        meter_code="M-INS",
        equipment_name="HVAC-1",
        rated_kw=Decimal("150.00"),
        power_factor=Decimal("0.940"),
        thd_pct=Decimal("2.00"),
        status=HealthStatus.NOMINAL.value,
        last_calibrated_at=date(2026, 11, 1),
    )
    db_session.add(meter)
    db_session.flush()

    dedupe_key = f"LOW_POWER_FACTOR:facility={fac.id}:zone={zone.id}:meter={meter.id}"
    implemented = EnergyInsight(
        facility_id=fac.id,
        zone_id=zone.id,
        meter_id=meter.id,
        rule_code=InsightRuleCode.LOW_POWER_FACTOR.value,
        dedupe_key=dedupe_key,
        title="Old Implemented",
        category=InsightCategory.POWER_QUALITY.value,
        summary="Historical implemented insight",
        monthly_kwh_savings=Decimal("0.00"),
        annual_cost_savings=None,
        payback_months=None,
        cost_estimate_status=CostEstimateStatus.NOT_QUANTIFIABLE.value,
        savings_basis=InsightSavingsBasis.UNQUANTIFIED_TELEMETRY.value,
        priority=InsightPriority.MEDIUM.value,
        status=InsightStatus.IMPLEMENTED.value,
    )
    active = EnergyInsight(
        facility_id=fac.id,
        zone_id=zone.id,
        meter_id=meter.id,
        rule_code=InsightRuleCode.LOW_POWER_FACTOR.value,
        dedupe_key=dedupe_key,
        title="Current Active",
        category=InsightCategory.POWER_QUALITY.value,
        summary="Current active insight",
        monthly_kwh_savings=Decimal("0.00"),
        annual_cost_savings=None,
        payback_months=None,
        cost_estimate_status=CostEstimateStatus.NOT_QUANTIFIABLE.value,
        savings_basis=InsightSavingsBasis.UNQUANTIFIED_TELEMETRY.value,
        priority=InsightPriority.MEDIUM.value,
        status=InsightStatus.RECOMMENDED.value,
    )
    db_session.add_all([implemented, active])
    db_session.commit()

    # Facility manager strictly read-only
    with pytest.raises(PermissionDeniedError):
        insight_service.update_insight_status(
            db_session,
            actor=fm,
            insight_id=active.id,
            new_status=InsightStatus.IN_PROGRESS,
        )

    # Reactivating historical Implemented insight while an active dedupe owner exists must raise 409 ConflictError
    with pytest.raises(ConflictError):
        insight_service.update_insight_status(
            db_session,
            actor=eng,
            insight_id=implemented.id,
            new_status=InsightStatus.RECOMMENDED,
        )

    # Valid transition of active row creates workflow log
    prog = insight_service.update_insight_status(
        db_session,
        actor=eng,
        insight_id=active.id,
        new_status=InsightStatus.IN_PROGRESS,
        note="Scheduled capacitor bank check",
    )
    assert prog.status == InsightStatus.IN_PROGRESS
    logs = insight_service.get_insight_history(db_session, actor=fm, insight_id=active.id)
    assert len(logs) == 1
    assert logs[0].from_status == InsightStatus.RECOMMENDED
    assert logs[0].to_status == InsightStatus.IN_PROGRESS
