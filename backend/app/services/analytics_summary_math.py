"""Pure calculation helpers for server-side analytics summary endpoints.

Zero ORM/web dependencies so window math, trend calculations, meter health status
derivation, and heatmap/time-series aggregation are deterministic and unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import math
from typing import Literal
from zoneinfo import ZoneInfo

SummaryWindow = Literal["24h", "7d", "30d", "custom"]


@dataclass(frozen=True)
class SummarySampleRow:
    meter_id: str
    zone_id: str
    recorded_at: datetime
    interval_seconds: int
    actual_kw: Decimal
    energy_kwh: Decimal
    baseline_kw: Decimal | None
    std_dev_kw: Decimal | None
    z_score: Decimal | None
    power_factor: Decimal
    tariff_period: str
    ambient_temp_c: Decimal | None


def resolve_window_bounds(
    *,
    time_window: SummaryWindow,
    anchor_utc: datetime,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> tuple[datetime, datetime, datetime, datetime]:
    """Return (window_start, window_end, previous_start, previous_end) in UTC."""
    if start_at is not None and end_at is not None:
        w_start = start_at.astimezone(UTC)
        w_end = end_at.astimezone(UTC)
        span = w_end - w_start
        if span.total_seconds() <= 0:
            span = timedelta(hours=24)
        return w_start, w_end, w_start - span, w_start

    w_end = (end_at or anchor_utc).astimezone(UTC)
    if time_window == "24h":
        span = timedelta(hours=24)
    elif time_window == "7d":
        span = timedelta(days=7)
    else:
        span = timedelta(days=30)

    w_start = w_end - span
    return w_start, w_end, w_start - span, w_start


def compute_trend_pct(current_kwh: float, previous_kwh: float, previous_count: int) -> float | None:
    """Return percentage delta against prior period, or None if prior period has no readings."""
    if previous_count <= 0 or previous_kwh <= 0:
        return None
    return round(((current_kwh - previous_kwh) / previous_kwh) * 100.0, 2)


def compute_interval_demand_stats(samples: list[SummarySampleRow]) -> tuple[float, float]:
    """Return exact (avg_demand_kw, peak_demand_kw) across concurrent timestamp intervals."""
    if not samples:
        return 0.0, 0.0
    kw_by_ts: dict[datetime, float] = {}
    for s in samples:
        kw_by_ts[s.recorded_at] = kw_by_ts.get(s.recorded_at, 0.0) + float(s.actual_kw)
    avg_kw = round(sum(kw_by_ts.values()) / len(kw_by_ts), 2)
    peak_kw = round(max(kw_by_ts.values()), 2)
    return avg_kw, peak_kw


def derive_health_status(
    *,
    latest_pf: float | None,
    open_critical_or_high: int,
    open_elevated: int,
    fallback_status: str = "Nominal",
) -> str:
    """Derive live operational health status from anomalies and power factor telemetry."""
    if open_critical_or_high > 0 or (latest_pf is not None and latest_pf < 0.85):
        return "Fault"
    if open_elevated > 0 or (latest_pf is not None and latest_pf < 0.90):
        return "Warning"
    if latest_pf is not None:
        return "Nominal"
    return fallback_status


def _bucket_key_and_label(
    dt_utc: datetime,
    *,
    time_window: SummaryWindow,
    span_hours: float,
    tz: ZoneInfo,
) -> tuple[str, str]:
    local = dt_utc.astimezone(tz)
    if time_window == "24h" or span_hours <= 36:
        return (
            local.strftime("%Y-%m-%d %H:%M"),
            local.strftime("%H:%M"),
        )
    if time_window == "7d" or span_hours <= 24 * 10:
        hour6 = (local.hour // 6) * 6
        return (
            f"{local.strftime('%Y-%m-%d')} {hour6:02d}:00",
            f"{local.strftime('%m/%d')} {hour6:02d}h",
        )
    return (
        f"{local.strftime('%Y-%m-%d')} 00:00",
        local.strftime("%m/%d"),
    )


def build_series_and_heatmap(
    samples: list[SummarySampleRow],
    *,
    time_window: SummaryWindow,
    window_start: datetime,
    window_end: datetime,
    timezone_name: str = "UTC",
) -> tuple[list[dict[str, object]], list[list[int]]]:
    """Compute multi-meter concurrent time-series buckets and 7x24 weekday-hour heatmap."""
    heatmap = [[0 for _ in range(24)] for _ in range(7)]
    if not samples:
        return [], heatmap

    tz = ZoneInfo(timezone_name)
    span_hours = max(1.0, (window_end - window_start).total_seconds() / 3600.0)
    sorted_samples = sorted(samples, key=lambda s: s.recorded_at)

    # 1. Series bucketing
    buckets: dict[str, dict[str, object]] = {}
    tariff_rank = {"Peak": 3, "Mid-Peak": 2, "Off-Peak": 1}

    # 2. Heatmap day-hour-meter accumulators
    day_hour_meter: dict[tuple[int, int, str], dict[str, list[float]]] = {}

    for s in sorted_samples:
        key, label = _bucket_key_and_label(
            s.recorded_at, time_window=time_window, span_hours=span_hours, tz=tz
        )
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "timestamp": key,
                "label": label,
                "first_at": s.recorded_at.isoformat(),
                "by_meter": {},
                "pfs": [],
                "temps": [],
                "tariff": s.tariff_period,
                "max_z": None,
                "zone_id": s.zone_id,
            }
            buckets[key] = bucket

        by_meter: dict[str, list[SummarySampleRow]] = bucket["by_meter"]  # type: ignore[assignment]
        by_meter.setdefault(s.meter_id, []).append(s)

        pfs: list[float] = bucket["pfs"]  # type: ignore[assignment]
        pfs.append(float(s.power_factor))

        if s.ambient_temp_c is not None:
            temps: list[float] = bucket["temps"]  # type: ignore[assignment]
            temps.append(float(s.ambient_temp_c))

        if tariff_rank.get(s.tariff_period, 0) > tariff_rank.get(str(bucket["tariff"]), 0):
            bucket["tariff"] = s.tariff_period

        if s.z_score is not None:
            z = float(s.z_score)
            cur_max = bucket["max_z"]
            if cur_max is None or z > float(cur_max):
                bucket["max_z"] = z

        # Heatmap accumulation
        local = s.recorded_at.astimezone(tz)
        date_str = local.strftime("%Y-%m-%d")
        slot_key = (local.weekday(), local.hour, date_str)
        slot_meters = day_hour_meter.setdefault(slot_key, {})
        slot_meters.setdefault(s.meter_id, []).append(float(s.actual_kw))

    series_out: list[dict[str, object]] = []
    for bucket in buckets.values():
        by_meter = bucket["by_meter"]  # type: ignore[assignment]
        actual_kw = 0.0
        baseline_kw = 0.0
        std_sq_sum = 0.0
        has_baseline = False

        for meter_rows in by_meter.values():
            avg_act = sum(float(r.actual_kw) for r in meter_rows) / len(meter_rows)
            actual_kw += avg_act
            baselined = [r for r in meter_rows if r.baseline_kw is not None]
            if baselined:
                has_baseline = True
                baseline_kw += sum(float(r.baseline_kw) for r in baselined if r.baseline_kw is not None) / len(baselined)
                avg_std = sum(float(r.std_dev_kw or 0) for r in baselined) / len(baselined)
                std_sq_sum += avg_std * avg_std
            else:
                baseline_kw += avg_act

        rounded_actual = round(actual_kw, 1)
        rounded_baseline = round(baseline_kw if has_baseline else actual_kw, 1)
        std_dev_kw = round(math.sqrt(std_sq_sum), 1)
        max_z = bucket["max_z"]
        if max_z is not None:
            z_score = round(float(max_z), 2)
        elif std_dev_kw > 0:
            z_score = round((rounded_actual - rounded_baseline) / std_dev_kw, 2)
        else:
            z_score = 0.0

        pfs = bucket["pfs"]  # type: ignore[assignment]
        avg_pf = round(sum(pfs) / len(pfs), 2) if pfs else 0.0
        temps = bucket["temps"]  # type: ignore[assignment]
        avg_temp = round(sum(temps) / len(temps), 1) if temps else 0.0

        series_out.append(
            {
                "timestamp": bucket["timestamp"],
                "label": bucket["label"],
                "actual_kw": rounded_actual,
                "baseline_kw": rounded_baseline,
                "std_dev_kw": std_dev_kw,
                "has_baseline": has_baseline,
                "power_factor": avg_pf,
                "tariff_period": bucket["tariff"],
                "ambient_temp_c": avg_temp,
                "z_score": z_score,
                "zone_id": bucket["zone_id"],
            }
        )

    weekday_hour_totals: list[list[list[float]]] = [[[] for _ in range(24)] for _ in range(7)]
    for (weekday, hour, _date_str), meter_vals in day_hour_meter.items():
        slot_total = sum(sum(vals) / len(vals) for vals in meter_vals.values())
        weekday_hour_totals[weekday][hour].append(slot_total)

    for d in range(7):
        for h in range(24):
            vals = weekday_hour_totals[d][h]
            if vals:
                heatmap[d][h] = round(sum(vals) / len(vals))

    return series_out, heatmap
