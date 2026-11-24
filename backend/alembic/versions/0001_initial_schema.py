"""Initial EnergyGrid PostgreSQL schema.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-11-19 00:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.constants import SUPPORTED_ISO4217_CURRENCIES

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CURRENCY_SQL_LIST = ", ".join(repr(c) for c in sorted(SUPPORTED_ISO4217_CURRENCIES))


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('admin', 'facility_manager', 'utility_engineer', 'viewer')",
            name=op.f("ck_users_valid_role"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )

    op.create_table(
        "facilities",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("location", sa.String(length=160), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("contracted_demand_kw", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("off_peak_tariff_rate", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("mid_peak_tariff_rate", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("peak_tariff_rate", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"currency_code IN ({_CURRENCY_SQL_LIST})",
            name=op.f("ck_facilities_supported_iso4217_currency"),
        ),
        sa.CheckConstraint(
            "contracted_demand_kw > 0",
            name=op.f("ck_facilities_positive_contracted_demand"),
        ),
        sa.CheckConstraint(
            "off_peak_tariff_rate >= 0",
            name=op.f("ck_facilities_non_negative_off_peak_rate"),
        ),
        sa.CheckConstraint(
            "mid_peak_tariff_rate >= 0",
            name=op.f("ck_facilities_non_negative_mid_peak_rate"),
        ),
        sa.CheckConstraint(
            "peak_tariff_rate >= 0",
            name=op.f("ck_facilities_non_negative_peak_rate"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_facilities")),
        sa.UniqueConstraint("code", name=op.f("uq_facilities_code")),
    )

    op.create_table(
        "zones",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("facility_id", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("primary_meter_code", sa.String(length=32), nullable=False),
        sa.Column("share_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "share_pct >= 0 AND share_pct <= 100",
            name=op.f("ck_zones_valid_share_pct"),
        ),
        sa.CheckConstraint(
            "status IN ('Nominal', 'Warning', 'Fault')",
            name=op.f("ck_zones_valid_zone_status"),
        ),
        sa.ForeignKeyConstraint(
            ["facility_id"],
            ["facilities.id"],
            name=op.f("fk_zones_facility_id_facilities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_zones")),
        sa.UniqueConstraint("facility_id", "slug", name="uq_zones_facility_slug"),
        sa.UniqueConstraint("id", "facility_id", name="uq_zones_id_facility"),
    )
    op.create_index("ix_zones_facility_id", "zones", ["facility_id"], unique=False)

    op.create_table(
        "meters",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("facility_id", sa.String(length=64), nullable=False),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meter_code", sa.String(length=32), nullable=False),
        sa.Column("equipment_name", sa.String(length=160), nullable=False),
        sa.Column("rated_kw", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "nominal_interval_seconds",
            sa.Integer(),
            server_default=sa.text("900"),
            nullable=False,
        ),
        sa.Column(
            "current_kw",
            sa.Numeric(precision=10, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("power_factor", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("thd_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_calibrated_at", sa.Date(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("rated_kw > 0", name=op.f("ck_meters_positive_rated_kw")),
        sa.CheckConstraint(
            "nominal_interval_seconds BETWEEN 60 AND 86400",
            name=op.f("ck_meters_valid_nominal_interval"),
        ),
        sa.CheckConstraint("current_kw >= 0", name=op.f("ck_meters_non_negative_current_kw")),
        sa.CheckConstraint(
            "power_factor >= 0 AND power_factor <= 1",
            name=op.f("ck_meters_valid_power_factor"),
        ),
        sa.CheckConstraint("thd_pct >= 0", name=op.f("ck_meters_non_negative_thd_pct")),
        sa.CheckConstraint(
            "status IN ('Nominal', 'Warning', 'Fault')",
            name=op.f("ck_meters_valid_meter_status"),
        ),
        sa.CheckConstraint(
            "(is_active = true AND deactivated_at IS NULL) OR (is_active = false AND deactivated_at IS NOT NULL)",
            name=op.f("ck_meters_consistent_deactivation_state"),
        ),
        sa.ForeignKeyConstraint(
            ["zone_id", "facility_id"],
            ["zones.id", "zones.facility_id"],
            name="fk_meters_zone_facility",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meters")),
        sa.UniqueConstraint("id", "facility_id", "zone_id", name="uq_meters_id_facility_zone"),
        sa.UniqueConstraint("meter_code", name=op.f("uq_meters_meter_code")),
    )
    op.create_index("ix_meters_facility_active", "meters", ["facility_id", "is_active"], unique=False)
    op.create_index(
        "ix_meters_facility_zone_status",
        "meters",
        ["facility_id", "zone_id", "status"],
        unique=False,
    )

    op.create_table(
        "telemetry_readings",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
        sa.Column("facility_id", sa.String(length=64), nullable=False),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("actual_kw", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("energy_kwh", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("baseline_kw", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("std_dev_kw", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("z_score", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("baseline_status", sa.String(length=24), nullable=False),
        sa.Column("power_factor", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("tariff_period", sa.String(length=16), nullable=False),
        sa.Column("ambient_temp_c", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column(
            "quality_flag",
            sa.String(length=24),
            server_default=sa.text("'valid'"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=24),
            server_default=sa.text("'meter_feed'"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "interval_seconds BETWEEN 60 AND 86400",
            name=op.f("ck_telemetry_readings_valid_interval_seconds"),
        ),
        sa.CheckConstraint(
            "interval_start = recorded_at - make_interval(secs => interval_seconds)",
            name=op.f("ck_telemetry_readings_consistent_interval_bounds"),
        ),
        sa.CheckConstraint(
            "actual_kw >= 0",
            name=op.f("ck_telemetry_readings_non_negative_actual_kw"),
        ),
        sa.CheckConstraint(
            "energy_kwh >= 0",
            name=op.f("ck_telemetry_readings_non_negative_energy_kwh"),
        ),
        sa.CheckConstraint(
            "power_factor >= 0 AND power_factor <= 1",
            name=op.f("ck_telemetry_readings_valid_power_factor"),
        ),
        sa.CheckConstraint(
            "tariff_period IN ('Peak', 'Mid-Peak', 'Off-Peak')",
            name=op.f("ck_telemetry_readings_valid_tariff_period"),
        ),
        sa.CheckConstraint(
            "baseline_status IN ('ready', 'insufficient_history')",
            name=op.f("ck_telemetry_readings_valid_baseline_status"),
        ),
        sa.CheckConstraint(
            "quality_flag IN ('valid', 'gap_bounded', 'simulated')",
            name=op.f("ck_telemetry_readings_valid_quality_flag"),
        ),
        sa.CheckConstraint(
            "source IN ('meter_feed', 'csv_import', 'seed', 'simulation')",
            name=op.f("ck_telemetry_readings_valid_source"),
        ),
        sa.ForeignKeyConstraint(
            ["meter_id", "facility_id", "zone_id"],
            ["meters.id", "meters.facility_id", "meters.zone_id"],
            name="fk_telemetry_meter_facility_zone",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telemetry_readings")),
        sa.UniqueConstraint("id", "meter_id", name="uq_telemetry_id_meter"),
        sa.UniqueConstraint("meter_id", "recorded_at", name="uq_telemetry_meter_recorded_at"),
    )
    op.execute(
        """
        ALTER TABLE telemetry_readings
        ADD CONSTRAINT ex_telemetry_no_overlapping_intervals
        EXCLUDE USING gist (
            meter_id WITH =,
            tstzrange(interval_start, recorded_at, '[)') WITH &&
        )
        """
    )
    op.create_index(
        "ix_telemetry_facility_time",
        "telemetry_readings",
        ["facility_id", sa.text("recorded_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_zone_time",
        "telemetry_readings",
        ["zone_id", sa.text("recorded_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_telemetry_zscore_high",
        "telemetry_readings",
        ["facility_id", sa.text("z_score DESC")],
        unique=False,
        postgresql_where=sa.text("baseline_status = 'ready' AND z_score >= 1.5"),
    )

    op.create_table(
        "anomalies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("event_code", sa.String(length=32), nullable=False),
        sa.Column("facility_id", sa.String(length=64), nullable=False),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reading_id", sa.BigInteger(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'Open'"),
            nullable=False,
        ),
        sa.Column("z_score", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("actual_kw", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("expected_kw", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("deviation_pct", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("estimated_waste_kwh", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("estimated_cost", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("waveform", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("baseline_waveform", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "severity IN ('Critical', 'High', 'Elevated')",
            name=op.f("ck_anomalies_valid_severity"),
        ),
        sa.CheckConstraint(
            "status IN ('Open', 'Acknowledged', 'Assigned', 'Resolved')",
            name=op.f("ck_anomalies_valid_status"),
        ),
        sa.CheckConstraint("duration_min > 0", name=op.f("ck_anomalies_positive_duration_min")),
        sa.CheckConstraint(
            "estimated_waste_kwh >= 0",
            name=op.f("ck_anomalies_non_negative_waste_kwh"),
        ),
        sa.CheckConstraint(
            "estimated_cost >= 0",
            name=op.f("ck_anomalies_non_negative_cost"),
        ),
        sa.CheckConstraint(
            "(status <> 'Assigned') OR (assigned_to_user_id IS NOT NULL)",
            name=op.f("ck_anomalies_assigned_requires_user"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to_user_id"],
            ["users.id"],
            name=op.f("fk_anomalies_assigned_to_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["meter_id", "facility_id", "zone_id"],
            ["meters.id", "meters.facility_id", "meters.zone_id"],
            name="fk_anomalies_meter_facility_zone",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_anomalies")),
        sa.UniqueConstraint("event_code", name=op.f("uq_anomalies_event_code")),
    )
    # PostgreSQL 15 column-scoped ON DELETE SET NULL preserves meter_id (NOT NULL)
    op.execute(
        """
        ALTER TABLE anomalies
        ADD CONSTRAINT fk_anomalies_reading_meter
        FOREIGN KEY (reading_id, meter_id)
        REFERENCES telemetry_readings (id, meter_id)
        ON DELETE SET NULL (reading_id)
        """
    )
    op.create_index(
        "ix_anomalies_facility_status_z",
        "anomalies",
        ["facility_id", "status", sa.text("z_score DESC")],
        unique=False,
    )
    op.create_index(
        "ix_anomalies_zone_detected",
        "anomalies",
        ["zone_id", sa.text("detected_at DESC")],
        unique=False,
    )

    op.create_table(
        "anomaly_workflow_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("anomaly_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=False),
        sa.Column("from_assignee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("to_assignee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("changed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('Open', 'Acknowledged', 'Assigned', 'Resolved')",
            name=op.f("ck_anomaly_workflow_logs_valid_from_status"),
        ),
        sa.CheckConstraint(
            "to_status IN ('Open', 'Acknowledged', 'Assigned', 'Resolved')",
            name=op.f("ck_anomaly_workflow_logs_valid_to_status"),
        ),
        sa.ForeignKeyConstraint(
            ["anomaly_id"],
            ["anomalies.id"],
            name=op.f("fk_anomaly_workflow_logs_anomaly_id_anomalies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_user_id"],
            ["users.id"],
            name=op.f("fk_anomaly_workflow_logs_changed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["from_assignee_id"],
            ["users.id"],
            name=op.f("fk_anomaly_workflow_logs_from_assignee_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["to_assignee_id"],
            ["users.id"],
            name=op.f("fk_anomaly_workflow_logs_to_assignee_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_anomaly_workflow_logs")),
    )
    op.create_index(
        "ix_anomaly_logs_anomaly_time",
        "anomaly_workflow_logs",
        ["anomaly_id", sa.text("changed_at DESC")],
        unique=False,
    )

    op.create_table(
        "energy_insights",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("facility_id", sa.String(length=64), nullable=False),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("monthly_kwh_savings", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("annual_cost_savings", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("payback_months", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'Recommended'"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('Load Shifting', 'Power Quality', 'HVAC & Thermal', 'Compressed Air')",
            name=op.f("ck_energy_insights_valid_category"),
        ),
        sa.CheckConstraint(
            "priority IN ('High', 'Medium')",
            name=op.f("ck_energy_insights_valid_priority"),
        ),
        sa.CheckConstraint(
            "status IN ('Recommended', 'In Progress', 'Implemented')",
            name=op.f("ck_energy_insights_valid_status"),
        ),
        sa.CheckConstraint(
            "monthly_kwh_savings >= 0",
            name=op.f("ck_energy_insights_non_negative_monthly_kwh"),
        ),
        sa.CheckConstraint(
            "annual_cost_savings >= 0",
            name=op.f("ck_energy_insights_non_negative_annual_cost"),
        ),
        sa.CheckConstraint(
            "payback_months >= 0",
            name=op.f("ck_energy_insights_non_negative_payback"),
        ),
        sa.ForeignKeyConstraint(
            ["zone_id", "facility_id"],
            ["zones.id", "zones.facility_id"],
            name="fk_insights_zone_facility",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_energy_insights")),
    )
    op.create_index(
        "ix_insights_facility_zone_status",
        "energy_insights",
        ["facility_id", "zone_id", "status"],
        unique=False,
    )

    op.create_table(
        "insight_workflow_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("insight_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("changed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('Recommended', 'In Progress', 'Implemented')",
            name=op.f("ck_insight_workflow_logs_valid_from_status"),
        ),
        sa.CheckConstraint(
            "to_status IN ('Recommended', 'In Progress', 'Implemented')",
            name=op.f("ck_insight_workflow_logs_valid_to_status"),
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_user_id"],
            ["users.id"],
            name=op.f("fk_insight_workflow_logs_changed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["insight_id"],
            ["energy_insights.id"],
            name=op.f("fk_insight_workflow_logs_insight_id_energy_insights"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_insight_workflow_logs")),
    )
    op.create_index(
        "ix_insight_logs_insight_time",
        "insight_workflow_logs",
        ["insight_id", sa.text("changed_at DESC")],
        unique=False,
    )

    op.create_table(
        "meter_calibration_audits",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("meter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audited_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("audited_on", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["audited_by_user_id"],
            ["users.id"],
            name=op.f("fk_meter_calibration_audits_audited_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["meter_id"],
            ["meters.id"],
            name=op.f("fk_meter_calibration_audits_meter_id_meters"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meter_calibration_audits")),
    )
    op.create_index(
        "ix_meter_audits_meter_date",
        "meter_calibration_audits",
        ["meter_id", sa.text("audited_on DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_meter_audits_meter_date", table_name="meter_calibration_audits")
    op.drop_table("meter_calibration_audits")

    op.drop_index("ix_insight_logs_insight_time", table_name="insight_workflow_logs")
    op.drop_table("insight_workflow_logs")

    op.drop_index("ix_insights_facility_zone_status", table_name="energy_insights")
    op.drop_table("energy_insights")

    op.drop_index("ix_anomaly_logs_anomaly_time", table_name="anomaly_workflow_logs")
    op.drop_table("anomaly_workflow_logs")

    op.drop_index("ix_anomalies_zone_detected", table_name="anomalies")
    op.drop_index("ix_anomalies_facility_status_z", table_name="anomalies")
    op.drop_table("anomalies")

    op.drop_index("ix_telemetry_zscore_high", table_name="telemetry_readings")
    op.drop_index("ix_telemetry_zone_time", table_name="telemetry_readings")
    op.drop_index("ix_telemetry_facility_time", table_name="telemetry_readings")
    op.drop_table("telemetry_readings")

    op.drop_index("ix_meters_facility_zone_status", table_name="meters")
    op.drop_index("ix_meters_facility_active", table_name="meters")
    op.drop_table("meters")

    op.drop_index("ix_zones_facility_id", table_name="zones")
    op.drop_table("zones")

    op.drop_table("facilities")
    op.drop_table("users")
