from decimal import Decimal
from functools import lru_cache
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import Environment

_WEAK_SECRET_PLACEHOLDERS = {
    "",
    "secret",
    "changeme",
    "change-me",
    "change-me-in-local-dev-only-at-least-32-bytes",
    "dev-secret",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Environment = Environment.DEVELOPMENT
    app_name: str = "EnergyGrid API"
    api_v1_prefix: str = "/api/v1"

    # Database URL must be supplied via environment (.env) — never hardcoded in source
    database_url: str = Field(
        ...,
        description="PostgreSQL SQLAlchemy connection URL (e.g. postgresql+psycopg://...)",
    )
    test_database_url: str | None = None

    # Security settings
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=30, gt=0, le=10080)
    allow_dev_auth_bypass: bool = False
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    cors_allow_credentials: bool = True

    # Telemetry ingestion thresholds & upload caps
    telemetry_max_overload_factor: Decimal = Field(
        default=Decimal("3.0"), gt=Decimal("0"), le=Decimal("20.0")
    )
    telemetry_energy_tolerance_pct: Decimal = Field(
        default=Decimal("0.05"), ge=Decimal("0"), le=Decimal("1.0")
    )
    telemetry_energy_tolerance_abs_kwh: Decimal = Field(
        default=Decimal("0.0500"), ge=Decimal("0"), le=Decimal("100.0")
    )
    telemetry_max_bulk_items: int = Field(default=1000, ge=1, le=50000)
    telemetry_max_csv_upload_bytes: int = Field(
        default=10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024
    )
    telemetry_max_csv_upload_rows: int = Field(default=10000, ge=1, le=200000)
    telemetry_future_skew_seconds: int = Field(default=300, ge=0, le=86400)

    # Phase 2E: Rolling baseline calculation, retry limits & bounded batch caps
    baseline_lookback_days: int = Field(default=30, ge=7, le=365)
    baseline_min_samples: int = Field(default=14, ge=3, le=1000)
    baseline_allow_hour_only_fallback: bool = True
    baseline_require_matching_interval: bool = True
    baseline_max_window_samples_per_bucket: int = Field(default=120, ge=3, le=1000)
    baseline_min_std_dev_kw: Decimal = Field(
        default=Decimal("1.00"), gt=Decimal("0"), le=Decimal("1000.0")
    )
    baseline_min_std_dev_pct: Decimal = Field(
        default=Decimal("0.02"), ge=Decimal("0"), le=Decimal("1.0")
    )
    analytics_insufficient_max_attempts: int = Field(default=20, ge=1, le=1000)
    analytics_insufficient_base_cooldown_minutes: int = Field(default=60, ge=1, le=1440)
    analytics_insufficient_max_cooldown_minutes: int = Field(default=1440, ge=1, le=10080)
    analytics_chunk_size: int = Field(default=250, ge=10, le=2000)
    analytics_default_max_readings: int = Field(default=2500, ge=1, le=50000)
    analytics_hard_max_readings: int = Field(default=20000, ge=1, le=100000)
    # Automatic analytics: background trigger after telemetry ingestion
    analytics_auto_trigger: bool = True
    analytics_background_max_readings: int = Field(default=500, ge=10, le=20000)

    # Phase 2E: Anomaly detection thresholds (positive deviations only)
    anomaly_z_score_elevated: Decimal = Field(
        default=Decimal("2.00"), gt=Decimal("0"), le=Decimal("20.0")
    )
    anomaly_z_score_high: Decimal = Field(
        default=Decimal("2.60"), gt=Decimal("0"), le=Decimal("20.0")
    )
    anomaly_z_score_critical: Decimal = Field(
        default=Decimal("3.40"), gt=Decimal("0"), le=Decimal("20.0")
    )
    anomaly_min_excess_kw: Decimal = Field(
        default=Decimal("2.00"), ge=Decimal("0"), le=Decimal("10000.0")
    )

    # Phase 2E: Insight window gates and rule thresholds
    insight_lookback_days: int = Field(default=30, ge=7, le=365)
    insight_min_window_days: int = Field(default=7, ge=1, le=365)
    insight_min_window_readings: int = Field(default=96, ge=14, le=50000)
    insight_load_shift_min_peak_readings: int = Field(default=24, ge=1, le=10000)
    insight_load_shift_peak_share_threshold: Decimal = Field(
        default=Decimal("0.45"), gt=Decimal("0"), le=Decimal("1.0")
    )
    insight_load_shift_transferable_fraction: Decimal = Field(
        default=Decimal("0.20"), gt=Decimal("0"), le=Decimal("1.0")
    )
    insight_pf_threshold: Decimal = Field(
        default=Decimal("0.90"), gt=Decimal("0"), le=Decimal("1.0")
    )
    insight_pf_min_violation_readings: int = Field(default=12, ge=1, le=10000)
    insight_pf_min_violation_ratio: Decimal = Field(
        default=Decimal("0.25"), gt=Decimal("0"), le=Decimal("1.0")
    )
    insight_off_peak_min_readings: int = Field(default=32, ge=1, le=10000)
    insight_off_peak_active_min_readings: int = Field(default=32, ge=1, le=10000)
    insight_off_peak_baseload_ratio: Decimal = Field(
        default=Decimal("0.65"), gt=Decimal("0"), le=Decimal("5.0")
    )
    insight_thermal_min_readings: int = Field(default=48, ge=14, le=10000)
    insight_thermal_min_correlation: Decimal = Field(
        default=Decimal("0.60"), gt=Decimal("0"), le=Decimal("1.0")
    )
    insight_high_priority_annual_savings: Decimal = Field(
        default=Decimal("5000.00"), ge=Decimal("0"), le=Decimal("100000000.0")
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value or not value.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a valid PostgreSQL SQLAlchemy URL.")
        return value

    @field_validator("jwt_algorithm")
    @classmethod
    def validate_jwt_algorithm(cls, value: str) -> str:
        allowed = {"HS256", "HS384", "HS512"}
        normalized = value.strip().upper()
        if normalized not in allowed:
            raise ValueError(f"JWT_ALGORITHM must be one of {sorted(allowed)}.")
        return normalized

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: object) -> list[str]:
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("["):
                import json

                parsed = json.loads(raw)
                return [str(o).strip() for o in parsed if str(o).strip()]
            return [item.strip() for item in raw.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(o).strip() for o in value if str(o).strip()]
        raise ValueError("ALLOWED_ORIGINS must be a list or comma-separated string.")

    @model_validator(mode="after")
    def validate_security_posture(self) -> "Settings":
        # Never allow wildcard CORS together with credentials
        if self.cors_allow_credentials and "*" in self.allowed_origins:
            raise ValueError(
                "Wildcard '*' in ALLOWED_ORIGINS is forbidden when CORS_ALLOW_CREDENTIALS is enabled."
            )

        # Production & staging guardrails: dev auth bypass is strictly impossible
        if self.environment in (Environment.STAGING, Environment.PRODUCTION):
            if self.allow_dev_auth_bypass:
                raise ValueError(
                    "ALLOW_DEV_AUTH_BYPASS=true is strictly forbidden in staging/production."
                )
            secret = self.jwt_secret_key.strip()
            if secret.lower() in _WEAK_SECRET_PLACEHOLDERS or len(secret) < 32:
                raise ValueError(
                    "JWT_SECRET_KEY must be at least 32 non-placeholder characters in staging/production."
                )

        if not (
            self.anomaly_z_score_elevated
            < self.anomaly_z_score_high
            < self.anomaly_z_score_critical
        ):
            raise ValueError(
                "Anomaly z-score thresholds must satisfy elevated < high < critical."
            )
        if (
            self.analytics_insufficient_base_cooldown_minutes
            > self.analytics_insufficient_max_cooldown_minutes
        ):
            raise ValueError(
                "ANALYTICS_INSUFFICIENT_BASE_COOLDOWN_MINUTES cannot exceed ANALYTICS_INSUFFICIENT_MAX_COOLDOWN_MINUTES."
            )
        if self.analytics_default_max_readings > self.analytics_hard_max_readings:
            raise ValueError(
                "ANALYTICS_DEFAULT_MAX_READINGS cannot exceed ANALYTICS_HARD_MAX_READINGS."
            )
        if self.insight_min_window_days > self.insight_lookback_days:
            raise ValueError(
                "INSIGHT_MIN_WINDOW_DAYS cannot exceed INSIGHT_LOOKBACK_DAYS."
            )
        if self.baseline_min_samples > self.baseline_max_window_samples_per_bucket:
            raise ValueError(
                "BASELINE_MIN_SAMPLES cannot exceed BASELINE_MAX_WINDOW_SAMPLES_PER_BUCKET."
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
