"""CLI importer for real-world public energy consumption datasets into PostgreSQL.

Usage examples:
  python -m app.cli.import_dataset \\
      --format uci_steel \\
      --file data/Steel_industry_data.csv \\
      --facility-id steel-plant-01 \\
      --zone-slug main-plant \\
      --meter-code MTR-STEEL-01 \\
      --timezone Asia/Seoul \\
      --create-infrastructure \\
      --run-analytics
"""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
import io
from itertools import islice
from pathlib import Path
import sys
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.constants import HealthStatus, UserRole
from app.core.database import get_session_factory
from app.models.facility import Facility, Meter, Zone
from app.models.user import User
from app.schemas.analytics import AnalyticsProcessRequest
from app.services import analytics as analytics_service
from app.services import telemetry as telemetry_service
from app.services.dataset_adapters import (
    DatasetFormat,
    NormalizedTelemetryRow,
    iter_uci_household_rows,
    iter_uci_steel_rows,
    rows_to_energygrid_csv_bytes,
)


def _resolve_import_actor(db: Session, actor_email: str | None) -> User:
    if actor_email:
        user = db.scalar(select(User).where(User.email == actor_email.strip().lower()))
        if user is None or not user.is_active:
            raise ValueError(f"Active operator account '{actor_email}' was not found.")
        if user.role not in (UserRole.ADMIN.value, UserRole.UTILITY_ENGINEER.value):
            raise ValueError(
                f"Account '{actor_email}' has role '{user.role}'; admin or utility_engineer is required."
            )
        return user

    actor = db.scalar(
        select(User)
        .where(
            User.is_active.is_(True),
            User.role.in_([UserRole.ADMIN.value, UserRole.UTILITY_ENGINEER.value]),
        )
        .order_by(User.created_at.asc())
        .limit(1)
    )
    if actor is None:
        raise ValueError(
            "No active admin or utility_engineer account exists in PostgreSQL. "
            "Run 'python -m app.cli.create_admin' before importing telemetry."
        )
    return actor


def _ensure_target_meter(
    db: Session,
    *,
    facility_id: str,
    facility_name: str,
    facility_code: str,
    facility_location: str,
    timezone_name: str,
    currency_code: str,
    contracted_demand_kw: Decimal,
    zone_slug: str,
    zone_name: str,
    meter_code: str,
    equipment_name: str,
    rated_kw: Decimal,
    nominal_interval_seconds: int,
    create_infrastructure: bool,
) -> Meter:
    meter = db.scalar(select(Meter).where(Meter.meter_code == meter_code))
    if meter is not None:
        if meter.facility_id != facility_id:
            raise ValueError(
                f"Meter '{meter_code}' already exists under facility '{meter.facility_id}', not '{facility_id}'."
            )
        if meter.nominal_interval_seconds != nominal_interval_seconds:
            raise ValueError(
                f"Meter '{meter_code}' expects interval {meter.nominal_interval_seconds}s, "
                f"but dataset adapter produces {nominal_interval_seconds}s intervals."
            )
        return meter

    if not create_infrastructure:
        raise ValueError(
            f"Meter '{meter_code}' does not exist in PostgreSQL. Register it first or pass --create-infrastructure."
        )

    facility = db.get(Facility, facility_id)
    if facility is None:
        facility = Facility(
            id=facility_id,
            code=facility_code,
            name=facility_name,
            location=facility_location,
            timezone=timezone_name,
            currency_code=currency_code,
            contracted_demand_kw=contracted_demand_kw,
            off_peak_tariff_rate=Decimal("0.0950"),
            mid_peak_tariff_rate=Decimal("0.1350"),
            peak_tariff_rate=Decimal("0.1950"),
            is_active=True,
            deactivated_at=None,
        )
        db.add(facility)
        db.flush()

    zone = db.scalar(
        select(Zone).where(Zone.facility_id == facility_id, Zone.slug == zone_slug)
    )
    if zone is None:
        zone = Zone(
            facility_id=facility_id,
            slug=zone_slug,
            name=zone_name,
            primary_meter_code=meter_code,
            share_pct=Decimal("100.00"),
            status=HealthStatus.NOMINAL.value,
            is_active=True,
            deactivated_at=None,
        )
        db.add(zone)
        db.flush()

    meter = Meter(
        facility_id=facility_id,
        zone_id=zone.id,
        meter_code=meter_code,
        equipment_name=equipment_name,
        rated_kw=rated_kw,
        nominal_interval_seconds=nominal_interval_seconds,
        current_kw=Decimal("0.00"),
        power_factor=Decimal("0.950"),
        thd_pct=Decimal("2.50"),
        status=HealthStatus.NOMINAL.value,
        last_calibrated_at=date.today(),
        is_active=True,
        deactivated_at=None,
    )
    db.add(meter)
    db.commit()
    db.refresh(meter)
    return meter


