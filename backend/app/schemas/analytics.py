from datetime import UTC, datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _require_tz_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware.")
    return value.astimezone(UTC)


class AnalyticsCursor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_meter_id: uuid.UUID
    last_recorded_at: datetime
    last_reading_id: int = Field(..., ge=1)

    @field_validator("last_recorded_at")
    @classmethod
    def validate_last_recorded_at(cls, value: datetime) -> datetime:
        return _require_tz_utc(value, "last_recorded_at")


class AnalyticsProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facility_id: str | None = Field(default=None, min_length=2, max_length=64)
    zone_id: uuid.UUID | None = None
    meter_id: uuid.UUID | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    reprocess: bool = False
    retry_insufficient: bool = False
    retry_exhausted: bool = False
    max_readings: int | None = Field(default=None, ge=1)
    include_insights: bool = True
    force_insights: bool = False
    cursor: AnalyticsCursor | None = None

    @field_validator("facility_id")
    @classmethod
    def clean_facility_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("start_at")
    @classmethod
    def validate_start_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _require_tz_utc(value, "start_at")

    @field_validator("end_at")
    @classmethod
    def validate_end_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _require_tz_utc(value, "end_at")

    @model_validator(mode="after")
    def validate_modes_and_bounds(self) -> "AnalyticsProcessRequest":
        if self.start_at is not None and self.end_at is not None and self.start_at > self.end_at:
            raise ValueError("start_at cannot be after end_at.")
        if self.retry_exhausted and self.reprocess:
            raise ValueError("retry_exhausted=true cannot be combined with reprocess=true.")
        if self.retry_exhausted and self.retry_insufficient:
            raise ValueError(
                "retry_exhausted=true cannot be combined with retry_insufficient=true."
            )
        return self


class AnalyticsProcessSummary(BaseModel):
    processed_readings: int = Field(..., ge=0)
    baselines_ready: int = Field(..., ge=0)
    baselines_insufficient: int = Field(..., ge=0)
    anomalies_created: int = Field(..., ge=0)
    anomalies_reconciled: int = Field(..., ge=0)
    anomalies_unchanged: int = Field(..., ge=0)
    insights_created: int = Field(..., ge=0)
    insights_updated: int = Field(..., ge=0)
    exhausted_skipped_count: int = Field(..., ge=0)
    remaining_eligible_readings: int = Field(..., ge=0)
    has_more: bool
    next_cursor: AnalyticsCursor | None = None
