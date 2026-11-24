from datetime import date, datetime
from decimal import Decimal
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.constants import HealthStatus, validate_iso4217_currency

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _require_non_blank(value: str, field_label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_label} cannot be blank.")
    return cleaned


def _validate_slug(value: str, field_label: str) -> str:
    cleaned = value.strip().lower()
    if not _SLUG_PATTERN.fullmatch(cleaned):
        raise ValueError(
            f"{field_label} must contain only lowercase letters, digits, and single hyphens."
        )
    return cleaned


def _validate_timezone(value: str) -> str:
    cleaned = _require_non_blank(value, "Timezone")
    try:
        ZoneInfo(cleaned)
    except (ZoneInfoNotFoundError, KeyError, ValueError) as exc:
        raise ValueError(f"Invalid IANA timezone '{value}'.") from exc
    return cleaned


class FacilityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=2, max_length=64)
    code: str = Field(..., min_length=2, max_length=32)
    name: str = Field(..., min_length=1, max_length=160)
    location: str = Field(..., min_length=1, max_length=160)
    timezone: str = Field(..., min_length=1, max_length=64)
    currency_code: str = Field(..., min_length=3, max_length=3)
    contracted_demand_kw: Decimal = Field(..., gt=Decimal("0"), max_digits=10, decimal_places=2)
    off_peak_tariff_rate: Decimal = Field(..., ge=Decimal("0"), max_digits=10, decimal_places=4)
    mid_peak_tariff_rate: Decimal = Field(..., ge=Decimal("0"), max_digits=10, decimal_places=4)
    peak_tariff_rate: Decimal = Field(..., ge=Decimal("0"), max_digits=10, decimal_places=4)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _validate_slug(value, "Facility ID")

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        return _require_non_blank(value, "Facility code")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _require_non_blank(value, "Facility name")

    @field_validator("location")
    @classmethod
    def validate_location(cls, value: str) -> str:
        return _require_non_blank(value, "Facility location")

    @field_validator("timezone")
    @classmethod
    def validate_tz(cls, value: str) -> str:
        return _validate_timezone(value)

    @field_validator("currency_code")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return validate_iso4217_currency(value)


class FacilityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=2, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    location: str | None = Field(default=None, min_length=1, max_length=160)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    currency_code: str | None = Field(default=None, min_length=3, max_length=3)
    contracted_demand_kw: Decimal | None = Field(
        default=None, gt=Decimal("0"), max_digits=10, decimal_places=2
    )
    off_peak_tariff_rate: Decimal | None = Field(
        default=None, ge=Decimal("0"), max_digits=10, decimal_places=4
    )
    mid_peak_tariff_rate: Decimal | None = Field(
        default=None, ge=Decimal("0"), max_digits=10, decimal_places=4
    )
    peak_tariff_rate: Decimal | None = Field(
        default=None, ge=Decimal("0"), max_digits=10, decimal_places=4
    )

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str | None) -> str | None:
        return _require_non_blank(value, "Facility code") if value is not None else None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return _require_non_blank(value, "Facility name") if value is not None else None

    @field_validator("location")
    @classmethod
    def validate_location(cls, value: str | None) -> str | None:
        return _require_non_blank(value, "Facility location") if value is not None else None

    @field_validator("timezone")
    @classmethod
    def validate_tz(cls, value: str | None) -> str | None:
        return _validate_timezone(value) if value is not None else None

    @field_validator("currency_code")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        return validate_iso4217_currency(value) if value is not None else None

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "FacilityUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for facility update.")
        return self


class FacilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    name: str
    location: str
    timezone: str
    currency_code: str
    contracted_demand_kw: Decimal
    off_peak_tariff_rate: Decimal
    mid_peak_tariff_rate: Decimal
    peak_tariff_rate: Decimal
    is_active: bool
    deactivated_at: datetime | None
    created_at: datetime
    zone_count: int = 0
    active_zone_count: int = 0
    meter_count: int = 0
    active_meter_count: int = 0


class ZoneCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facility_id: str = Field(..., min_length=2, max_length=64)
    slug: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=1, max_length=160)
    primary_meter_code: str = Field(..., min_length=1, max_length=32)
    share_pct: Decimal = Field(
        ..., ge=Decimal("0"), le=Decimal("100"), max_digits=5, decimal_places=2
    )
    status: HealthStatus = HealthStatus.NOMINAL

    @field_validator("facility_id")
    @classmethod
    def validate_facility_id(cls, value: str) -> str:
        return _require_non_blank(value, "Facility ID")

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        return _validate_slug(value, "Zone slug")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _require_non_blank(value, "Zone name")

    @field_validator("primary_meter_code")
    @classmethod
    def validate_primary_meter_code(cls, value: str) -> str:
        return _require_non_blank(value, "Primary meter code")


class ZoneUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str | None = Field(default=None, min_length=2, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    primary_meter_code: str | None = Field(default=None, min_length=1, max_length=32)
    share_pct: Decimal | None = Field(
        default=None, ge=Decimal("0"), le=Decimal("100"), max_digits=5, decimal_places=2
    )
    status: HealthStatus | None = None

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        return _validate_slug(value, "Zone slug") if value is not None else None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return _require_non_blank(value, "Zone name") if value is not None else None

    @field_validator("primary_meter_code")
    @classmethod
    def validate_primary_meter_code(cls, value: str | None) -> str | None:
        return _require_non_blank(value, "Primary meter code") if value is not None else None

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "ZoneUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for zone update.")
        return self


class ZoneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    facility_id: str
    slug: str
    name: str
    primary_meter_code: str
    share_pct: Decimal
    status: HealthStatus
    is_active: bool
    deactivated_at: datetime | None
    meter_count: int = 0
    active_meter_count: int = 0


class MeterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facility_id: str = Field(..., min_length=2, max_length=64)
    zone_id: uuid.UUID
    meter_code: str = Field(..., min_length=1, max_length=32)
    equipment_name: str = Field(..., min_length=1, max_length=160)
    rated_kw: Decimal = Field(..., gt=Decimal("0"), max_digits=10, decimal_places=2)
    nominal_interval_seconds: int = Field(default=900, ge=60, le=86400)
    current_kw: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0"), max_digits=10, decimal_places=2)
    power_factor: Decimal = Field(
        ..., ge=Decimal("0"), le=Decimal("1"), max_digits=4, decimal_places=3
    )
    thd_pct: Decimal = Field(..., ge=Decimal("0"), max_digits=5, decimal_places=2)
    status: HealthStatus = HealthStatus.NOMINAL
    last_calibrated_at: date

    @field_validator("facility_id")
    @classmethod
    def validate_facility_id(cls, value: str) -> str:
        return _require_non_blank(value, "Facility ID")

    @field_validator("meter_code")
    @classmethod
    def validate_meter_code(cls, value: str) -> str:
        return _require_non_blank(value, "Meter code")

    @field_validator("equipment_name")
    @classmethod
    def validate_equipment_name(cls, value: str) -> str:
        return _require_non_blank(value, "Equipment name")


class MeterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_id: uuid.UUID | None = None
    meter_code: str | None = Field(default=None, min_length=1, max_length=32)
    equipment_name: str | None = Field(default=None, min_length=1, max_length=160)
    rated_kw: Decimal | None = Field(
        default=None, gt=Decimal("0"), max_digits=10, decimal_places=2
    )
    nominal_interval_seconds: int | None = Field(default=None, ge=60, le=86400)
    current_kw: Decimal | None = Field(
        default=None, ge=Decimal("0"), max_digits=10, decimal_places=2
    )
    power_factor: Decimal | None = Field(
        default=None, ge=Decimal("0"), le=Decimal("1"), max_digits=4, decimal_places=3
    )
    thd_pct: Decimal | None = Field(
        default=None, ge=Decimal("0"), max_digits=5, decimal_places=2
    )
    status: HealthStatus | None = None
    last_calibrated_at: date | None = None

    @field_validator("meter_code")
    @classmethod
    def validate_meter_code(cls, value: str | None) -> str | None:
        return _require_non_blank(value, "Meter code") if value is not None else None

    @field_validator("equipment_name")
    @classmethod
    def validate_equipment_name(cls, value: str | None) -> str | None:
        return _require_non_blank(value, "Equipment name") if value is not None else None

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "MeterUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided for meter update.")
        return self


class MeterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    facility_id: str
    zone_id: uuid.UUID
    meter_code: str
    equipment_name: str
    rated_kw: Decimal
    nominal_interval_seconds: int
    current_kw: Decimal
    power_factor: Decimal
    thd_pct: Decimal
    status: HealthStatus
    last_calibrated_at: date
    is_active: bool
    deactivated_at: datetime | None
