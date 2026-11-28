import csv
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import io
import math
import tempfile
from typing import IO, Any
import uuid
from zoneinfo import ZoneInfo

from fastapi import UploadFile
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.constants import (
    MAX_INTEGRATION_GAP_SECONDS,
    BaselineStatus,
    QualityFlag,
    TariffPeriod,
    TelemetrySource,
)
from app.models.facility import Facility, Meter, Zone
from app.models.telemetry import TelemetryReading
from app.models.user import User
from app.schemas.common import DEFAULT_PAGE, DEFAULT_PAGE_SIZE, PaginatedResponse
from app.schemas.telemetry import (
    IngestionRowError,
    TelemetryBulkIngestRequest,
    TelemetryIngestionSummary,
    TelemetryReadingCreate,
    TelemetryReadingResponse,
)
from app.services.exceptions import (
    ConflictError,
    InvalidRelationError,
    PayloadTooLargeError,
    ResourceNotFoundError,
    ValidationFailureError,
)
from app.services.permissions import (
    ALL_AUTHENTICATED_ROLES,
    METER_UPDATE_ROLES,
    assert_actor_authorized,
)

_CSV_CHUNK_SIZE = 64 * 1024
_CSV_SPOOL_THRESHOLD_BYTES = 1024 * 1024
_CSV_REQUIRED_BASE_COLUMNS: frozenset[str] = frozenset(
    {"recorded_at", "actual_kw", "power_factor"}
)
_CSV_ALLOWED_COLUMNS: frozenset[str] = frozenset(
    {
        "meter_id",
        "meter_code",
        "facility_id",
        "zone_id",
        "recorded_at",
        "interval_start",
        "interval_seconds",
        "actual_kw",
        "energy_kwh",
        "power_factor",
        "ambient_temp_c",
        "tariff_period",
        "quality_flag",
        "source",
    }
)
_CSV_OPTIONAL_FIELDS: frozenset[str] = frozenset(
    {
        "meter_id",
        "meter_code",
        "facility_id",
        "zone_id",
        "interval_start",
        "interval_seconds",
        "energy_kwh",
        "ambient_temp_c",
        "tariff_period",
        "quality_flag",
        "source",
    }
)


def _derive_tariff_period(recorded_at_utc: datetime, facility_timezone: str) -> TariffPeriod:
    """Derive facility-local time-of-use tariff period deterministically from UTC timestamp."""
    local_dt = recorded_at_utc.astimezone(ZoneInfo(facility_timezone))
    hour = local_dt.hour
    is_weekday = local_dt.weekday() < 5

    if is_weekday:
        if (9 <= hour < 12) or (18 <= hour < 22):
            return TariffPeriod.PEAK
        if (6 <= hour < 9) or (12 <= hour < 18) or (22 <= hour <= 23):
            return TariffPeriod.MID_PEAK
        return TariffPeriod.OFF_PEAK

    if 8 <= hour < 22:
        return TariffPeriod.MID_PEAK
    return TariffPeriod.OFF_PEAK


def _classify_integrity_error(exc: IntegrityError) -> tuple[str, str]:
    orig = exc.orig
    sqlstate = getattr(orig, "sqlstate", None)
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)

    if sqlstate == "23505" or constraint_name == "uq_telemetry_meter_recorded_at":
        return (
            "duplicate_reading",
            "A telemetry reading already exists for this meter at the specified 'recorded_at' timestamp.",
        )
    if sqlstate == "23P01" or constraint_name == "ex_telemetry_no_overlapping_intervals":
        return (
            "overlapping_interval",
            "Telemetry interval overlaps an existing reading interval for this meter.",
        )
    return ("database_error", "Telemetry reading violates a database integrity constraint.")


