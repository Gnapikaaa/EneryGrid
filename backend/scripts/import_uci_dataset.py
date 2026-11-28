#!/usr/bin/env python3
"""
UCI Household Electric Power Consumption — EnergyGrid import pipeline.

╔══════════════════════════════════════════════════════════════════════════╗
║  NOTICE: THIS DATA IS HOUSEHOLD CONSUMPTION DATA — NOT INDUSTRIAL DATA  ║
║  Source: UCI ML Repository dataset #235                                  ║
║  License: CC BY 4.0  (https://creativecommons.org/licenses/by/4.0/)     ║
║  For TEST / STAGING environments only. Never import to production.       ║
╚══════════════════════════════════════════════════════════════════════════╝

Dataset:
    "Individual Household Electric Power Consumption" by Georges Hebrail
    and Alice Berard, UCI Machine Learning Repository (2012).
    URL: https://archive.ics.uci.edu/dataset/235/individual+household+electric+power+consumption

Usage:
    python scripts/import_uci_dataset.py \\
        --csv-path /path/to/household_power_consumption.txt \\
        --db-url postgresql+psycopg://user:pass@host/db \\
        --facility-id uci-household-001 \\
        --batch-size 1000 \\
        [--dry-run]

Schema mapping summary:
    Date + Time  → recorded_at (Europe/Paris → UTC), interval_seconds=60
    Global_active_power (kW) → actual_kw (clamp ≥ 0)
    energy_kwh = actual_kw * (60 / 3600) = actual_kw / 60
    Power factor = cos(arctan(Q/P)) from Global_reactive_power / Global_active_power
    Tariff period = time-of-use schedule (Europe/Paris local time)
    quality_flag = 'valid'; rows with '?' in key fields are SKIPPED (not inserted)
    source = 'csv_import'

Missing values ('?'):
    Rows where Global_active_power == '?' are SKIPPED entirely.
    This keeps the schema clean; the script logs how many were skipped.
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_FACILITY_ID_DEFAULT = "uci-household-001"
_FACILITY_CODE = "UCI-HH001"
_FACILITY_NAME = "UCI Household (Test/Staging) — NOT Industrial Data"
_ZONE_SLUG = "main"
_ZONE_NAME = "Main Household Zone"
_METER_CODE = "UCI-M001"
_METER_EQUIPMENT_NAME = "UCI Household Electricity Meter (1-min interval)"
_METER_RATED_KW = Decimal("20.0")  # generous ceiling for household data
_METER_NOMINAL_INTERVAL = 60  # 1-minute intervals
_METER_POWER_FACTOR_DEFAULT = Decimal("0.95")
_METER_THD_PCT = Decimal("0.00")

_INTERVAL_SECONDS = 60
_ENERGY_SCALE = Decimal(_INTERVAL_SECONDS) / Decimal(3600)
_DEFAULT_POWER_FACTOR = Decimal("0.95")


# ---------------------------------------------------------------------------
# Field mapping helpers — pure functions; tested independently
# ---------------------------------------------------------------------------

def parse_recorded_at(date_str: str, time_str: str) -> datetime | None:
    """Parse UCI Date/Time strings (Europe/Paris) → UTC datetime.

    Args:
        date_str: e.g. '16/12/2006'
        time_str: e.g. '17:24:00'

    Returns:
        UTC-aware datetime, or None if parsing fails.
    """
    from zoneinfo import ZoneInfo
    try:
        paris = ZoneInfo("Europe/Paris")
        local_dt = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M:%S")
        return local_dt.replace(tzinfo=paris).astimezone(UTC)
    except (ValueError, KeyError):
        return None


def compute_energy_kwh(actual_kw: Decimal) -> Decimal:
    """Compute energy in kWh for one 1-minute interval.

    energy_kwh = actual_kw * (60 s / 3600 s/h)

    Returns value rounded to 4 decimal places.
    """
    return (actual_kw * _ENERGY_SCALE).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def derive_power_factor(active_kw: Decimal, reactive_kw: Decimal) -> Decimal:
    """Derive power factor from active and reactive power.

    PF = cos(arctan(Q / P)) where Q = reactive power, P = active power.
    Falls back to _DEFAULT_POWER_FACTOR when active_kw ≤ 0 (avoid div-by-zero).
    Result is clamped to [0, 1] and rounded to 3 decimal places.
    """
    if active_kw <= Decimal("0"):
        return _DEFAULT_POWER_FACTOR
    q_over_p = float(reactive_kw) / float(active_kw)
    pf = math.cos(math.atan(q_over_p))
    pf_decimal = Decimal(str(round(pf, 4)))
    # Clamp to valid range
    pf_decimal = max(Decimal("0.000"), min(Decimal("1.000"), pf_decimal))
    return pf_decimal.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def classify_tariff_period(recorded_at_utc: datetime) -> str:
    """Map UTC timestamp → tariff period using simple European TOU schedule.

    Converts to Europe/Paris local time, then applies:
        Peak:     09:00–12:00 and 18:00–22:00 on weekdays
        Mid-Peak: 06:00–09:00, 12:00–18:00, 22:00–23:59 on weekdays;
                  08:00–22:00 on weekends
        Off-Peak: all other hours

    Returns one of 'Peak', 'Mid-Peak', 'Off-Peak'.
    """
    from zoneinfo import ZoneInfo
    local_dt = recorded_at_utc.astimezone(ZoneInfo("Europe/Paris"))
    hour = local_dt.hour
    is_weekday = local_dt.weekday() < 5

    if is_weekday:
        if (9 <= hour < 12) or (18 <= hour < 22):
            return "Peak"
        if (6 <= hour < 9) or (12 <= hour < 18) or (22 <= hour <= 23):
            return "Mid-Peak"
        return "Off-Peak"

    if 8 <= hour < 22:
        return "Mid-Peak"
    return "Off-Peak"


def map_uci_row(row: dict[str, str]) -> dict[str, Any] | None:
    """Map one raw UCI CSV row dict to EnergyGrid telemetry fields.

    Returns None if the row should be skipped (missing value '?').
    """
    date_str = row.get("Date", "").strip()
    time_str = row.get("Time", "").strip()
    gap_str = row.get("Global_active_power", "").strip()
    grp_str = row.get("Global_reactive_power", "").strip()

    # Skip rows with missing values in key fields
    if not gap_str or gap_str == "?":
        return None

    # Parse numeric fields
    try:
        active_kw = max(Decimal("0"), Decimal(gap_str))
    except Exception:
        return None

    try:
        reactive_kw = Decimal("0") if (not grp_str or grp_str == "?") else Decimal(grp_str)
    except Exception:
        reactive_kw = Decimal("0")

    recorded_at = parse_recorded_at(date_str, time_str)
    if recorded_at is None:
        return None

    energy_kwh = compute_energy_kwh(active_kw)
    power_factor = derive_power_factor(active_kw, reactive_kw)
    tariff_period = classify_tariff_period(recorded_at)
    interval_start = recorded_at - timedelta(seconds=_INTERVAL_SECONDS)

    return {
        "recorded_at": recorded_at,
        "interval_start": interval_start,
        "interval_seconds": _INTERVAL_SECONDS,
        "actual_kw": active_kw,
        "energy_kwh": energy_kwh,
        "power_factor": power_factor,
        "tariff_period": tariff_period,
        "quality_flag": "valid",
        "source": "csv_import",
        "ambient_temp_c": None,
        "baseline_status": "insufficient_history",
    }


# ---------------------------------------------------------------------------
# Facility / Zone / Meter seeding
# ---------------------------------------------------------------------------

def _seed_facility_zone_meter(session: Any, facility_id: str) -> tuple[Any, Any, Any]:
    """Create Facility, Zone, Meter for UCI data if they don't already exist.

    Returns (facility, zone, meter) ORM objects.
    """
    from datetime import date
    from app.models.facility import Facility, Zone, Meter

    facility = session.get(Facility, facility_id)
    if facility is None:
        facility = Facility(
            id=facility_id,
            code=_FACILITY_CODE,
            name=_FACILITY_NAME,
            location="Sceaux, Hauts-de-Seine, France",
            timezone="Europe/Paris",
            currency_code="EUR",
            contracted_demand_kw=Decimal("20.0"),
            off_peak_tariff_rate=Decimal("0.1000"),
            mid_peak_tariff_rate=Decimal("0.1500"),
            peak_tariff_rate=Decimal("0.2000"),
            is_active=True,
        )
        session.add(facility)
        session.flush()
        logger.info("Created facility %s", facility_id)

    # Find or create zone
    from sqlalchemy import select
    zone = session.scalar(
        select(Zone).where(
            Zone.facility_id == facility_id,
            Zone.slug == _ZONE_SLUG,
        )
    )
    if zone is None:
        zone = Zone(
            facility_id=facility_id,
            slug=_ZONE_SLUG,
            name=_ZONE_NAME,
            primary_meter_code=_METER_CODE,
            share_pct=Decimal("100.00"),
            status="Nominal",
            is_active=True,
        )
        session.add(zone)
        session.flush()
        logger.info("Created zone %s / %s", facility_id, _ZONE_SLUG)

    # Find or create meter
    meter = session.scalar(
        select(Meter).where(Meter.meter_code == _METER_CODE)
    )
    if meter is None:
        meter = Meter(
            facility_id=facility_id,
            zone_id=zone.id,
            meter_code=_METER_CODE,
            equipment_name=_METER_EQUIPMENT_NAME,
            rated_kw=_METER_RATED_KW,
            nominal_interval_seconds=_METER_NOMINAL_INTERVAL,
            current_kw=Decimal("0.00"),
            power_factor=_METER_POWER_FACTOR_DEFAULT,
            thd_pct=_METER_THD_PCT,
            status="Nominal",
            last_calibrated_at=date(2006, 12, 16),
            is_active=True,
        )
        session.add(meter)
        session.flush()
        logger.info("Created meter %s", _METER_CODE)

    return facility, zone, meter


# ---------------------------------------------------------------------------
# Main import pipeline
# ---------------------------------------------------------------------------

def import_uci_dataset(
    *,
    csv_path: Path,
    db_url: str,
    facility_id: str = _FACILITY_ID_DEFAULT,
    batch_size: int = 1000,
    dry_run: bool = False,
) -> dict[str, int]:
    """Import UCI household electricity dataset into EnergyGrid telemetry_readings.

    Args:
        csv_path: Path to the UCI CSV file (semicolon-delimited).
        db_url: SQLAlchemy PostgreSQL connection URL for the TEST database.
        facility_id: Target facility ID (will be created if absent).
        batch_size: Rows per commit batch.
        dry_run: If True, parse and validate rows but do not write to DB.

    Returns:
        dict with keys: total_read, inserted, skipped_missing, skipped_duplicate, errors
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import sessionmaker

    from app.models.telemetry import TelemetryReading

    print("=" * 72)
    print("UCI HOUSEHOLD ELECTRICITY DATA IMPORT")
    print("DATA TYPE : HOUSEHOLD CONSUMPTION — NOT INDUSTRIAL TELEMETRY")
    print("ENV       : TEST / STAGING ONLY — NEVER IMPORT TO PRODUCTION")
    print(f"SOURCE    : {csv_path}")
    print(f"FACILITY  : {facility_id}")
    print(f"DRY-RUN   : {dry_run}")
    print("=" * 72)

    engine = create_engine(db_url, pool_pre_ping=True, future=True)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    counters = {
        "total_read": 0,
        "inserted": 0,
        "skipped_missing": 0,
        "skipped_duplicate": 0,
        "errors": 0,
    }

    with Session() as session:
        if not dry_run:
            facility, zone, meter = _seed_facility_zone_meter(session, facility_id)
            session.commit()
        else:
            # In dry-run we still need meter_id; use a sentinel UUID
            meter = type("_FakeMeter", (), {
                "id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
                "facility_id": facility_id,
                "zone_id": uuid.UUID("00000000-0000-0000-0000-000000000002"),
            })()
            zone = type("_FakeZone", (), {"id": meter.zone_id})()

        batch: list[TelemetryReading] = []

        def _flush_batch() -> None:
            if dry_run or not batch:
                batch.clear()
                return
            try:
                session.bulk_save_objects(batch)
                session.commit()
                counters["inserted"] += len(batch)
            except IntegrityError:
                session.rollback()
                # Row-by-row fallback to identify and skip duplicates
                for obj in batch:
                    try:
                        session.add(obj)
                        session.flush()
                        session.commit()
                        counters["inserted"] += 1
                    except IntegrityError:
                        session.rollback()
                        counters["skipped_duplicate"] += 1
                    except Exception:
                        session.rollback()
                        counters["errors"] += 1
                        logger.exception("Unexpected error inserting row recorded_at=%s", obj.recorded_at)
            except Exception:
                session.rollback()
                counters["errors"] += len(batch)
                logger.exception("Batch commit failed for %d rows", len(batch))
            finally:
                batch.clear()

        with open(csv_path, encoding="utf-8", newline="") as fh:
            # UCI file uses semicolon delimiter
            reader = csv.DictReader(fh, delimiter=";")
            for raw_row in reader:
                counters["total_read"] += 1

                mapped = map_uci_row(raw_row)
                if mapped is None:
                    counters["skipped_missing"] += 1
                    continue

                if dry_run:
                    # Validate mapping only; do not build ORM objects
                    counters["inserted"] += 1  # count as "would insert"
                    continue

                reading = TelemetryReading(
                    facility_id=meter.facility_id,
                    zone_id=meter.zone_id,
                    meter_id=meter.id,
                    interval_start=mapped["interval_start"],
                    recorded_at=mapped["recorded_at"],
                    interval_seconds=mapped["interval_seconds"],
                    actual_kw=mapped["actual_kw"],
                    energy_kwh=mapped["energy_kwh"],
                    baseline_kw=None,
                    std_dev_kw=None,
                    z_score=None,
                    baseline_status=mapped["baseline_status"],
                    power_factor=mapped["power_factor"],
                    tariff_period=mapped["tariff_period"],
                    ambient_temp_c=None,
                    quality_flag=mapped["quality_flag"],
                    source=mapped["source"],
                )
                batch.append(reading)

                if len(batch) >= batch_size:
                    _flush_batch()
                    logger.info(
                        "Progress: read=%d inserted=%d skipped_missing=%d skipped_dup=%d errors=%d",
                        counters["total_read"],
                        counters["inserted"],
                        counters["skipped_missing"],
                        counters["skipped_duplicate"],
                        counters["errors"],
                    )

        # Flush remainder
        _flush_batch()

    print("=" * 72)
    print("IMPORT COMPLETE" if not dry_run else "DRY-RUN COMPLETE (no data written)")
    for k, v in counters.items():
        print(f"  {k:<24} {v:>10,}")
    print("=" * 72)
    return counters


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Import UCI Household Electric Power Consumption dataset into EnergyGrid.\n"
            "\nDATA TYPE: HOUSEHOLD — NOT INDUSTRIAL. TEST/STAGING ONLY."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--csv-path", required=True, type=Path, help="Path to UCI semicolon-delimited CSV file")
    p.add_argument("--db-url", required=True, help="SQLAlchemy PostgreSQL URL for the TEST database")
    p.add_argument("--facility-id", default=_FACILITY_ID_DEFAULT, help="Target facility ID")
    p.add_argument("--batch-size", type=int, default=1000, help="Rows per commit batch (default 1000)")
    p.add_argument("--dry-run", action="store_true", help="Parse and validate without writing to DB")
    return p


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _build_parser().parse_args()

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        print(f"ERROR: CSV file not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    result = import_uci_dataset(
        csv_path=csv_path,
        db_url=args.db_url,
        facility_id=args.facility_id,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )
    sys.exit(0 if result["errors"] == 0 else 1)
