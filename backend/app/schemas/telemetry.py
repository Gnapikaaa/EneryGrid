from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.constants import (
    BaselineStatus,
    QualityFlag,
    TariffPeriod,
    TelemetrySource,
)


def _ensure_utc_datetime(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include an explicit timezone offset or 'Z'.")
    return value.astimezone(UTC)


def _ensure_finite_decimal(value: Decimal, field_name: str) -> Decimal:
    if not value.is_finite():
        raise ValueError(f"{field_name} must be a finite decimal number.")
    return value


class TelemetryReadingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meter_id: uuid.UUID | None = None
    meter_code: str | None = Field(default=None, min_length=1, max_length=32)
    facility_id: str | None = Field(default=None, min_length=2, max_length=64)
    zone_id: uuid.UUID | None = None
    recorded_at: datetime
    interval_start: datetime | None = None
    interval_seconds: int | None = Field(default=None, ge=60, le=86400)
    actual_kw: Decimal = Field(..., ge=Decimal("0"), max_digits=10, decimal_places=2)
    energy_kwh: Decimal | None = Field(
        default=None, ge=Decimal("0"), max_digits=12, decimal_places=4
    )
    power_factor: Decimal = Field(
        ..., ge=Decimal("0"), le=Decimal("1"), max_digits=4, decimal_places=3
    )
    ambient_temp_c: Decimal | None = Field(
        default=None, ge=Decimal("-60"), le=Decimal("85"), max_digits=5, decimal_places=2
    )
    tariff_period: TariffPeriod | None = None
    quality_flag: QualityFlag = QualityFlag.VALID
    source: TelemetrySource = TelemetrySource.METER_FEED

    @field_validator("meter_code", "facility_id")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Identifier cannot be blank.")
        return cleaned

    @field_validator("recorded_at")
    @classmethod
    def validate_recorded_at(cls, value: datetime) -> datetime:
        return _ensure_utc_datetime(value, "recorded_at")

    @field_validator("interval_start")
    @classmethod
    def validate_interval_start(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _ensure_utc_datetime(value, "interval_start")

    @field_validator("actual_kw", "power_factor")
    @classmethod
    def validate_required_finite_decimals(cls, value: Decimal, info: Any) -> Decimal:
        return _ensure_finite_decimal(value, info.field_name or "value")

    @field_validator("energy_kwh", "ambient_temp_c")
    @classmethod
    def validate_optional_finite_decimals(
        cls, value: Decimal | None, info: Any
    ) -> Decimal | None:
        if value is None:
            return None
        return _ensure_finite_decimal(value, info.field_name or "value")

    @model_validator(mode="after")
    def validate_identifiers_and_interval(self) -> "TelemetryReadingCreate":
        if self.meter_id is None and self.meter_code is None:
            raise ValueError("Either 'meter_id' or 'meter_code' must be provided.")

        if self.interval_start is not None:
            delta = self.recorded_at - self.interval_start
            total_seconds = delta.total_seconds()
            if total_seconds != int(total_seconds) or not (60 <= int(total_seconds) <= 86400):
                raise ValueError(
                    "Interval between 'interval_start' and 'recorded_at' must be a whole number of seconds between 60 and 86400."
                )
            derived_seconds = int(total_seconds)
            if self.interval_seconds is not None and self.interval_seconds != derived_seconds:
                raise ValueError(
                    "'interval_start' does not match 'recorded_at - interval_seconds'."
                )
            self.interval_seconds = derived_seconds

        return self


class TelemetryBulkIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atomic: bool = False
    readings: list[dict[str, Any]] = Field(..., min_length=1)


class TelemetryReadingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    facility_id: str
    zone_id: uuid.UUID
    meter_id: uuid.UUID
    interval_start: datetime
    recorded_at: datetime
    interval_seconds: int
    actual_kw: Decimal
    energy_kwh: Decimal
    baseline_kw: Decimal | None
    std_dev_kw: Decimal | None
    z_score: Decimal | None
    baseline_status: BaselineStatus
    power_factor: Decimal
    tariff_period: TariffPeriod
    ambient_temp_c: Decimal | None
    quality_flag: QualityFlag
    source: TelemetrySource


class IngestionRowError(BaseModel):
    row_index: int = Field(..., ge=0)
    row_number: int | None = Field(default=None, ge=1)
    meter_id: uuid.UUID | None = None
    meter_code: str | None = None
    recorded_at: datetime | None = None
    code: str
    message: str


class TelemetryIngestionSummary(BaseModel):
    atomic: bool
    total_received: int = Field(..., ge=0)
    inserted_count: int = Field(..., ge=0)
    duplicate_count: int = Field(..., ge=0)
    overlap_count: int = Field(..., ge=0)
    failed_count: int = Field(..., ge=0)
    inserted_ids: list[int]
    errors: list[IngestionRowError]