def _lock_and_fetch_meters(
    db: Session,
    *,
    meter_ids: set[uuid.UUID],
    meter_codes: set[str],
) -> tuple[dict[uuid.UUID, tuple[Meter, Zone, Facility]], dict[str, tuple[Meter, Zone, Facility]]]:
    if not meter_ids and not meter_codes:
        return {}, {}

    conditions = []
    if meter_ids:
        conditions.append(Meter.id.in_(sorted(meter_ids)))
    if meter_codes:
        conditions.append(Meter.meter_code.in_(sorted(meter_codes)))

    # Deterministic Meter.id ordering + FOR SHARE OF meters prevents deadlocks and
    # serializes safely against deactivate_meter (which acquires FOR UPDATE on meters).
    rows = db.execute(
        select(Meter, Zone, Facility)
        .join(Zone, (Meter.zone_id == Zone.id) & (Meter.facility_id == Zone.facility_id))
        .join(Facility, Zone.facility_id == Facility.id)
        .where(or_(*conditions))
        .order_by(Meter.id.asc())
        .with_for_update(read=True, of=Meter)
        .execution_options(populate_existing=True)
    ).all()

    by_id: dict[uuid.UUID, tuple[Meter, Zone, Facility]] = {}
    by_code: dict[str, tuple[Meter, Zone, Facility]] = {}
    for meter, zone, facility in rows:
        bundle = (meter, zone, facility)
        by_id[meter.id] = bundle
        by_code[meter.meter_code] = bundle
    return by_id, by_code


def _resolve_meter_bundle(
    payload: TelemetryReadingCreate,
    by_id: dict[uuid.UUID, tuple[Meter, Zone, Facility]],
    by_code: dict[str, tuple[Meter, Zone, Facility]],
) -> tuple[Meter, Zone, Facility]:
    bundle_by_id = by_id.get(payload.meter_id) if payload.meter_id is not None else None
    bundle_by_code = by_code.get(payload.meter_code) if payload.meter_code is not None else None

    if payload.meter_id is not None and payload.meter_code is not None:
        if bundle_by_id is None or bundle_by_code is None:
            raise ResourceNotFoundError("Referenced meter was not found.")
        if bundle_by_id[0].id != bundle_by_code[0].id:
            raise InvalidRelationError(
                "Provided 'meter_id' and 'meter_code' refer to different meters."
            )
        return bundle_by_id

    if payload.meter_id is not None:
        if bundle_by_id is None:
            raise ResourceNotFoundError(f"Meter '{payload.meter_id}' not found.")
        return bundle_by_id

    assert payload.meter_code is not None
    if bundle_by_code is None:
        raise ResourceNotFoundError(f"Meter with code '{payload.meter_code}' not found.")
    return bundle_by_code


