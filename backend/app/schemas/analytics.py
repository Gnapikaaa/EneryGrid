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


class AnalyticsSeriesBucketItem(BaseModel):
    timestamp: str
    label: str
    actual_kw: float
    baseline_kw: float
    std_dev_kw: float
    has_baseline: bool
    power_factor: float
    tariff_period: str
    ambient_temp_c: float
    z_score: float
    zone_id: uuid.UUID


class ZoneAnalyticsSummaryItem(BaseModel):
    zone_id: uuid.UUID
    slug: str
    name: str
    primary_meter_code: str
    kwh_used: float
    share_pct: float
    avg_kw: float
    peak_kw: float
    power_factor: float
    delta_vs_baseline_pct: float
    derived_status: str
    reading_count: int


class MeterLiveSnapshotItem(BaseModel):
    meter_id: uuid.UUID
    meter_code: str
    zone_id: uuid.UUID
    latest_recorded_at: datetime | None = None
    latest_kw: float
    avg_kw: float
    peak_kw: float
    latest_power_factor: float
    reading_count: int
    open_anomalies_count: int
    derived_status: str


class AnalyticsSummaryResponse(BaseModel):
    facility_id: str
    zone_id: uuid.UUID | None = None
    time_window: str
    include_simulated: bool
    window_start: datetime
    window_end: datetime
    latest_recorded_at: datetime | None = None
    reading_count: int = Field(..., ge=0)
    baselined_reading_count: int = Field(..., ge=0)
    total_kwh: float
    total_mwh: float
    avg_demand_kw: float
    peak_demand_kw: float
    contracted_demand_kw: float
    demand_headroom_pct: float
    avg_power_factor: float
    previous_total_kwh: float
    consumption_trend_pct: float | None = None
    open_anomalies_count: int = Field(..., ge=0)
    critical_anomalies_count: int = Field(..., ge=0)
    potential_annual_savings: float
    has_quantified_savings: bool
    unquantified_insights_count: int = Field(..., ge=0)
    zone_breakdown: list[ZoneAnalyticsSummaryItem]
    meter_snapshots: list[MeterLiveSnapshotItem]
    series: list[AnalyticsSeriesBucketItem]
    heatmap_matrix: list[list[int]]