def run_dataset_import(
    db: Session,
    *,
    settings: Settings,
    dataset_format: DatasetFormat,
    file_path: Path,
    facility_id: str,
    meter_code: str,
    actor_email: str | None = None,
    source_timezone: str | None = None,
    resample_minutes: int = 15,
    submeter_channel: str = "total",
    chunk_size: int = 2000,
    limit: int | None = None,
    create_infrastructure: bool = False,
    run_analytics: bool = False,
) -> dict[str, int]:
    if not file_path.is_file():
        raise FileNotFoundError(f"Dataset file not found: {file_path}")

    resolved_chunk = max(1, min(chunk_size, settings.telemetry_max_csv_upload_rows))
    actor = _resolve_import_actor(db, actor_email)

    if dataset_format == "uci_steel":
        tz_name = source_timezone or "Asia/Seoul"
        interval_seconds = 900
        default_fac_name = "Daewoo Steel Industrial Plant (UCI #851)"
        default_fac_code = "UCI-STL851"
        default_location = "Gwangyang, South Korea"
        default_currency = "KRW"
        default_demand = Decimal("1200.00")
        default_rated = Decimal("600.00")
        default_zone_slug = "main-plant-feeder"
        default_zone_name = "Main Plant Utility Feeder"
        default_equipment = "Steel Plant Main Substation Meter"
    elif dataset_format == "uci_household":
        tz_name = source_timezone or "Europe/Paris"
        interval_seconds = resample_minutes * 60
        default_fac_name = "UCI Residential Reference Meter (UCI #235)"
        default_fac_code = "UCI-HH235"
        default_location = "Sceaux, France"
        default_currency = "EUR"
        default_demand = Decimal("25.00")
        default_rated = Decimal("15.00")
        default_zone_slug = f"circuit-{submeter_channel}"
        default_zone_name = f"Distribution Circuit ({submeter_channel})"
        default_equipment = f"Household Power Meter ({submeter_channel})"
    else:
        tz_name = source_timezone or "UTC"
        interval_seconds = 900
        default_fac_name = f"Imported Facility ({facility_id})"
        default_fac_code = facility_id.upper()[:32]
        default_location = "Imported CSV Site"
        default_currency = "USD"
        default_demand = Decimal("1500.00")
        default_rated = Decimal("800.00")
        default_zone_slug = "primary-zone"
        default_zone_name = "Primary Meter Zone"
        default_equipment = f"Meter {meter_code}"

    meter = _ensure_target_meter(
        db,
        facility_id=facility_id,
        facility_name=default_fac_name,
        facility_code=default_fac_code,
        facility_location=default_location,
        timezone_name=tz_name,
        currency_code=default_currency,
        contracted_demand_kw=default_demand,
        zone_slug=default_zone_slug,
        zone_name=default_zone_name,
        meter_code=meter_code,
        equipment_name=default_equipment,
        rated_kw=default_rated,
        nominal_interval_seconds=interval_seconds,
        create_infrastructure=create_infrastructure,
    )

    inserted = 0
    duplicates = 0
    overlaps = 0
    failed = 0
    parse_stats: dict[str, int] = {}

    if dataset_format == "standard_csv":
        raw_bytes = file_path.read_bytes()
        summary = telemetry_service.ingest_csv_bytes(
            db,
            actor=actor,
            csv_stream=io.BytesIO(raw_bytes),
            settings=settings,
            atomic=False,
        )
        inserted = summary.inserted_count
        duplicates = summary.duplicate_count
        overlaps = summary.overlap_count
        failed = summary.failed_count
    else:
        with file_path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            if dataset_format == "uci_steel":
                row_iter = iter_uci_steel_rows(
                    handle,
                    meter_code=meter.meter_code,
                    source_timezone=tz_name,
                    limit=limit,
                    stats_out=parse_stats,
                )
            else:
                row_iter = iter_uci_household_rows(
                    handle,
                    meter_code=meter.meter_code,
                    source_timezone=tz_name,
                    resample_minutes=resample_minutes,
                    submeter_channel=submeter_channel,  # type: ignore[arg-type]
                    limit=limit,
                    stats_out=parse_stats,
                )

            while True:
                batch: list[NormalizedTelemetryRow] = list(islice(row_iter, resolved_chunk))
                if not batch:
                    break
                csv_bytes = rows_to_energygrid_csv_bytes(batch)
                summary = telemetry_service.ingest_csv_bytes(
                    db,
                    actor=actor,
                    csv_stream=io.BytesIO(csv_bytes),
                    settings=settings,
                    atomic=False,
                )
                inserted += summary.inserted_count
                duplicates += summary.duplicate_count
                overlaps += summary.overlap_count
                failed += summary.failed_count

    anomalies_created = 0
    insights_updated = 0
    processed_readings = 0
    if run_analytics:
        cursor = None
        while True:
            proc = analytics_service.process_analytics_batch(
                db,
                actor=actor,
                payload=AnalyticsProcessRequest(
                    facility_id=facility_id,
                    meter_id=meter.id,
                    include_insights=True,
                    cursor=cursor,
                ),
                settings=settings,
            )
            processed_readings += proc.processed_readings
            anomalies_created += proc.anomalies_created
            insights_updated += proc.insights_created + proc.insights_updated
            if not proc.has_more or proc.next_cursor is None:
                break
            cursor = proc.next_cursor

    return {
        "total_rows_read": parse_stats.get("total_rows_read", inserted + duplicates + overlaps + failed),
        "emitted_rows": parse_stats.get("emitted_rows", inserted + duplicates + overlaps + failed),
        "skipped_missing_rows": parse_stats.get("skipped_missing_rows", 0),
        "skipped_invalid_rows": parse_stats.get("skipped_invalid_rows", 0),
        "inserted_count": inserted,
        "duplicate_count": duplicates,
        "overlap_count": overlaps,
        "failed_count": failed,
        "processed_readings": processed_readings,
        "anomalies_created": anomalies_created,
        "insights_updated": insights_updated,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.import_dataset",
        description="Import real public energy telemetry datasets (UCI Steel / UCI Household / CSV) into PostgreSQL.",
    )
    parser.add_argument(
        "--format",
        required=True,
        choices=["uci_steel", "uci_household", "standard_csv"],
        help="Input dataset format adapter.",
    )
    parser.add_argument("--file", required=True, help="Local path to dataset CSV/TXT file.")
    parser.add_argument("--facility-id", required=True, help="Target facility slug ID.")
    parser.add_argument("--meter-code", required=True, help="Target meter code.")
    parser.add_argument("--actor-email", default=None, help="Admin/engineer email recorded for analytics.")
    parser.add_argument("--timezone", default=None, help="Source timestamp IANA timezone (e.g. Asia/Seoul).")
    parser.add_argument(
        "--resample-minutes",
        type=int,
        default=15,
        help="Resampling interval in minutes for uci_household (default: 15).",
    )
    parser.add_argument(
        "--submeter",
        default="total",
        choices=["total", "1", "2", "3"],
        help="Channel selection for uci_household (default: total).",
    )
    parser.add_argument("--chunk-size", type=int, default=2000, help="Batch size per DB commit.")
    parser.add_argument("--limit", type=int, default=None, help="Optional maximum intervals to import.")
    parser.add_argument(
        "--create-infrastructure",
        action="store_true",
        help="Create target facility/zone/meter in PostgreSQL if missing.",
    )
    parser.add_argument(
        "--run-analytics",
        action="store_true",
        help="Run rolling-baseline, anomaly, and insight processing after import.",
    )

    args = parser.parse_args(argv)
    settings = get_settings()
    session_factory = get_session_factory()

    try:
        with session_factory() as db:
            report = run_dataset_import(
                db,
                settings=settings,
                dataset_format=args.format,
                file_path=Path(args.file),
                facility_id=args.facility_id,
                meter_code=args.meter_code,
                actor_email=args.actor_email,
                source_timezone=args.timezone,
                resample_minutes=args.resample_minutes,
                submeter_channel=args.submeter,
                chunk_size=args.chunk_size,
                limit=args.limit,
                create_infrastructure=args.create_infrastructure,
                run_analytics=args.run_analytics,
            )
    except Exception as exc:
        print(f"Dataset import error: {exc}", file=sys.stderr)
        return 1

    print(
        "Import complete: "
        f"read={report['total_rows_read']}, "
        f"emitted={report['emitted_rows']}, "
        f"inserted={report['inserted_count']}, "
        f"duplicates={report['duplicate_count']}, "
        f"overlaps={report['overlap_count']}, "
        f"failed={report['failed_count']}, "
        f"analytics_processed={report['processed_readings']}, "
        f"anomalies_created={report['anomalies_created']}, "
        f"insights_updated={report['insights_updated']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
