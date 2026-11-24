from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import math
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.constants import (
    CostEstimateStatus,
    InsightCategory,
    InsightPriority,
    InsightRuleCode,
    InsightSavingsBasis,
    InsightStatus,
    QualityFlag,
    TariffPeriod,
    TelemetrySource,
)
from app.models.facility import Facility, Meter
from app.models.insight import EnergyInsight, InsightWorkflowLog
from app.models.telemetry import TelemetryReading
from app.models.user import User
from app.schemas.common import DEFAULT_PAGE, DEFAULT_PAGE_SIZE, PaginatedResponse
from app.schemas.insight import (
    InsightDetailResponse,
    InsightResponse,
    InsightWorkflowLogResponse,
)
from app.services.baselines import stable_lock_id
from app.services.exceptions import ConflictError, ResourceNotFoundError, ValidationFailureError
from app.services.permissions import (
    ALL_AUTHENTICATED_ROLES,
    ANALYTICS_OPERATIONS_ROLES,
    assert_actor_authorized,
)

LOCK_NS_INSIGHT_DEDUPE = 2002
_QUANT_2 = Decimal("0.01")
_ACTIVE_INSIGHT_STATUSES = (
    InsightStatus.RECOMMENDED.value,
    InsightStatus.IN_PROGRESS.value,
)


def _q2(val: Decimal) -> Decimal:
    return val.quantize(_QUANT_2, rounding=ROUND_HALF_UP)


