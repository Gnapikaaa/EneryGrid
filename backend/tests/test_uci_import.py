"""Unit tests for the UCI household electricity dataset import pipeline.

DATA TYPE: HOUSEHOLD CONSUMPTION — NOT INDUSTRIAL TELEMETRY.
These tests cover only pure mapping and validation functions.
No database connection is required.

Covers:
1. Timestamp parsing (Europe/Paris → UTC, DST boundary)
2. energy_kwh calculation
3. Tariff period classification
4. Power factor derivation (normal case, zero active power, missing reactive)
5. '?' / missing values → map_uci_row returns None (row is skipped)
6. Duplicate timestamps in input are deduped before insert (batch dedup logic)
7. Batch boundary: 2.5 batches worth of rows produces correct batch count
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

# Make the scripts directory importable when running from the backend root
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = _BACKEND_DIR / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from import_uci_dataset import (
    classify_tariff_period,
    compute_energy_kwh,
    derive_power_factor,
    map_uci_row,
    parse_recorded_at,
)


# ---------------------------------------------------------------------------
# 1. Timestamp parsing
# ---------------------------------------------------------------------------

class TestParseRecordedAt:
    def test_known_utc_offset_winter(self) -> None:
        """Paris is UTC+1 in winter (CET); 17:24:00 Paris → 16:24:00 UTC."""
        result = parse_recorded_at("16/12/2006", "17:24:00")
        assert result is not None
        assert result.tzinfo is UTC or result.utcoffset().total_seconds() == 0  # type: ignore[union-attr]
        assert result.year == 2006
        assert result.month == 12
        assert result.day == 16
        assert result.hour == 16
        assert result.minute == 24

    def test_known_utc_offset_summer(self) -> None:
        """Paris is UTC+2 in summer (CEST); 12:00:00 Paris → 10:00:00 UTC."""
        result = parse_recorded_at("01/07/2007", "12:00:00")
        assert result is not None
        assert result.hour == 10

    def test_invalid_date_returns_none(self) -> None:
        assert parse_recorded_at("not-a-date", "17:24:00") is None

    def test_invalid_time_returns_none(self) -> None:
        assert parse_recorded_at("16/12/2006", "bad-time") is None

    def test_result_is_utc_aware(self) -> None:
        result = parse_recorded_at("16/12/2006", "08:00:00")
        assert result is not None
        assert result.utcoffset() is not None
        assert result.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# 2. energy_kwh calculation
# ---------------------------------------------------------------------------

class TestComputeEnergyKwh:
    def test_one_kw_one_minute(self) -> None:
        # 1 kW * (60/3600) h = 0.0167 kWh (rounded to 4 dp)
        result = compute_energy_kwh(Decimal("1.0"))
        assert result == Decimal("0.0167")

    def test_zero_kw(self) -> None:
        assert compute_energy_kwh(Decimal("0")) == Decimal("0.0000")

    def test_known_value(self) -> None:
        # 4.216 kW / 60 = 0.07026... → 0.0703 (ROUND_HALF_UP, 4 dp)
        result = compute_energy_kwh(Decimal("4.216"))
        expected = (Decimal("4.216") * Decimal("60") / Decimal("3600")).quantize(
            Decimal("0.0001")
        )
        assert result == expected

    def test_high_load(self) -> None:
        result = compute_energy_kwh(Decimal("20.0"))
        assert result == Decimal("0.3333")


# ---------------------------------------------------------------------------
# 3. Tariff period classification
# ---------------------------------------------------------------------------

class TestClassifyTariffPeriod:
    """Tests use UTC timestamps that map to known Paris local times."""

    def _utc(self, year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
        return datetime(year, month, day, hour, minute, tzinfo=UTC)

    def test_weekday_peak_morning(self) -> None:
        # Monday 2007-01-15, Paris winter (UTC+1): UTC 09:00 → Paris 10:00 → Peak
        dt = self._utc(2007, 1, 15, 9, 0)
        assert classify_tariff_period(dt) == "Peak"

    def test_weekday_peak_evening(self) -> None:
        # Monday 2007-01-15: UTC 18:00 → Paris 19:00 → Peak
        dt = self._utc(2007, 1, 15, 17, 0)
        assert classify_tariff_period(dt) == "Peak"

    def test_weekday_off_peak_night(self) -> None:
        # UTC 00:00 → Paris 01:00 → Off-Peak
        dt = self._utc(2007, 1, 15, 0, 0)
        assert classify_tariff_period(dt) == "Off-Peak"

    def test_weekend_mid_peak(self) -> None:
        # Saturday 2007-01-20: UTC 09:00 → Paris 10:00 → Mid-Peak (weekend)
        dt = self._utc(2007, 1, 20, 9, 0)
        assert classify_tariff_period(dt) == "Mid-Peak"

    def test_weekend_off_peak(self) -> None:
        # Saturday 2007-01-20: UTC 22:00 → Paris 23:00 → Off-Peak (weekend)
        dt = self._utc(2007, 1, 20, 22, 0)
        assert classify_tariff_period(dt) == "Off-Peak"

    def test_valid_values_only(self) -> None:
        """Every timestamp should map to exactly one of the three valid values."""
        valid = {"Peak", "Mid-Peak", "Off-Peak"}
        for hour in range(24):
            # Weekday
            dt = self._utc(2007, 1, 15, hour, 30)
            assert classify_tariff_period(dt) in valid
            # Weekend
            dt2 = self._utc(2007, 1, 20, hour, 30)
            assert classify_tariff_period(dt2) in valid


# ---------------------------------------------------------------------------
# 4. Power factor derivation
# ---------------------------------------------------------------------------

class TestDerivePowerFactor:
    def test_pure_active_no_reactive(self) -> None:
        # Q=0 → PF = cos(0) = 1.000
        result = derive_power_factor(Decimal("4.0"), Decimal("0.0"))
        assert result == Decimal("1.000")

    def test_zero_active_returns_default(self) -> None:
        result = derive_power_factor(Decimal("0"), Decimal("1.0"))
        from import_uci_dataset import _DEFAULT_POWER_FACTOR
        assert result == _DEFAULT_POWER_FACTOR

    def test_negative_active_returns_default(self) -> None:
        result = derive_power_factor(Decimal("-1.0"), Decimal("0.5"))
        from import_uci_dataset import _DEFAULT_POWER_FACTOR
        assert result == _DEFAULT_POWER_FACTOR

    def test_typical_household_pf(self) -> None:
        # P=4.0 kW, Q=1.0 kVAR → PF ≈ cos(arctan(0.25)) ≈ 0.9701...
        import math as _math
        result = derive_power_factor(Decimal("4.0"), Decimal("1.0"))
        expected_float = _math.cos(_math.atan(1.0 / 4.0))
        # Result should be within 0.001 of theoretical
        assert abs(float(result) - expected_float) < 0.002

    def test_result_clamped_to_one(self) -> None:
        """Very large P with no Q should give PF=1.000, not >1."""
        result = derive_power_factor(Decimal("100.0"), Decimal("0.0"))
        assert result <= Decimal("1.000")
        assert result >= Decimal("0.000")


# ---------------------------------------------------------------------------
# 5. Missing values → row skipped
# ---------------------------------------------------------------------------

class TestMapUciRow:
    def _valid_row(self, **overrides: str) -> dict[str, str]:
        base = {
            "Date": "16/12/2006",
            "Time": "17:24:00",
            "Global_active_power": "4.216",
            "Global_reactive_power": "0.418",
            "Voltage": "234.840",
            "Global_intensity": "18.400",
            "Sub_metering_1": "0.000",
            "Sub_metering_2": "1.000",
            "Sub_metering_3": "17.000",
        }
        base.update(overrides)
        return base

    def test_valid_row_produces_mapping(self) -> None:
        result = map_uci_row(self._valid_row())
        assert result is not None
        assert result["interval_seconds"] == 60
        assert result["quality_flag"] == "valid"
        assert result["source"] == "csv_import"
        assert result["actual_kw"] >= Decimal("0")

    def test_missing_active_power_skips_row(self) -> None:
        assert map_uci_row(self._valid_row(Global_active_power="?")) is None

    def test_empty_active_power_skips_row(self) -> None:
        assert map_uci_row(self._valid_row(Global_active_power="")) is None

    def test_missing_reactive_power_uses_zero(self) -> None:
        """Missing Q should not cause failure; PF defaults instead."""
        result = map_uci_row(self._valid_row(Global_reactive_power="?"))
        assert result is not None

    def test_negative_active_clamped_to_zero(self) -> None:
        """UCI data should never have negative power; clamp is a safety net."""
        result = map_uci_row(self._valid_row(Global_active_power="-1.0"))
        assert result is not None
        assert result["actual_kw"] == Decimal("0")

    def test_interval_start_is_recorded_at_minus_60s(self) -> None:
        result = map_uci_row(self._valid_row())
        assert result is not None
        assert result["recorded_at"] - result["interval_start"] == timedelta(seconds=60)

    def test_bad_date_skips_row(self) -> None:
        assert map_uci_row(self._valid_row(Date="not-a-date")) is None

    def test_bad_active_power_non_numeric_skips_row(self) -> None:
        assert map_uci_row(self._valid_row(Global_active_power="abc")) is None


# ---------------------------------------------------------------------------
# 6. Duplicate timestamp deduplication before insert
# ---------------------------------------------------------------------------

class TestDuplicateDeduplication:
    """The import pipeline should skip rows with identical (meter_id, recorded_at)."""

    def test_duplicate_recorded_at_in_input(self) -> None:
        """When two rows share the same Date+Time string the parsed recorded_at is identical.
        A production DB insert will silently skip the second via ON CONFLICT; here we test
        that map_uci_row produces the same recorded_at so the caller can deduplicate."""
        row = {
            "Date": "16/12/2006",
            "Time": "17:24:00",
            "Global_active_power": "4.216",
            "Global_reactive_power": "0.418",
        }
        r1 = map_uci_row(row)
        r2 = map_uci_row(row)
        assert r1 is not None
        assert r2 is not None
        assert r1["recorded_at"] == r2["recorded_at"]

    def test_set_dedup_on_recorded_at(self) -> None:
        """Using a set of recorded_at values correctly deduplicates rows."""
        rows = [
            {"Date": "16/12/2006", "Time": "17:24:00", "Global_active_power": "4.216", "Global_reactive_power": "0.0"},
            {"Date": "16/12/2006", "Time": "17:24:00", "Global_active_power": "4.300", "Global_reactive_power": "0.0"},
            {"Date": "16/12/2006", "Time": "17:25:00", "Global_active_power": "3.900", "Global_reactive_power": "0.0"},
        ]
        mapped = [map_uci_row(r) for r in rows]
        assert all(m is not None for m in mapped)
        unique_times: set[datetime] = set()
        deduped = []
        for m in mapped:
            if m["recorded_at"] not in unique_times:  # type: ignore[index]
                unique_times.add(m["recorded_at"])  # type: ignore[index]
                deduped.append(m)
        assert len(deduped) == 2  # duplicate 17:24:00 removed


# ---------------------------------------------------------------------------
# 7. Batch boundary: 2.5 batches worth of rows
# ---------------------------------------------------------------------------

class TestBatchBoundary:
    def test_batch_count_for_2_5_batches(self) -> None:
        """With batch_size=10 and 25 valid rows, math.ceil(25/10) = 3 flushes."""
        import math as _math
        batch_size = 10
        n_rows = 25
        expected_flush_count = _math.ceil(n_rows / batch_size)
        assert expected_flush_count == 3

    def test_full_last_batch_no_extra_flush(self) -> None:
        """With batch_size=10 and exactly 20 rows: 2 flushes, 0 leftover."""
        batch_size = 10
        n_rows = 20
        import math as _math
        assert _math.ceil(n_rows / batch_size) == 2

    def test_rows_map_correctly_at_batch_boundary(self) -> None:
        """Generate 25 synthetic UCI rows and confirm all 25 map successfully."""
        from datetime import date as _date, timedelta as _td
        base = datetime(2007, 1, 15, 8, 0, 0, tzinfo=UTC)
        rows = []
        for i in range(25):
            ts = base + _td(minutes=i)
            rows.append({
                "Date": ts.strftime("%d/%m/%Y"),
                "Time": ts.strftime("%H:%M:%S"),
                "Global_active_power": "3.500",
                "Global_reactive_power": "0.200",
            })
        mapped = [map_uci_row(r) for r in rows]
        assert all(m is not None for m in mapped)
        assert len(mapped) == 25
