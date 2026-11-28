"""Pure dataset parsing and field-mapping adapters for real-world public energy datasets.

Zero ORM/web dependencies so unit tests and streaming CLI importers share exact
physical unit conversions, timezone localization, and interval validation.
"""

from __future__ import annotations

from collections.abc import Iterator
import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import io
import math
from typing import Literal, TextIO
from zoneinfo import ZoneInfo

DatasetFormat = Literal["uci_steel", "uci_household", "standard_csv"]

_KW_QUANT = Decimal("0.01")
_KWH_QUANT = Decimal("0.0001")
_PF_QUANT = Decimal("0.001")


@dataclass(frozen=True)
class NormalizedTelemetryRow:
    meter_code: str
    recorded_at: datetime
    interval_seconds: int
    actual_kw: Decimal
    energy_kwh: Decimal
    power_factor: Decimal
    ambient_temp_c: Decimal | None = None
    quality_flag: str = "valid"
    source: str = "csv_import"


@dataclass(frozen=True)
class DatasetParseStats:
    format_name: DatasetFormat
    total_rows_read: int
    emitted_rows: int
    skipped_missing_rows: int
    skipped_invalid_rows: int


def _parse_decimal(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned or cleaned in {"?", "NA", "NaN", "null", "NULL"}:
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _normalize_pf_value(raw_pf: Decimal) -> Decimal:
    """Convert either 0..1 ratio or 0..100 percentage power factor into 0.000..1.000."""
    ratio = raw_pf / Decimal("100") if raw_pf > Decimal("1") else raw_pf
    if ratio < Decimal("0"):
        ratio = Decimal("0")
    elif ratio > Decimal("1"):
        ratio = Decimal("1")
    return ratio.quantize(_PF_QUANT, rounding=ROUND_HALF_UP)


def compute_pf_from_pq(active_kw: Decimal, reactive_kvar: Decimal) -> Decimal:
    """Derive apparent power factor P / sqrt(P^2 + Q^2) from active & reactive power."""
    p = float(max(Decimal("0"), active_kw))
    q = float(reactive_kvar)
    apparent = math.hypot(p, q)
    if apparent <= 0.0:
        return Decimal("1.000")
    pf = max(0.0, min(1.0, p / apparent))
    return Decimal(f"{pf:.6f}").quantize(_PF_QUANT, rounding=ROUND_HALF_UP)


def iter_uci_steel_rows(
    stream: TextIO,
    *,
    meter_code: str,
    source_timezone: str = "Asia/Seoul",
    limit: int | None = None,
    stats_out: dict[str, int] | None = None,
) -> Iterator[NormalizedTelemetryRow]:
    """Stream-parse UCI #851 Steel Industry Energy Consumption CSV into EnergyGrid intervals.

    Dataset source: UCI Machine Learning Repository (ID #851, DAEWOO Steel Co., Ltd., 2018).
    Native resolution: 15-minute intervals (900s).
    Units: Usage_kWh (kWh per 15 min) -> actual_kw = Usage_kWh * 4; PF (%) -> 0..1.
    """
    tz = ZoneInfo(source_timezone)
    reader = csv.DictReader(stream)
    if reader.fieldnames is None:
        raise ValueError("UCI Steel CSV is empty or missing a header row.")

    normalized_fields = {name.strip() for name in reader.fieldnames if name}
    required = {"date", "Usage_kWh"}
    missing_cols = sorted(required - normalized_fields)
    if missing_cols:
        raise ValueError(
            f"UCI Steel CSV is missing required column(s): {', '.join(missing_cols)}."
        )

    total_read = 0
    emitted = 0
    skipped_missing = 0
    skipped_invalid = 0
    seen_utc: set[datetime] = set()

    for raw in reader:
        if limit is not None and emitted >= limit:
            break
        total_read += 1

        date_raw = (raw.get("date") or "").strip()
        kwh_val = _parse_decimal(raw.get("Usage_kWh"))
        if not date_raw or kwh_val is None:
            skipped_missing += 1
            continue
        if kwh_val < Decimal("0"):
            skipped_invalid += 1
            continue

        try:
            naive_dt = datetime.strptime(date_raw, "%d/%m/%Y %H:%M")
        except ValueError:
            try:
                naive_dt = datetime.fromisoformat(date_raw)
            except ValueError:
                skipped_invalid += 1
                continue

        if naive_dt.tzinfo is None:
            local_dt = naive_dt.replace(tzinfo=tz)
        else:
            local_dt = naive_dt
        recorded_at_utc = local_dt.astimezone(UTC)

        if recorded_at_utc in seen_utc:
            # Handle rare DST fall-back disambiguation safely
            recorded_at_utc = naive_dt.replace(tzinfo=tz, fold=1).astimezone(UTC)
            if recorded_at_utc in seen_utc:
                skipped_invalid += 1
                continue
        seen_utc.add(recorded_at_utc)

        lag_pf = _parse_decimal(raw.get("Lagging_Current_Power_Factor"))
        lead_pf = _parse_decimal(raw.get("Leading_Current_Power_Factor"))

        if lag_pf is not None and lag_pf > Decimal("0"):
            pf = _normalize_pf_value(lag_pf)
        elif lead_pf is not None and lead_pf > Decimal("0"):
            pf = _normalize_pf_value(lead_pf)
        else:
            pf = Decimal("1.000") if kwh_val == Decimal("0") else Decimal("0.000")

        energy_kwh = kwh_val.quantize(_KWH_QUANT, rounding=ROUND_HALF_UP)
        actual_kw = (energy_kwh * Decimal("4")).quantize(_KW_QUANT, rounding=ROUND_HALF_UP)

        emitted += 1
        yield NormalizedTelemetryRow(
            meter_code=meter_code,
            recorded_at=recorded_at_utc,
            interval_seconds=900,
            actual_kw=actual_kw,
            energy_kwh=energy_kwh,
            power_factor=pf,
            ambient_temp_c=None,
            quality_flag="valid",
            source="csv_import",
        )

    if stats_out is not None:
        stats_out["total_rows_read"] = total_read
        stats_out["emitted_rows"] = emitted
        stats_out["skipped_missing_rows"] = skipped_missing
        stats_out["skipped_invalid_rows"] = skipped_invalid


def iter_uci_household_rows(
    stream: TextIO,
    *,
    meter_code: str,
    source_timezone: str = "Europe/Paris",
    resample_minutes: int = 15,
    submeter_channel: Literal["total", "1", "2", "3"] = "total",
    limit: int | None = None,
    stats_out: dict[str, int] | None = None,
) -> Iterator[NormalizedTelemetryRow]:
    """Stream-parse UCI #235 Individual Household Electric Power Consumption (.txt).

    Dataset source: UCI Machine Learning Repository (ID #235, Sceaux, France, 2006-2010).
    Native resolution: 1-minute semicolon-delimited rows; resampled deterministically to
    `resample_minutes` (default 15m -> 900s) by averaging active power kW and deriving PF
    from Global_active_power (kW) & Global_reactive_power (kVAR).
    """
    if resample_minutes < 1 or resample_minutes > 1440:
        raise ValueError("resample_minutes must be between 1 and 1440.")

    tz = ZoneInfo(source_timezone)
    reader = csv.DictReader(stream, delimiter=";")
    if reader.fieldnames is None:
        raise ValueError("UCI Household file is empty or missing a header row.")

    normalized_fields = {name.strip() for name in reader.fieldnames if name}
    required = {"Date", "Time", "Global_active_power", "Global_reactive_power"}
    missing_cols = sorted(required - normalized_fields)
    if missing_cols:
        raise ValueError(
            f"UCI Household file is missing required column(s): {', '.join(missing_cols)}."
        )

    bucket_seconds = resample_minutes * 60
    total_read = 0
    emitted = 0
    skipped_missing = 0
    skipped_invalid = 0

    current_bucket_end: datetime | None = None
    bucket_kw: list[Decimal] = []
    bucket_kvar: list[Decimal] = []
    bucket_sub_wh: list[Decimal] = []

    def _flush_bucket(bucket_end: datetime) -> NormalizedTelemetryRow | None:
        if not bucket_kw:
            return None
        count = Decimal(len(bucket_kw))
        if submeter_channel == "total":
            avg_kw = (sum(bucket_kw) / count).quantize(_KW_QUANT, rounding=ROUND_HALF_UP)
        else:
            # Sub_metering_1/2/3 are measured in active watt-hours per 1-min step
            avg_wh_per_min = sum(bucket_sub_wh) / count
            avg_kw = (avg_wh_per_min * Decimal("0.06")).quantize(_KW_QUANT, rounding=ROUND_HALF_UP)

        energy_kwh = (avg_kw * Decimal(bucket_seconds) / Decimal(3600)).quantize(
            _KWH_QUANT, rounding=ROUND_HALF_UP
        )
        avg_total_p = sum(bucket_kw) / count
        avg_total_q = sum(bucket_kvar) / count
        pf = compute_pf_from_pq(avg_total_p, avg_total_q)

        return NormalizedTelemetryRow(
            meter_code=meter_code,
            recorded_at=bucket_end,
            interval_seconds=bucket_seconds,
            actual_kw=avg_kw,
            energy_kwh=energy_kwh,
            power_factor=pf,
            ambient_temp_c=None,
            quality_flag="valid",
            source="csv_import",
        )

    for raw in reader:
        if limit is not None and emitted >= limit:
            break
        total_read += 1

        date_str = (raw.get("Date") or "").strip()
        time_str = (raw.get("Time") or "").strip()
        p_kw = _parse_decimal(raw.get("Global_active_power"))
        q_kvar = _parse_decimal(raw.get("Global_reactive_power"))

        sub_wh: Decimal | None = None
        if submeter_channel != "total":
            sub_wh = _parse_decimal(raw.get(f"Sub_metering_{submeter_channel}"))
            if sub_wh is None:
                skipped_missing += 1
                continue

        if not date_str or not time_str or p_kw is None or q_kvar is None:
            skipped_missing += 1
            continue
        if p_kw < Decimal("0"):
            skipped_invalid += 1
            continue

        try:
            naive_dt = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M:%S")
        except ValueError:
            skipped_invalid += 1
            continue

        local_dt = naive_dt.replace(tzinfo=tz)
        utc_dt = local_dt.astimezone(UTC)

        # Align reading end timestamp onto fixed UTC grid multiples of bucket_seconds
        epoch_sec = int(utc_dt.timestamp())
        floored = (epoch_sec // bucket_seconds) * bucket_seconds
        bucket_end = datetime.fromtimestamp(floored + bucket_seconds, tz=UTC)

        if current_bucket_end is not None and bucket_end != current_bucket_end:
            row = _flush_bucket(current_bucket_end)
            bucket_kw.clear()
            bucket_kvar.clear()
            bucket_sub_wh.clear()
            if row is not None:
                emitted += 1
                yield row
                if limit is not None and emitted >= limit:
                    current_bucket_end = None
                    break

        current_bucket_end = bucket_end
        bucket_kw.append(p_kw)
        bucket_kvar.append(q_kvar)
        if sub_wh is not None:
            bucket_sub_wh.append(sub_wh)

    if current_bucket_end is not None and (limit is None or emitted < limit):
        row = _flush_bucket(current_bucket_end)
        if row is not None:
            emitted += 1
            yield row

    if stats_out is not None:
        stats_out["total_rows_read"] = total_read
        stats_out["emitted_rows"] = emitted
        stats_out["skipped_missing_rows"] = skipped_missing
        stats_out["skipped_invalid_rows"] = skipped_invalid


def rows_to_energygrid_csv_bytes(rows: list[NormalizedTelemetryRow]) -> bytes:
    """Serialize normalized telemetry rows into EnergyGrid's canonical CSV upload format."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "meter_code",
            "recorded_at",
            "interval_seconds",
            "actual_kw",
            "energy_kwh",
            "power_factor",
            "quality_flag",
            "source",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.meter_code,
                r.recorded_at.isoformat(),
                str(r.interval_seconds),
                f"{r.actual_kw:.2f}",
                f"{r.energy_kwh:.4f}",
                f"{r.power_factor:.3f}",
                r.quality_flag,
                r.source,
            ]
        )
    return buf.getvalue().encode("utf-8")