def _build_telemetry_reading(
    payload: TelemetryReadingCreate,
    *,
    meter: Meter,
    zone: Zone,
    facility: Facility,
    settings: Settings,
    now_utc: datetime,
) -> TelemetryReading:
    if payload.facility_id is not None and payload.facility_id != meter.facility_id:
        raise InvalidRelationError(
            f"Reading facility_id '{payload.facility_id}' does not match meter facility '{meter.facility_id}'."
        )
    if payload.zone_id is not None and payload.zone_id != meter.zone_id:
        raise InvalidRelationError(
            f"Reading zone_id '{payload.zone_id}' does not match meter zone '{meter.zone_id}'."
        )

    if not meter.is_active:
        raise ConflictError(f"Meter '{meter.meter_code}' is deactivated.")
    if not zone.is_active:
        raise ConflictError(
            f"Zone '{zone.id}' for meter '{meter.meter_code}' is deactivated."
        )
    if not facility.is_active:
        raise ConflictError(
            f"Facility '{facility.id}' for meter '{meter.meter_code}' is deactivated."
        )

    max_allowed_dt = now_utc + timedelta(seconds=settings.telemetry_future_skew_seconds)
    if payload.recorded_at > max_allowed_dt:
        raise ValidationFailureError(
            f"recorded_at '{payload.recorded_at.isoformat()}' exceeds allowed future clock skew."
        )

    interval_seconds = (
        payload.interval_seconds
        if payload.interval_seconds is not None
        else meter.nominal_interval_seconds
    )
    if payload.quality_flag == QualityFlag.GAP_BOUNDED:
        if not (60 <= interval_seconds <= MAX_INTEGRATION_GAP_SECONDS):
            raise ValidationFailureError(
                f"Gap-bounded interval_seconds ({interval_seconds}) must be between 60 and {MAX_INTEGRATION_GAP_SECONDS}."
            )
    elif interval_seconds != meter.nominal_interval_seconds:
        raise ValidationFailureError(
            f"interval_seconds ({interval_seconds}) must match meter nominal_interval_seconds ({meter.nominal_interval_seconds}) unless quality_flag is 'gap_bounded'."
        )

    interval_start = payload.recorded_at - timedelta(seconds=interval_seconds)

    max_allowed_kw = (meter.rated_kw * settings.telemetry_max_overload_factor).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if payload.actual_kw > max_allowed_kw:
        raise ValidationFailureError(
            f"actual_kw ({payload.actual_kw}) exceeds configured {settings.telemetry_max_overload_factor}x rated_kw threshold ({max_allowed_kw} kW)."
        )

    expected_energy_kwh = (
        payload.actual_kw * Decimal(interval_seconds) / Decimal(3600)
    ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    if payload.energy_kwh is None:
        final_energy_kwh = expected_energy_kwh
    else:
        final_energy_kwh = payload.energy_kwh
        allowed_delta = (
            expected_energy_kwh * settings.telemetry_energy_tolerance_pct
        ) + settings.telemetry_energy_tolerance_abs_kwh
        if abs(final_energy_kwh - expected_energy_kwh) > allowed_delta:
            raise ValidationFailureError(
                f"Supplied energy_kwh ({final_energy_kwh}) deviates from expected {expected_energy_kwh} kWh beyond allowed tolerance (±{allowed_delta.quantize(Decimal('0.0001'))} kWh)."
            )

    tariff_period = (
        payload.tariff_period
        if payload.tariff_period is not None
        else _derive_tariff_period(payload.recorded_at, facility.timezone)
    )

    return TelemetryReading(
        facility_id=meter.facility_id,
        zone_id=meter.zone_id,
        meter_id=meter.id,
        interval_start=interval_start,
        recorded_at=payload.recorded_at,
        interval_seconds=interval_seconds,
        actual_kw=payload.actual_kw,
        energy_kwh=final_energy_kwh,
        baseline_kw=None,
        std_dev_kw=None,
        z_score=None,
        baseline_status=BaselineStatus.INSUFFICIENT_HISTORY.value,
        power_factor=payload.power_factor,
        tariff_period=tariff_period.value,
        ambient_temp_c=payload.ambient_temp_c,
        quality_flag=payload.quality_flag.value,
        source=payload.source.value,
    )


def _error_code_for_exception(exc: Exception) -> str:
    if isinstance(exc, ResourceNotFoundError):
        return "not_found"
    if isinstance(exc, InvalidRelationError):
        return "relation_mismatch"
    if isinstance(exc, ConflictError):
        return "inactive_resource"
    return "validation_error"


def _extract_raw_identifiers(raw: dict[str, Any]) -> tuple[uuid.UUID | None, str | None]:
    meter_id: uuid.UUID | None = None
    meter_code: str | None = None

    raw_id = raw.get("meter_id")
    if isinstance(raw_id, uuid.UUID):
        meter_id = raw_id
    elif isinstance(raw_id, str) and raw_id.strip():
        try:
            meter_id = uuid.UUID(raw_id.strip())
        except ValueError:
            meter_id = None

    raw_code = raw.get("meter_code")
    if isinstance(raw_code, str) and raw_code.strip():
        meter_code = raw_code.strip()

    return meter_id, meter_code


def _extract_raw_recorded_at(raw: dict[str, Any]) -> datetime | None:
    val = raw.get("recorded_at")
    if isinstance(val, datetime) and val.tzinfo is not None:
        return val.astimezone(UTC)
    if isinstance(val, str) and val.strip():
        try:
            parsed = datetime.fromisoformat(val.strip().replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(UTC)
        except ValueError:
            return None
    return None


def _persist_validated_batch_row(
    db: Session,
    *,
    raw_row: dict[str, Any],
    row_index: int,
    row_number: int | None,
    by_id: dict[uuid.UUID, tuple[Meter, Zone, Facility]],
    by_code: dict[str, tuple[Meter, Zone, Facility]],
    settings: Settings,
    now_utc: datetime,
    atomic: bool,
    force_source: TelemetrySource | None = None,
) -> tuple[int | None, IngestionRowError | None]:
    raw_meter_id, raw_meter_code = _extract_raw_identifiers(raw_row)
    raw_recorded_at = _extract_raw_recorded_at(raw_row)

    try:
        payload = TelemetryReadingCreate.model_validate(raw_row)
        if force_source is not None:
            payload.source = force_source
        meter, zone, facility = _resolve_meter_bundle(payload, by_id, by_code)
        reading = _build_telemetry_reading(
            payload,
            meter=meter,
            zone=zone,
            facility=facility,
            settings=settings,
            now_utc=now_utc,
        )
    except ValidationError as exc:
        if atomic:
            db.rollback()
            prefix = f"Row {row_number}" if row_number is not None else f"Item {row_index}"
            raise ValidationFailureError(f"{prefix} validation failed: {exc.errors()[0]['msg']}") from exc
        return None, IngestionRowError(
            row_index=row_index,
            row_number=row_number,
            meter_id=raw_meter_id,
            meter_code=raw_meter_code,
            recorded_at=raw_recorded_at,
            code="validation_error",
            message=str(exc.errors()[0]["msg"]),
        )
    except (
        ResourceNotFoundError,
        InvalidRelationError,
        ConflictError,
        ValidationFailureError,
    ) as exc:
        if atomic:
            db.rollback()
            raise
        return None, IngestionRowError(
            row_index=row_index,
            row_number=row_number,
            meter_id=raw_meter_id,
            meter_code=raw_meter_code,
            recorded_at=raw_recorded_at,
            code=_error_code_for_exception(exc),
            message=str(exc),
        )

    if atomic:
        db.add(reading)
        try:
            db.flush([reading])
        except IntegrityError as exc:
            db.rollback()
            _code, msg = _classify_integrity_error(exc)
            raise ConflictError(msg) from exc
        return int(reading.id), None

    try:
        with db.begin_nested():
            db.add(reading)
            db.flush([reading])
        return int(reading.id), None
    except IntegrityError as exc:
        err_code, err_msg = _classify_integrity_error(exc)
        return None, IngestionRowError(
            row_index=row_index,
            row_number=row_number,
            meter_id=meter.id,
            meter_code=meter.meter_code,
            recorded_at=reading.recorded_at,
            code=err_code,
            message=err_msg,
        )


def ingest_reading(
    db: Session,
    *,
    actor: User,
    payload: TelemetryReadingCreate,
    settings: Settings,
) -> TelemetryReadingResponse:
    assert_actor_authorized(actor, METER_UPDATE_ROLES)

    meter_ids = {payload.meter_id} if payload.meter_id is not None else set()
    meter_codes = {payload.meter_code} if payload.meter_code is not None else set()
    by_id, by_code = _lock_and_fetch_meters(db, meter_ids=meter_ids, meter_codes=meter_codes)

    try:
        meter, zone, facility = _resolve_meter_bundle(payload, by_id, by_code)
        reading = _build_telemetry_reading(
            payload,
            meter=meter,
            zone=zone,
            facility=facility,
            settings=settings,
            now_utc=datetime.now(UTC),
        )
    except Exception:
        db.rollback()
        raise

    db.add(reading)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _err_code, err_msg = _classify_integrity_error(exc)
        raise ConflictError(err_msg) from exc

    db.refresh(reading)
    return TelemetryReadingResponse.model_validate(reading)


def ingest_bulk_readings(
    db: Session,
    *,
    actor: User,
    payload: TelemetryBulkIngestRequest,
    settings: Settings,
) -> TelemetryIngestionSummary:
    assert_actor_authorized(actor, METER_UPDATE_ROLES)

    if len(payload.readings) > settings.telemetry_max_bulk_items:
        raise PayloadTooLargeError(
            f"Bulk ingestion batch exceeds maximum allowed limit of {settings.telemetry_max_bulk_items} readings."
        )

    meter_ids: set[uuid.UUID] = set()
    meter_codes: set[str] = set()
    for raw_item in payload.readings:
        m_id, m_code = _extract_raw_identifiers(raw_item)
        if m_id is not None:
            meter_ids.add(m_id)
        if m_code is not None:
            meter_codes.add(m_code)

    by_id, by_code = _lock_and_fetch_meters(db, meter_ids=meter_ids, meter_codes=meter_codes)

    now_utc = datetime.now(UTC)
    inserted_ids: list[int] = []
    errors: list[IngestionRowError] = []
    duplicate_count = 0
    overlap_count = 0
    failed_count = 0

    for idx, raw_item in enumerate(payload.readings):
        reading_id, row_error = _persist_validated_batch_row(
            db,
            raw_row=raw_item,
            row_index=idx,
            row_number=None,
            by_id=by_id,
            by_code=by_code,
            settings=settings,
            now_utc=now_utc,
            atomic=payload.atomic,
        )
        if reading_id is not None:
            inserted_ids.append(reading_id)
        elif row_error is not None:
            errors.append(row_error)
            if row_error.code == "duplicate_reading":
                duplicate_count += 1
            elif row_error.code == "overlapping_interval":
                overlap_count += 1
            else:
                failed_count += 1

    db.commit()
    return TelemetryIngestionSummary(
        atomic=payload.atomic,
        total_received=len(payload.readings),
        inserted_count=len(inserted_ids),
        duplicate_count=duplicate_count,
        overlap_count=overlap_count,
        failed_count=failed_count,
        inserted_ids=inserted_ids,
        errors=errors,
    )


def _validate_csv_headers(headers: list[str] | None) -> list[str]:
    if not headers:
        raise ValidationFailureError("CSV file is empty or missing a header row.")

    cleaned: list[str] = []
    seen: set[str] = set()
    for col in headers:
        name = col.strip()
        if not name:
            raise ValidationFailureError("CSV header contains a blank column name.")
        if name in seen:
            raise ValidationFailureError(f"CSV header contains duplicate column '{name}'.")
        seen.add(name)
        cleaned.append(name)

    missing_base = sorted(_CSV_REQUIRED_BASE_COLUMNS - seen)
    if missing_base:
        raise ValidationFailureError(
            f"CSV header is missing required column(s): {', '.join(missing_base)}."
        )
    if "meter_id" not in seen and "meter_code" not in seen:
        raise ValidationFailureError(
            "CSV header must include 'meter_id' or 'meter_code'."
        )

    unknown = sorted(seen - _CSV_ALLOWED_COLUMNS)
    if unknown:
        raise ValidationFailureError(
            f"CSV header contains unsupported column(s): {', '.join(unknown)}."
        )

    return cleaned


def _normalize_csv_row_dict(raw_row: dict[str | None, str | None]) -> dict[str, Any]:
    if None in raw_row:
        raise ValueError("Malformed CSV row contains extra unheaded column values.")

    normalized: dict[str, Any] = {}
    for key, value in raw_row.items():
        if key is None:
            continue
        cleaned_key = key.strip()
        if value is None:
            normalized[cleaned_key] = None
            continue
        cleaned_val = value.strip()
        if cleaned_val == "" and cleaned_key in _CSV_OPTIONAL_FIELDS:
            normalized[cleaned_key] = None
        else:
            normalized[cleaned_key] = cleaned_val

    # Force CSV import source regardless of optional column presence
    normalized["source"] = TelemetrySource.CSV_IMPORT.value
    return normalized


def _ingest_csv_stream(
    db: Session,
    *,
    spooled_file: IO[bytes],
    settings: Settings,
    atomic: bool,
) -> TelemetryIngestionSummary:
    # Pass 1: validate headers, enforce max row count immediately, collect distinct meter identifiers
    spooled_file.seek(0)
    text_stream = io.TextIOWrapper(spooled_file, encoding="utf-8-sig", newline="")
    meter_ids: set[uuid.UUID] = set()
    meter_codes: set[str] = set()
    total_rows = 0

    try:
        csv_reader = csv.reader(text_stream)
        try:
            raw_headers = next(csv_reader, None)
        except UnicodeDecodeError as exc:
            raise ValidationFailureError("CSV file must be valid UTF-8.") from exc

        cleaned_headers = _validate_csv_headers(raw_headers)
        dict_reader = csv.DictReader(text_stream, fieldnames=cleaned_headers)

        try:
            for raw_row in dict_reader:
                total_rows += 1
                if total_rows > settings.telemetry_max_csv_upload_rows:
                    raise PayloadTooLargeError(
                        f"CSV upload exceeds maximum allowed limit of {settings.telemetry_max_csv_upload_rows} rows."
                    )
                if None not in raw_row:
                    m_id, m_code = _extract_raw_identifiers(
                        {k: v for k, v in raw_row.items() if k is not None}
                    )
                    if m_id is not None:
                        meter_ids.add(m_id)
                    if m_code is not None:
                        meter_codes.add(m_code)
        except UnicodeDecodeError as exc:
            raise ValidationFailureError("CSV file contains invalid UTF-8 bytes.") from exc
    finally:
        text_stream.detach()

    if total_rows == 0:
        raise ValidationFailureError("CSV file contains headers but zero data rows.")

    # Acquire deterministic FOR SHARE meter locks inside the single outer transaction
    by_id, by_code = _lock_and_fetch_meters(db, meter_ids=meter_ids, meter_codes=meter_codes)

    # Pass 2: stream rows sequentially and insert inside the outer transaction (savepoints if partial)
    spooled_file.seek(0)
    text_stream_2 = io.TextIOWrapper(spooled_file, encoding="utf-8-sig", newline="")
    now_utc = datetime.now(UTC)
    inserted_ids: list[int] = []
    errors: list[IngestionRowError] = []
    duplicate_count = 0
    overlap_count = 0
    failed_count = 0

    try:
        header_skip = csv.reader(text_stream_2)
        next(header_skip, None)
        row_reader = csv.DictReader(text_stream_2, fieldnames=cleaned_headers)

        for row_idx, raw_row in enumerate(row_reader):
            csv_line_number = row_idx + 2  # Line 1 is header
            try:
                normalized_row = _normalize_csv_row_dict(raw_row)
            except ValueError as exc:
                if atomic:
                    db.rollback()
                    raise ValidationFailureError(f"Row {csv_line_number}: {exc}") from exc
                errors.append(
                    IngestionRowError(
                        row_index=row_idx,
                        row_number=csv_line_number,
                        code="validation_error",
                        message=str(exc),
                    )
                )
                failed_count += 1
                continue

            reading_id, row_error = _persist_validated_batch_row(
                db,
                raw_row=normalized_row,
                row_index=row_idx,
                row_number=csv_line_number,
                by_id=by_id,
                by_code=by_code,
                settings=settings,
                now_utc=now_utc,
                atomic=atomic,
                force_source=TelemetrySource.CSV_IMPORT,
            )
            if reading_id is not None:
                inserted_ids.append(reading_id)
            elif row_error is not None:
                errors.append(row_error)
                if row_error.code == "duplicate_reading":
                    duplicate_count += 1
                elif row_error.code == "overlapping_interval":
                    overlap_count += 1
                else:
                    failed_count += 1
    finally:
        text_stream_2.detach()

    db.commit()
    return TelemetryIngestionSummary(
        atomic=atomic,
        total_received=total_rows,
        inserted_count=len(inserted_ids),
        duplicate_count=duplicate_count,
        overlap_count=overlap_count,
        failed_count=failed_count,
        inserted_ids=inserted_ids,
        errors=errors,
    )


async def ingest_csv_upload(
    db: Session,
    *,
    actor: User,
    upload_file: UploadFile,
    settings: Settings,
    atomic: bool = False,
) -> TelemetryIngestionSummary:
    assert_actor_authorized(actor, METER_UPDATE_ROLES)

    spooled = tempfile.SpooledTemporaryFile(max_size=_CSV_SPOOL_THRESHOLD_BYTES)
    total_bytes = 0
    try:
        while True:
            chunk = await upload_file.read(_CSV_CHUNK_SIZE)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > settings.telemetry_max_csv_upload_bytes:
                raise PayloadTooLargeError(
                    f"CSV upload exceeds maximum allowed size of {settings.telemetry_max_csv_upload_bytes} bytes."
                )
            spooled.write(chunk)

        if total_bytes == 0:
            raise ValidationFailureError("CSV file is empty.")

        return _ingest_csv_stream(
            db,
            spooled_file=spooled,
            settings=settings,
            atomic=atomic,
        )
    finally:
        spooled.close()


def ingest_csv_bytes(
    db: Session,
    *,
    actor: User,
    csv_stream: IO[bytes],
    settings: Settings,
    atomic: bool = False,
) -> TelemetryIngestionSummary:
    """Synchronous stream helper enabling direct service-layer CSV testing and batch jobs."""
    assert_actor_authorized(actor, METER_UPDATE_ROLES)

    spooled = tempfile.SpooledTemporaryFile(max_size=_CSV_SPOOL_THRESHOLD_BYTES)
    total_bytes = 0
    try:
        while True:
            chunk = csv_stream.read(_CSV_CHUNK_SIZE)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > settings.telemetry_max_csv_upload_bytes:
                raise PayloadTooLargeError(
                    f"CSV upload exceeds maximum allowed size of {settings.telemetry_max_csv_upload_bytes} bytes."
                )
            spooled.write(chunk)

        if total_bytes == 0:
            raise ValidationFailureError("CSV file is empty.")

        return _ingest_csv_stream(
            db,
            spooled_file=spooled,
            settings=settings,
            atomic=atomic,
        )
    finally:
        spooled.close()


def list_telemetry_readings(
    db: Session,
    *,
    actor: User,
    page: int = DEFAULT_PAGE,
    page_size: int = DEFAULT_PAGE_SIZE,
    facility_id: str | None = None,
    zone_id: uuid.UUID | None = None,
    meter_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    quality_flag: QualityFlag | None = None,
    source: TelemetrySource | None = None,
) -> PaginatedResponse[TelemetryReadingResponse]:
    assert_actor_authorized(actor, ALL_AUTHENTICATED_ROLES)

    if start_at is not None and (start_at.tzinfo is None or start_at.utcoffset() is None):
        raise ValidationFailureError("start_at must include an explicit timezone offset or 'Z'.")
    if end_at is not None and (end_at.tzinfo is None or end_at.utcoffset() is None):
        raise ValidationFailureError("end_at must include an explicit timezone offset or 'Z'.")

    start_utc = start_at.astimezone(UTC) if start_at is not None else None
    end_utc = end_at.astimezone(UTC) if end_at is not None else None
    if start_utc is not None and end_utc is not None and start_utc > end_utc:
        raise ValidationFailureError("'start_at' cannot be later than 'end_at'.")

    filters = []
    if facility_id is not None:
        filters.append(TelemetryReading.facility_id == facility_id)
    if zone_id is not None:
        filters.append(TelemetryReading.zone_id == zone_id)
    if meter_id is not None:
        filters.append(TelemetryReading.meter_id == meter_id)
    if start_utc is not None:
        filters.append(TelemetryReading.recorded_at >= start_utc)
    if end_utc is not None:
        filters.append(TelemetryReading.recorded_at <= end_utc)
    if quality_flag is not None:
        filters.append(TelemetryReading.quality_flag == quality_flag.value)
    if source is not None:
        filters.append(TelemetryReading.source == source.value)

    total = int(db.scalar(select(func.count(TelemetryReading.id)).where(*filters)) or 0)
    offset = (page - 1) * page_size
    rows = list(
        db.scalars(
            select(TelemetryReading)
            .where(*filters)
            .order_by(TelemetryReading.recorded_at.desc(), TelemetryReading.id.desc())
            .offset(offset)
            .limit(page_size)
        ).all()
    )

    items = [TelemetryReadingResponse.model_validate(row) for row in rows]
    pages = math.ceil(total / page_size) if total > 0 else 0
    return PaginatedResponse[TelemetryReadingResponse](
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )
