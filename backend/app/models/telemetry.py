import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import (
    BaselineStatus,
    QualityFlag,
    TariffPeriod,
    TelemetrySource,
)
from app.core.database import Base

_TARIFF_SQL = ", ".join(repr(t.value) for t in TariffPeriod)
_BASELINE_SQL = ", ".join(repr(b.value) for b in BaselineStatus)
_QUALITY_SQL = ", ".join(repr(q.value) for q in QualityFlag)
_SOURCE_SQL = ", ".join(repr(s.value) for s in TelemetrySource)


class TelemetryReading(Base):
    __tablename__ = "telemetry_readings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["meter_id", "facility_id", "zone_id"],
            ["meters.id", "meters.facility_id", "meters.zone_id"],
            name="fk_telemetry_meter_facility_zone",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("meter_id", "recorded_at", name="uq_telemetry_meter_recorded_at"),
        UniqueConstraint("id", "meter_id", name="uq_telemetry_id_meter"),
        CheckConstraint("interval_seconds BETWEEN 60 AND 86400", name="valid_interval_seconds"),
        CheckConstraint(
            "interval_start = recorded_at - make_interval(secs => interval_seconds)",
            name="consistent_interval_bounds",
        ),
        CheckConstraint("actual_kw >= 0", name="non_negative_actual_kw"),
        CheckConstraint("energy_kwh >= 0", name="non_negative_energy_kwh"),
        CheckConstraint("power_factor >= 0 AND power_factor <= 1", name="valid_power_factor"),
        CheckConstraint(f"tariff_period IN ({_TARIFF_SQL})", name="valid_tariff_period"),
        CheckConstraint(f"baseline_status IN ({_BASELINE_SQL})", name="valid_baseline_status"),
        CheckConstraint(f"quality_flag IN ({_QUALITY_SQL})", name="valid_quality_flag"),
        CheckConstraint(f"source IN ({_SOURCE_SQL})", name="valid_source"),
        CheckConstraint(
            "baseline_attempt_count >= 0",
            name="non_negative_baseline_attempt_count",
        ),
        ExcludeConstraint(
            ("meter_id", "="),
            (
                func.tstzrange(
                    text("interval_start"),
                    text("recorded_at"),
                    text("'[)'"),
                ),
                "&&",
            ),
            name="ex_telemetry_no_overlapping_intervals",
            using="gist",
        ),
        Index("ix_telemetry_facility_time", "facility_id", text("recorded_at DESC")),
        Index("ix_telemetry_zone_time", "zone_id", text("recorded_at DESC")),
        Index(
            "ix_telemetry_zscore_high",
            "facility_id",
            text("z_score DESC"),
            postgresql_where=text("baseline_status = 'ready' AND z_score >= 1.5"),
        ),
        Index(
            "ix_telemetry_baseline_pending",
            "meter_id",
            "recorded_at",
            "id",
            postgresql_where=text(
                "baseline_computed_at IS NULL AND quality_flag = 'valid' AND source <> 'simulation'"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    facility_id: Mapped[str] = mapped_column(String(64), nullable=False)
    zone_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    meter_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    interval_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_kw: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    energy_kwh: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    baseline_kw: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    std_dev_kw: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    z_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    baseline_status: Mapped[str] = mapped_column(String(24), nullable=False)
    baseline_computed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    baseline_last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    baseline_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    baseline_retry_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    baseline_attempt_max_meter_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, default=None
    )
    power_factor: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    tariff_period: Mapped[str] = mapped_column(String(16), nullable=False)
    ambient_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    quality_flag: Mapped[str] = mapped_column(
        String(24), nullable=False, default="valid", server_default=text("'valid'")
    )
    source: Mapped[str] = mapped_column(
        String(24), nullable=False, default="meter_feed", server_default=text("'meter_feed'")
    )