def acquire_insight_dedupe_lock(db: Session, dedupe_key: str) -> None:
    """Acquire transaction-scoped advisory lock for a single insight deduplication key."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :key)"),
        {"ns": LOCK_NS_INSIGHT_DEDUPE, "key": stable_lock_id(dedupe_key)},
    )


def build_insight_dedupe_key(
    *,
    rule_code: InsightRuleCode,
    facility_id: str,
    zone_id: uuid.UUID,
    meter_id: uuid.UUID | None,
) -> str:
    meter_token = str(meter_id) if meter_id is not None else "none"
    return f"{rule_code.value}:facility={facility_id}:zone={zone_id}:meter={meter_token}"


@dataclass(frozen=True)
class InsightSample:
    recorded_at: datetime
    interval_seconds: int
    actual_kw: Decimal
    energy_kwh: Decimal
    power_factor: Decimal
    tariff_period: str
    ambient_temp_c: Decimal | None


@dataclass(frozen=True)
class InsightCandidate:
    rule_code: InsightRuleCode
    dedupe_key: str
    title: str
    category: InsightCategory
    summary: str
    monthly_kwh_savings: Decimal
    annual_cost_savings: Decimal | None
    payback_months: Decimal | None
    cost_estimate_status: CostEstimateStatus
    savings_basis: InsightSavingsBasis
    priority: InsightPriority
    evidence: dict[str, object]


def _resolve_tariff_map(facility: Facility) -> dict[str, Decimal | None]:
    def _valid_rate(rate: Decimal | None) -> Decimal | None:
        if rate is None or not rate.is_finite() or rate < Decimal("0"):
            return None
        return rate

    return {
        TariffPeriod.PEAK.value: _valid_rate(facility.peak_tariff_rate),
        TariffPeriod.MID_PEAK.value: _valid_rate(facility.mid_peak_tariff_rate),
        TariffPeriod.OFF_PEAK.value: _valid_rate(facility.off_peak_tariff_rate),
    }


def _evaluate_peak_load_shift(
    *,
    readings: list[InsightSample],
    scale_30d: Decimal,
    distinct_local_days: int,
    facility_id: str,
    zone_id: uuid.UUID,
    meter_id: uuid.UUID,
    meter_code: str,
    equipment_name: str,
    currency_code: str,
    tariff_rates: dict[str, Decimal | None],
    settings: Settings,
) -> InsightCandidate | None:
    peak_readings = [r for r in readings if r.tariff_period == TariffPeriod.PEAK.value]
    if len(peak_readings) < settings.insight_load_shift_min_peak_readings:
        return None

    total_window_kwh = sum((r.energy_kwh for r in readings), Decimal("0"))
    if total_window_kwh <= Decimal("0"):
        return None

    peak_energy_kwh = sum((r.energy_kwh for r in peak_readings), Decimal("0"))
    peak_share = peak_energy_kwh / total_window_kwh
    if peak_share < settings.insight_load_shift_peak_share_threshold:
        return None

    peak_rate = tariff_rates.get(TariffPeriod.PEAK.value)
    off_peak_rate = tariff_rates.get(TariffPeriod.OFF_PEAK.value)

    shifted_window_kwh = peak_energy_kwh * settings.insight_load_shift_transferable_fraction
    monthly_shifted_peak_kwh = _q2(shifted_window_kwh * scale_30d)
    if monthly_shifted_peak_kwh <= Decimal("0"):
        return None

    if peak_rate is None or off_peak_rate is None:
        cost_status = CostEstimateStatus.UNAVAILABLE_TARIFF
        annual_cost_savings: Decimal | None = None
        rate_spread: float | None = None
    else:
        if peak_rate <= off_peak_rate:
            return None
        rate_spread_dec = peak_rate - off_peak_rate
        annual_cost_savings = _q2(shifted_window_kwh * scale_30d * Decimal("12") * rate_spread_dec)
        cost_status = CostEstimateStatus.AVAILABLE
        rate_spread = float(rate_spread_dec)

    priority = (
        InsightPriority.HIGH
        if (
            (
                annual_cost_savings is not None
                and annual_cost_savings >= settings.insight_high_priority_annual_savings
            )
            or peak_share >= Decimal("0.60")
        )
        else InsightPriority.MEDIUM
    )

    dedupe_key = build_insight_dedupe_key(
        rule_code=InsightRuleCode.PEAK_LOAD_SHIFT,
        facility_id=facility_id,
        zone_id=zone_id,
        meter_id=meter_id,
    )

    return InsightCandidate(
        rule_code=InsightRuleCode.PEAK_LOAD_SHIFT,
        dedupe_key=dedupe_key,
        title=f"Shift Deferrable Peak Load on {meter_code} ({equipment_name})",
        category=InsightCategory.LOAD_SHIFTING,
        summary=(
            f"Peak-period energy represents {float(peak_share * Decimal('100')):.1f}% of observed load on "
            f"{meter_code} across {distinct_local_days} days; shifting {float(settings.insight_load_shift_transferable_fraction * Decimal('100')):.0f}% "
            f"of peak usage ({monthly_shifted_peak_kwh} kWh/month) to Off-Peak reduces tariff cost without assuming net kWh reduction."
        ),
        monthly_kwh_savings=Decimal("0.00"),
        annual_cost_savings=annual_cost_savings,
        payback_months=None,
        cost_estimate_status=cost_status,
        savings_basis=InsightSavingsBasis.TARIFF_ARBITRAGE_ONLY,
        priority=priority,
        evidence={
            "rule_code": InsightRuleCode.PEAK_LOAD_SHIFT.value,
            "meter_code": meter_code,
            "currency_code": currency_code,
            "window_readings": len(readings),
            "distinct_local_days": distinct_local_days,
            "peak_readings": len(peak_readings),
            "peak_energy_kwh": float(_q2(peak_energy_kwh)),
            "total_window_kwh": float(_q2(total_window_kwh)),
            "peak_share": round(float(peak_share), 4),
            "transferable_fraction": float(settings.insight_load_shift_transferable_fraction),
            "monthly_shifted_peak_kwh": float(monthly_shifted_peak_kwh),
            "peak_rate": float(peak_rate) if peak_rate is not None else None,
            "off_peak_rate": float(off_peak_rate) if off_peak_rate is not None else None,
            "rate_spread": rate_spread,
        },
    )


def _evaluate_low_power_factor(
    *,
    readings: list[InsightSample],
    distinct_local_days: int,
    facility_id: str,
    zone_id: uuid.UUID,
    meter_id: uuid.UUID,
    meter_code: str,
    equipment_name: str,
    settings: Settings,
) -> InsightCandidate | None:
    violations = [r for r in readings if r.power_factor < settings.insight_pf_threshold]
    if len(violations) < settings.insight_pf_min_violation_readings:
        return None

    violation_ratio = Decimal(len(violations)) / Decimal(len(readings))
    if violation_ratio < settings.insight_pf_min_violation_ratio:
        return None

    avg_pf = sum((r.power_factor for r in violations), Decimal("0")) / Decimal(len(violations))
    min_pf = min(r.power_factor for r in violations)
    priority = (
        InsightPriority.HIGH
        if (avg_pf < Decimal("0.82") or violation_ratio >= Decimal("0.50"))
        else InsightPriority.MEDIUM
    )

    dedupe_key = build_insight_dedupe_key(
        rule_code=InsightRuleCode.LOW_POWER_FACTOR,
        facility_id=facility_id,
        zone_id=zone_id,
        meter_id=meter_id,
    )

    return InsightCandidate(
        rule_code=InsightRuleCode.LOW_POWER_FACTOR,
        dedupe_key=dedupe_key,
        title=f"Correct Persistent Low Power Factor on {meter_code} ({equipment_name})",
        category=InsightCategory.POWER_QUALITY,
        summary=(
            f"{len(violations)} of {len(readings)} readings ({float(violation_ratio * Decimal('100')):.1f}%) on {meter_code} "
            f"recorded power factor below {settings.insight_pf_threshold} (min {min_pf:.3f}, violation avg {avg_pf:.3f}). "
            f"Utility penalty savings depend on unconfigured kVA/kVAR tariff clauses."
        ),
        monthly_kwh_savings=Decimal("0.00"),
        annual_cost_savings=None,
        payback_months=None,
        cost_estimate_status=CostEstimateStatus.NOT_QUANTIFIABLE,
        savings_basis=InsightSavingsBasis.UNQUANTIFIED_TELEMETRY,
        priority=priority,
        evidence={
            "rule_code": InsightRuleCode.LOW_POWER_FACTOR.value,
            "meter_code": meter_code,
            "window_readings": len(readings),
            "distinct_local_days": distinct_local_days,
            "pf_threshold": float(settings.insight_pf_threshold),
            "violation_readings": len(violations),
            "violation_ratio": round(float(violation_ratio), 4),
            "avg_violation_pf": round(float(avg_pf), 3),
            "min_pf": round(float(min_pf), 3),
        },
    )


def _evaluate_off_peak_baseload(
    *,
    readings: list[InsightSample],
    scale_30d: Decimal,
    distinct_local_days: int,
    facility_id: str,
    zone_id: uuid.UUID,
    meter_id: uuid.UUID,
    meter_code: str,
    equipment_name: str,
    currency_code: str,
    tariff_rates: dict[str, Decimal | None],
    settings: Settings,
) -> InsightCandidate | None:
    off_peak = [r for r in readings if r.tariff_period == TariffPeriod.OFF_PEAK.value]
    active = [
        r
        for r in readings
        if r.tariff_period in (TariffPeriod.PEAK.value, TariffPeriod.MID_PEAK.value)
    ]
    if (
        len(off_peak) < settings.insight_off_peak_min_readings
        or len(active) < settings.insight_off_peak_active_min_readings
    ):
        return None

    avg_off_peak_kw = sum((r.actual_kw for r in off_peak), Decimal("0")) / Decimal(len(off_peak))
    avg_active_kw = sum((r.actual_kw for r in active), Decimal("0")) / Decimal(len(active))
    if avg_active_kw <= Decimal("0"):
        return None

    baseload_ratio = avg_off_peak_kw / avg_active_kw
    if baseload_ratio < settings.insight_off_peak_baseload_ratio:
        return None

    # Target off-peak idle benchmark is 50% of active-period mean demand
    target_idle_kw = avg_active_kw * Decimal("0.50")
    window_excess_kwh = sum(
        (
            max(Decimal("0"), r.actual_kw - target_idle_kw)
            * Decimal(r.interval_seconds)
            / Decimal("3600")
            for r in off_peak
        ),
        Decimal("0"),
    )
    monthly_kwh_savings = _q2(window_excess_kwh * scale_30d)
    if monthly_kwh_savings <= Decimal("0"):
        return None

    off_peak_rate = tariff_rates.get(TariffPeriod.OFF_PEAK.value)
    if off_peak_rate is None:
        cost_status = CostEstimateStatus.UNAVAILABLE_TARIFF
        annual_cost_savings: Decimal | None = None
    else:
        annual_cost_savings = _q2(window_excess_kwh * scale_30d * Decimal("12") * off_peak_rate)
        cost_status = CostEstimateStatus.AVAILABLE

    lower_name = equipment_name.lower()
    category = (
        InsightCategory.COMPRESSED_AIR
        if any(token in lower_name for token in ("air", "compressor", "pneumatic"))
        else InsightCategory.LOAD_SHIFTING
    )
    priority = (
        InsightPriority.HIGH
        if (
            (
                annual_cost_savings is not None
                and annual_cost_savings >= settings.insight_high_priority_annual_savings
            )
            or baseload_ratio >= Decimal("0.80")
        )
        else InsightPriority.MEDIUM
    )

    dedupe_key = build_insight_dedupe_key(
        rule_code=InsightRuleCode.OFF_PEAK_BASELOAD_PATTERN,
        facility_id=facility_id,
        zone_id=zone_id,
        meter_id=meter_id,
    )

    return InsightCandidate(
        rule_code=InsightRuleCode.OFF_PEAK_BASELOAD_PATTERN,
        dedupe_key=dedupe_key,
        title=f"Reduce Elevated Off-Peak Baseload on {meter_code} ({equipment_name})",
        category=category,
        summary=(
            f"Off-peak average demand ({_q2(avg_off_peak_kw)} kW) on {meter_code} is {float(baseload_ratio * Decimal('100')):.1f}% "
            f"of active-period demand ({_q2(avg_active_kw)} kW) across {distinct_local_days} days; reducing off-peak idle draw "
            f"toward the 50% active benchmark yields an estimated {monthly_kwh_savings} kWh/month avoidance."
        ),
        monthly_kwh_savings=monthly_kwh_savings,
        annual_cost_savings=annual_cost_savings,
        payback_months=None,
        cost_estimate_status=cost_status,
        savings_basis=InsightSavingsBasis.ESTIMATED_EXCESS_AVOIDANCE,
        priority=priority,
        evidence={
            "rule_code": InsightRuleCode.OFF_PEAK_BASELOAD_PATTERN.value,
            "meter_code": meter_code,
            "currency_code": currency_code,
            "off_peak_readings": len(off_peak),
            "active_readings": len(active),
            "distinct_local_days": distinct_local_days,
            "avg_off_peak_kw": float(_q2(avg_off_peak_kw)),
            "avg_active_kw": float(_q2(avg_active_kw)),
            "target_idle_kw": float(_q2(target_idle_kw)),
            "baseload_ratio": round(float(baseload_ratio), 4),
            "window_excess_kwh": float(_q2(window_excess_kwh)),
            "off_peak_rate": float(off_peak_rate) if off_peak_rate is not None else None,
        },
    )


def _compute_median_decimal(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / Decimal("2")


def _evaluate_thermal_correlation(
    *,
    readings: list[InsightSample],
    scale_30d: Decimal,
    distinct_local_days: int,
    facility_id: str,
    zone_id: uuid.UUID,
    meter_id: uuid.UUID,
    meter_code: str,
    equipment_name: str,
    currency_code: str,
    tariff_rates: dict[str, Decimal | None],
    settings: Settings,
) -> InsightCandidate | None:
    thermal = [r for r in readings if r.ambient_temp_c is not None]
    if len(thermal) < settings.insight_thermal_min_readings:
        return None

    m = Decimal(len(thermal))
    temps = [r.ambient_temp_c for r in thermal if r.ambient_temp_c is not None]
    loads = [r.actual_kw for r in thermal]

    mean_t = sum(temps, Decimal("0")) / m
    mean_p = sum(loads, Decimal("0")) / m

    s_tt = sum(((t - mean_t) ** 2 for t in temps), Decimal("0"))
    s_pp = sum(((p - mean_p) ** 2 for p in loads), Decimal("0"))
    if s_tt <= Decimal("0") or s_pp <= Decimal("0"):
        return None

    s_tp = sum(((t - mean_t) * (p - mean_p) for t, p in zip(temps, loads, strict=True)), Decimal("0"))
    denom = math.sqrt(float(s_tt) * float(s_pp))
    if denom <= 0.0 or not math.isfinite(denom):
        return None

    pearson_r_float = float(s_tp) / denom
    if not math.isfinite(pearson_r_float):
        return None
    pearson_r = Decimal(str(round(pearson_r_float, 6)))
    if pearson_r < settings.insight_thermal_min_correlation:
        return None

    median_t = _compute_median_decimal(temps)
    cool_readings = [r for r in thermal if r.ambient_temp_c is not None and r.ambient_temp_c <= median_t]
    warm_readings = [r for r in thermal if r.ambient_temp_c is not None and r.ambient_temp_c > median_t]
    if not cool_readings or not warm_readings:
        return None

    cool_baseline_kw = sum((r.actual_kw for r in cool_readings), Decimal("0")) / Decimal(
        len(cool_readings)
    )

    window_excess_kwh = Decimal("0")
    per_period_excess_kwh: dict[str, Decimal] = {
        TariffPeriod.PEAK.value: Decimal("0"),
        TariffPeriod.MID_PEAK.value: Decimal("0"),
        TariffPeriod.OFF_PEAK.value: Decimal("0"),
    }
    window_excess_cost = Decimal("0")
    missing_tariff_encountered = False

    for r in warm_readings:
        excess_kw = max(Decimal("0"), r.actual_kw - cool_baseline_kw)
        if excess_kw <= Decimal("0"):
            continue
        interval_excess_kwh = excess_kw * Decimal(r.interval_seconds) / Decimal("3600")
        window_excess_kwh += interval_excess_kwh
        per_period_excess_kwh[r.tariff_period] = (
            per_period_excess_kwh.get(r.tariff_period, Decimal("0")) + interval_excess_kwh
        )
        rate = tariff_rates.get(r.tariff_period)
        if rate is None:
            missing_tariff_encountered = True
        else:
            window_excess_cost += interval_excess_kwh * rate

    monthly_kwh_savings = _q2(window_excess_kwh * scale_30d)
    if monthly_kwh_savings <= Decimal("0"):
        return None

    if missing_tariff_encountered:
        cost_status = CostEstimateStatus.UNAVAILABLE_TARIFF
        annual_cost_savings: Decimal | None = None
    else:
        cost_status = CostEstimateStatus.AVAILABLE
        annual_cost_savings = _q2(window_excess_cost * scale_30d * Decimal("12"))

    priority = (
        InsightPriority.HIGH
        if (
            (
                annual_cost_savings is not None
                and annual_cost_savings >= settings.insight_high_priority_annual_savings
            )
            or pearson_r >= Decimal("0.80")
        )
        else InsightPriority.MEDIUM
    )

    dedupe_key = build_insight_dedupe_key(
        rule_code=InsightRuleCode.THERMAL_CORRELATED_LOAD,
        facility_id=facility_id,
        zone_id=zone_id,
        meter_id=meter_id,
    )

    return InsightCandidate(
        rule_code=InsightRuleCode.THERMAL_CORRELATED_LOAD,
        dedupe_key=dedupe_key,
        title=f"Optimize Temperature-Correlated Load on {meter_code} ({equipment_name})",
        category=InsightCategory.HVAC_THERMAL,
        summary=(
            f"Demand on {meter_code} shows strong positive correlation with ambient temperature (Pearson r={float(pearson_r):.2f} across "
            f"{len(thermal)} readings). Excess demand above the cool-half baseline ({_q2(cool_baseline_kw)} kW at <= {median_t} C) "
            f"totals an estimated {monthly_kwh_savings} kWh/month."
        ),
        monthly_kwh_savings=monthly_kwh_savings,
        annual_cost_savings=annual_cost_savings,
        payback_months=None,
        cost_estimate_status=cost_status,
        savings_basis=InsightSavingsBasis.ESTIMATED_EXCESS_AVOIDANCE,
        priority=priority,
        evidence={
            "rule_code": InsightRuleCode.THERMAL_CORRELATED_LOAD.value,
            "meter_code": meter_code,
            "currency_code": currency_code,
            "thermal_readings": len(thermal),
            "distinct_local_days": distinct_local_days,
            "pearson_r": round(float(pearson_r), 4),
            "median_temp_c": float(_q2(median_t)),
            "cool_baseline_kw": float(_q2(cool_baseline_kw)),
            "window_excess_kwh": float(_q2(window_excess_kwh)),
            "per_period_excess_kwh": {
                period: float(_q2(kwh)) for period, kwh in per_period_excess_kwh.items()
            },
            "mixed_tariff_rates_complete": not missing_tariff_encountered,
        },
    )


def compute_meter_insight_candidates(
    *,
    readings: list[InsightSample],
    facility_id: str,
    facility_timezone: str,
    currency_code: str,
    zone_id: uuid.UUID,
    meter_id: uuid.UUID,
    meter_code: str,
    equipment_name: str,
    tariff_rates: dict[str, Decimal | None],
    settings: Settings,
) -> list[InsightCandidate]:
    """Pure deterministic evaluation of all 4 Phase 2E insight rules for a single meter."""
    if len(readings) < settings.insight_min_window_readings:
        return []

    tz = ZoneInfo(facility_timezone)
    distinct_dates = {r.recorded_at.astimezone(UTC).astimezone(tz).date() for r in readings}
    distinct_local_days = len(distinct_dates)
    if distinct_local_days < settings.insight_min_window_days:
        return []

    observed_days = min(settings.insight_lookback_days, max(1, distinct_local_days))
    scale_30d = Decimal("30") / Decimal(observed_days)

    candidates: list[InsightCandidate] = []
    evaluators = (
        _evaluate_peak_load_shift(
            readings=readings,
            scale_30d=scale_30d,
            distinct_local_days=distinct_local_days,
            facility_id=facility_id,
            zone_id=zone_id,
            meter_id=meter_id,
            meter_code=meter_code,
            equipment_name=equipment_name,
            currency_code=currency_code,
            tariff_rates=tariff_rates,
            settings=settings,
        ),
        _evaluate_low_power_factor(
            readings=readings,
            distinct_local_days=distinct_local_days,
            facility_id=facility_id,
            zone_id=zone_id,
            meter_id=meter_id,
            meter_code=meter_code,
            equipment_name=equipment_name,
            settings=settings,
        ),
        _evaluate_off_peak_baseload(
            readings=readings,
            scale_30d=scale_30d,
            distinct_local_days=distinct_local_days,
            facility_id=facility_id,
            zone_id=zone_id,
            meter_id=meter_id,
            meter_code=meter_code,
            equipment_name=equipment_name,
            currency_code=currency_code,
            tariff_rates=tariff_rates,
            settings=settings,
        ),
        _evaluate_thermal_correlation(
            readings=readings,
            scale_30d=scale_30d,
            distinct_local_days=distinct_local_days,
            facility_id=facility_id,
            zone_id=zone_id,
            meter_id=meter_id,
            meter_code=meter_code,
            equipment_name=equipment_name,
            currency_code=currency_code,
            tariff_rates=tariff_rates,
            settings=settings,
        ),
    )
    for item in evaluators:
        if item is not None:
            candidates.append(item)
    return candidates


def evaluate_meter_insights(
    db: Session,
    *,
    meter: Meter,
    facility: Facility,
    actor: User,
    now_utc: datetime,
    settings: Settings,
) -> tuple[int, int]:
    """Evaluate insights for one meter inside a meter-locked transaction, enforcing lock DAG."""
    if not meter.is_active or not facility.is_active:
        return 0, 0

    window_start = now_utc - timedelta(days=settings.insight_lookback_days)
    rows = db.execute(
        select(
            TelemetryReading.recorded_at,
            TelemetryReading.interval_seconds,
            TelemetryReading.actual_kw,
            TelemetryReading.energy_kwh,
            TelemetryReading.power_factor,
            TelemetryReading.tariff_period,
            TelemetryReading.ambient_temp_c,
        )
        .where(
            TelemetryReading.meter_id == meter.id,
            TelemetryReading.quality_flag == QualityFlag.VALID.value,
            TelemetryReading.source != TelemetrySource.SIMULATION.value,
            TelemetryReading.recorded_at >= window_start,
            TelemetryReading.recorded_at <= now_utc,
        )
        .order_by(TelemetryReading.recorded_at.asc(), TelemetryReading.id.asc())
    ).all()

    samples = [
        InsightSample(
            recorded_at=r[0],
            interval_seconds=int(r[1]),
            actual_kw=r[2],
            energy_kwh=r[3],
            power_factor=r[4],
            tariff_period=r[5],
            ambient_temp_c=r[6],
        )
        for r in rows
    ]

    candidates = compute_meter_insight_candidates(
        readings=samples,
        facility_id=facility.id,
        facility_timezone=facility.timezone,
        currency_code=facility.currency_code,
        zone_id=meter.zone_id,
        meter_id=meter.id,
        meter_code=meter.meter_code,
        equipment_name=meter.equipment_name,
        tariff_rates=_resolve_tariff_map(facility),
        settings=settings,
    )
    if not candidates:
        return 0, 0

    created = 0
    updated = 0

    for candidate in candidates:
        # Lock order DAG: 2001 (caller) -> 2002 (dedupe) -> energy_insights row lock
        acquire_insight_dedupe_lock(db, candidate.dedupe_key)

        existing = db.scalar(
            select(EnergyInsight)
            .where(
                EnergyInsight.dedupe_key == candidate.dedupe_key,
                EnergyInsight.status.in_(_ACTIVE_INSIGHT_STATUSES),
            )
            .with_for_update()
        )
        if existing is None:
            insight = EnergyInsight(
                facility_id=facility.id,
                zone_id=meter.zone_id,
                meter_id=meter.id,
                rule_code=candidate.rule_code.value,
                dedupe_key=candidate.dedupe_key,
                title=candidate.title,
                category=candidate.category.value,
                summary=candidate.summary,
                monthly_kwh_savings=candidate.monthly_kwh_savings,
                annual_cost_savings=candidate.annual_cost_savings,
                payback_months=candidate.payback_months,
                cost_estimate_status=candidate.cost_estimate_status.value,
                savings_basis=candidate.savings_basis.value,
                evidence=candidate.evidence,
                priority=candidate.priority.value,
                status=InsightStatus.RECOMMENDED.value,
                updated_at=now_utc,
            )
            db.add(insight)
            db.flush()
            db.add(
                InsightWorkflowLog(
                    insight_id=insight.id,
                    from_status=None,
                    to_status=InsightStatus.RECOMMENDED.value,
                    changed_by_user_id=actor.id,
                    note=f"Generated by {candidate.rule_code.value} rule evaluation.",
                )
            )
            created += 1
            continue

        changed = (
            existing.title != candidate.title
            or existing.category != candidate.category.value
            or existing.summary != candidate.summary
            or existing.monthly_kwh_savings != candidate.monthly_kwh_savings
            or existing.annual_cost_savings != candidate.annual_cost_savings
            or existing.payback_months != candidate.payback_months
            or existing.cost_estimate_status != candidate.cost_estimate_status.value
            or existing.savings_basis != candidate.savings_basis.value
            or existing.evidence != candidate.evidence
            or existing.priority != candidate.priority.value
        )
        if changed:
            existing.title = candidate.title
            existing.category = candidate.category.value
            existing.summary = candidate.summary
            existing.monthly_kwh_savings = candidate.monthly_kwh_savings
            existing.annual_cost_savings = candidate.annual_cost_savings
            existing.payback_months = candidate.payback_months
            existing.cost_estimate_status = candidate.cost_estimate_status.value
            existing.savings_basis = candidate.savings_basis.value
            existing.evidence = candidate.evidence
            existing.priority = candidate.priority.value
            existing.updated_at = now_utc
            updated += 1

    return created, updated


def list_insights(
    db: Session,
    *,
    actor: User,
    page: int = DEFAULT_PAGE,
    page_size: int = DEFAULT_PAGE_SIZE,
    facility_id: str | None = None,
    zone_id: uuid.UUID | None = None,
    meter_id: uuid.UUID | None = None,
    status: InsightStatus | None = None,
    priority: InsightPriority | None = None,
    category: InsightCategory | None = None,
) -> PaginatedResponse[InsightResponse]:
    assert_actor_authorized(actor, ALL_AUTHENTICATED_ROLES)

    filters = []
    if facility_id is not None:
        filters.append(EnergyInsight.facility_id == facility_id)
    if zone_id is not None:
        filters.append(EnergyInsight.zone_id == zone_id)
    if meter_id is not None:
        filters.append(EnergyInsight.meter_id == meter_id)
    if status is not None:
        filters.append(EnergyInsight.status == status.value)
    if priority is not None:
        filters.append(EnergyInsight.priority == priority.value)
    if category is not None:
        filters.append(EnergyInsight.category == category.value)

    total = int(db.scalar(select(func.count(EnergyInsight.id)).where(*filters)) or 0)
    pages = math.ceil(total / page_size) if total > 0 else 0
    rows = list(
        db.scalars(
            select(EnergyInsight)
            .where(*filters)
            .order_by(EnergyInsight.updated_at.desc(), EnergyInsight.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return PaginatedResponse[InsightResponse](
        items=[InsightResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


def get_insight(
    db: Session,
    *,
    actor: User,
    insight_id: uuid.UUID,
) -> InsightDetailResponse:
    assert_actor_authorized(actor, ALL_AUTHENTICATED_ROLES)
    insight = db.get(EnergyInsight, insight_id)
    if insight is None:
        raise ResourceNotFoundError(f"Insight '{insight_id}' was not found.")
    return InsightDetailResponse.model_validate(insight)


def get_insight_history(
    db: Session,
    *,
    actor: User,
    insight_id: uuid.UUID,
) -> list[InsightWorkflowLogResponse]:
    assert_actor_authorized(actor, ALL_AUTHENTICATED_ROLES)
    if db.get(EnergyInsight, insight_id) is None:
        raise ResourceNotFoundError(f"Insight '{insight_id}' was not found.")
    logs = list(
        db.scalars(
            select(InsightWorkflowLog)
            .where(InsightWorkflowLog.insight_id == insight_id)
            .order_by(InsightWorkflowLog.changed_at.asc(), InsightWorkflowLog.id.asc())
        ).all()
    )
    return [InsightWorkflowLogResponse.model_validate(log) for log in logs]


def update_insight_status(
    db: Session,
    *,
    actor: User,
    insight_id: uuid.UUID,
    new_status: InsightStatus,
    note: str | None = None,
) -> InsightDetailResponse:
    """Update insight lifecycle status enforcing 2002 advisory lock BEFORE FOR UPDATE row locks."""
    assert_actor_authorized(actor, ANALYTICS_OPERATIONS_ROLES)

    # Read immutable dedupe_key without FOR UPDATE to respect lock ordering (2002 -> row lock)
    dedupe_key = db.scalar(
        select(EnergyInsight.dedupe_key).where(EnergyInsight.id == insight_id)
    )
    if dedupe_key is None:
        raise ResourceNotFoundError(f"Insight '{insight_id}' was not found.")

    acquire_insight_dedupe_lock(db, dedupe_key)

    insight = db.scalar(
        select(EnergyInsight).where(EnergyInsight.id == insight_id).with_for_update()
    )
    if insight is None:
        raise ResourceNotFoundError(f"Insight '{insight_id}' was not found.")

    if insight.status == new_status.value:
        raise ConflictError(f"Insight is already in '{new_status.value}' status.")

    # Guard reactivation from Implemented -> active status against existing active dedupe owner
    if (
        insight.status == InsightStatus.IMPLEMENTED.value
        and new_status.value in _ACTIVE_INSIGHT_STATUSES
    ):
        conflicting = db.scalar(
            select(EnergyInsight.id)
            .where(
                and_(
                    EnergyInsight.dedupe_key == insight.dedupe_key,
                    EnergyInsight.id != insight.id,
                    EnergyInsight.status.in_(_ACTIVE_INSIGHT_STATUSES),
                )
            )
            .with_for_update()
        )
        if conflicting is not None:
            raise ConflictError(
                "Cannot reactivate insight: an active insight already exists for this scope and rule."
            )

    prev_status = insight.status
    insight.status = new_status.value
    insight.updated_at = datetime.now(UTC)
    db.add(
        InsightWorkflowLog(
            insight_id=insight.id,
            from_status=prev_status,
            to_status=new_status.value,
            changed_by_user_id=actor.id,
            note=note,
        )
    )
    db.commit()
    db.refresh(insight)
    return InsightDetailResponse.model_validate(insight)
