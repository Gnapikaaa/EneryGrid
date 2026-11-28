import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import (
    INSIGHT_COST_ESTIMATE_STATUSES,
    InsightCategory,
    InsightPriority,
    InsightSavingsBasis,
    InsightStatus,
)
from app.core.database import Base

_CAT_SQL = ", ".join(repr(c.value) for c in InsightCategory)
_PRI_SQL = ", ".join(repr(p.value) for p in InsightPriority)
_STATUS_SQL = ", ".join(repr(s.value) for s in InsightStatus)
_COST_STATUS_SQL = ", ".join(repr(c.value) for c in INSIGHT_COST_ESTIMATE_STATUSES)
_SAVINGS_BASIS_SQL = ", ".join(repr(b.value) for b in InsightSavingsBasis)


class EnergyInsight(Base):
    __tablename__ = "energy_insights"
    __table_args__ = (
        ForeignKeyConstraint(
            ["zone_id", "facility_id"],
            ["zones.id", "zones.facility_id"],
            name="fk_insights_zone_facility",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["meter_id", "facility_id", "zone_id"],
            ["meters.id", "meters.facility_id", "meters.zone_id"],
            name="fk_insights_meter_facility_zone",
            ondelete="RESTRICT",
        ),
        CheckConstraint(f"category IN ({_CAT_SQL})", name="valid_category"),
        CheckConstraint(f"priority IN ({_PRI_SQL})", name="valid_priority"),
        CheckConstraint(f"status IN ({_STATUS_SQL})", name="valid_status"),
        CheckConstraint("monthly_kwh_savings >= 0", name="non_negative_monthly_kwh"),
        CheckConstraint(
            "annual_cost_savings IS NULL OR annual_cost_savings >= 0",
            name="non_negative_annual_cost",
        ),
        CheckConstraint(
            "payback_months IS NULL OR payback_months >= 0",
            name="non_negative_payback",
        ),
        CheckConstraint(f"cost_estimate_status IN ({_COST_STATUS_SQL})", name="valid_cost_status"),
        CheckConstraint(f"savings_basis IN ({_SAVINGS_BASIS_SQL})", name="valid_savings_basis"),
        CheckConstraint(
            "(cost_estimate_status = 'available' AND savings_basis IN ('tariff_arbitrage_only', 'estimated_excess_avoidance') AND annual_cost_savings IS NOT NULL AND annual_cost_savings >= 0) "
            "OR (cost_estimate_status = 'unavailable_tariff' AND savings_basis IN ('tariff_arbitrage_only', 'estimated_excess_avoidance') AND annual_cost_savings IS NULL) "
            "OR (cost_estimate_status = 'not_quantifiable' AND savings_basis = 'unquantified_telemetry' AND annual_cost_savings IS NULL) "
            "OR (cost_estimate_status = 'legacy_unverified' AND savings_basis = 'legacy_migrated' AND annual_cost_savings IS NOT NULL AND annual_cost_savings >= 0)",
            name="consistent_cost_status",
        ),
        Index("ix_insights_facility_zone_status", "facility_id", "zone_id", "status"),
        Index(
            "uq_insights_active_dedupe",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status IN ('Recommended', 'In Progress')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    facility_id: Mapped[str] = mapped_column(String(64), nullable=False)
    zone_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    meter_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rule_code: Mapped[str] = mapped_column(String(48), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    monthly_kwh_savings: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    annual_cost_savings: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    payback_months: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    cost_estimate_status: Mapped[str] = mapped_column(String(24), nullable=False)
    savings_basis: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="Recommended",
        server_default=text("'Recommended'"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InsightWorkflowLog(Base):
    __tablename__ = "insight_workflow_logs"
    __table_args__ = (
        CheckConstraint(
            f"from_status IS NULL OR from_status IN ({_STATUS_SQL})",
            name="valid_from_status",
        ),
        CheckConstraint(f"to_status IN ({_STATUS_SQL})", name="valid_to_status"),
        Index("ix_insight_logs_insight_time", "insight_id", text("changed_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    insight_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("energy_insights.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
