import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import (
    ANOMALY_COST_ESTIMATE_STATUSES,
    AnomalySeverity,
    AnomalyStatus,
    CostEstimateStatus,
)
from app.core.database import Base

_SEVERITY_SQL = ", ".join(repr(s.value) for s in AnomalySeverity)
_STATUS_SQL = ", ".join(repr(s.value) for s in AnomalyStatus)
_COST_STATUS_SQL = ", ".join(repr(c.value) for c in ANOMALY_COST_ESTIMATE_STATUSES)


class Anomaly(Base):
    __tablename__ = "anomalies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["meter_id", "facility_id", "zone_id"],
            ["meters.id", "meters.facility_id", "meters.zone_id"],
            name="fk_anomalies_meter_facility_zone",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["reading_id", "meter_id"],
            ["telemetry_readings.id", "telemetry_readings.meter_id"],
            name="fk_anomalies_reading_meter",
            ondelete="SET NULL (reading_id)",
        ),
        CheckConstraint(f"severity IN ({_SEVERITY_SQL})", name="valid_severity"),
        CheckConstraint(f"status IN ({_STATUS_SQL})", name="valid_status"),
        CheckConstraint("duration_min > 0", name="positive_duration_min"),
        CheckConstraint("estimated_waste_kwh >= 0", name="non_negative_waste_kwh"),
        CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0",
            name="non_negative_cost",
        ),
        CheckConstraint(
            f"cost_estimate_status IN ({_COST_STATUS_SQL})",
            name="valid_cost_status",
        ),
        CheckConstraint(
            "(cost_estimate_status = 'available' AND estimated_cost IS NOT NULL AND estimated_cost >= 0) "
            "OR (cost_estimate_status = 'unavailable_tariff' AND estimated_cost IS NULL) "
            "OR (cost_estimate_status = 'legacy_unverified' AND estimated_cost IS NOT NULL AND estimated_cost >= 0)",
            name="consistent_cost_status",
        ),
        CheckConstraint(
            "(status <> 'Assigned') OR (assigned_to_user_id IS NOT NULL)",
            name="assigned_requires_user",
        ),
        Index("ix_anomalies_facility_status_z", "facility_id", "status", text("z_score DESC")),
        Index("ix_anomalies_zone_detected", "zone_id", text("detected_at DESC")),
        Index(
            "uq_anomalies_reading_id",
            "reading_id",
            unique=True,
            postgresql_where=text("reading_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    event_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    facility_id: Mapped[str] = mapped_column(String(64), nullable=False)
    zone_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    meter_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reading_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="Open", server_default=text("'Open'")
    )
    z_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    actual_kw: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    expected_kw: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    deviation_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_waste_kwh: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    cost_estimate_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=CostEstimateStatus.AVAILABLE.value
    )
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    waveform: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    baseline_waveform: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class AnomalyWorkflowLog(Base):
    __tablename__ = "anomaly_workflow_logs"
    __table_args__ = (
        CheckConstraint(
            f"from_status IS NULL OR from_status IN ({_STATUS_SQL})",
            name="valid_from_status",
        ),
        CheckConstraint(f"to_status IN ({_STATUS_SQL})", name="valid_to_status"),
        Index("ix_anomaly_logs_anomaly_time", "anomaly_id", text("changed_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    anomaly_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("anomalies.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    from_assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    to_assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
