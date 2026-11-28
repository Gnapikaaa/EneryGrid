import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.constants import (
    SUPPORTED_ISO4217_CURRENCIES,
    HealthStatus,
    validate_iso4217_currency,
)
from app.core.database import Base

_CURRENCY_SQL_LIST = ", ".join(repr(c) for c in sorted(SUPPORTED_ISO4217_CURRENCIES))
_HEALTH_STATUS_SQL_LIST = ", ".join(repr(s.value) for s in HealthStatus)


class Facility(Base):
    __tablename__ = "facilities"
    __table_args__ = (
        CheckConstraint(
            f"currency_code IN ({_CURRENCY_SQL_LIST})",
            name="supported_iso4217_currency",
        ),
        CheckConstraint("contracted_demand_kw > 0", name="positive_contracted_demand"),
        CheckConstraint("off_peak_tariff_rate >= 0", name="non_negative_off_peak_rate"),
        CheckConstraint("mid_peak_tariff_rate >= 0", name="non_negative_mid_peak_rate"),
        CheckConstraint("peak_tariff_rate >= 0", name="non_negative_peak_rate"),
        CheckConstraint(
            "(is_active = true AND deactivated_at IS NULL) OR (is_active = false AND deactivated_at IS NOT NULL)",
            name="consistent_deactivation_state",
        ),
        Index("ix_facilities_is_active", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    location: Mapped[str] = mapped_column(String(160), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    # Explicit ISO-4217 currency code required (no implicit USD default)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    contracted_demand_kw: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    off_peak_tariff_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    mid_peak_tariff_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    peak_tariff_rate: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    zones: Mapped[list["Zone"]] = relationship(back_populates="facility")

    @validates("currency_code")
    def _validate_currency(self, _key: str, value: str) -> str:
        return validate_iso4217_currency(value)


class Zone(Base):
    __tablename__ = "zones"
    __table_args__ = (
        UniqueConstraint("facility_id", "slug", name="uq_zones_facility_slug"),
        UniqueConstraint("id", "facility_id", name="uq_zones_id_facility"),
        CheckConstraint("share_pct >= 0 AND share_pct <= 100", name="valid_share_pct"),
        CheckConstraint(f"status IN ({_HEALTH_STATUS_SQL_LIST})", name="valid_zone_status"),
        CheckConstraint(
            "(is_active = true AND deactivated_at IS NULL) OR (is_active = false AND deactivated_at IS NOT NULL)",
            name="consistent_deactivation_state",
        ),
        Index("ix_zones_facility_id", "facility_id"),
        Index("ix_zones_facility_active", "facility_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    facility_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("facilities.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    primary_meter_code: Mapped[str] = mapped_column(String(32), nullable=False)
    share_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    facility: Mapped["Facility"] = relationship(back_populates="zones")
    meters: Mapped[list["Meter"]] = relationship(back_populates="zone")


class Meter(Base):
    __tablename__ = "meters"
    __table_args__ = (
        ForeignKeyConstraint(
            ["zone_id", "facility_id"],
            ["zones.id", "zones.facility_id"],
            name="fk_meters_zone_facility",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "facility_id", "zone_id", name="uq_meters_id_facility_zone"),
        CheckConstraint("rated_kw > 0", name="positive_rated_kw"),
        CheckConstraint(
            "nominal_interval_seconds BETWEEN 60 AND 86400",
            name="valid_nominal_interval",
        ),
        CheckConstraint("current_kw >= 0", name="non_negative_current_kw"),
        CheckConstraint("power_factor >= 0 AND power_factor <= 1", name="valid_power_factor"),
        CheckConstraint("thd_pct >= 0", name="non_negative_thd_pct"),
        CheckConstraint(f"status IN ({_HEALTH_STATUS_SQL_LIST})", name="valid_meter_status"),
        CheckConstraint(
            "(is_active = true AND deactivated_at IS NULL) OR (is_active = false AND deactivated_at IS NOT NULL)",
            name="consistent_deactivation_state",
        ),
        Index("ix_meters_facility_zone_status", "facility_id", "zone_id", "status"),
        Index("ix_meters_facility_active", "facility_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    facility_id: Mapped[str] = mapped_column(String(64), nullable=False)
    zone_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    meter_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    equipment_name: Mapped[str] = mapped_column(String(160), nullable=False)
    rated_kw: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    nominal_interval_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=900, server_default=text("900")
    )
    current_kw: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    power_factor: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    thd_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    last_calibrated_at: Mapped[date] = mapped_column(Date, nullable=False)
    # Soft deactivation preferred over deletion to preserve historical telemetry & audits
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    zone: Mapped["Zone"] = relationship(
        back_populates="meters",
        foreign_keys=[zone_id, facility_id],
        overlaps="zones",
    )
