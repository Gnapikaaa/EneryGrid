"""Phase 2E analytics schema, cost-availability checks, and deduplication constraints.

Revision ID: 0003_phase2e_analytics
Revises: 0002_soft_deactivation
Create Date: 2026-11-20 02:00:00+00:00

Safety notes:
- Preserves existing anomalies and energy_insights rows without assuming empty tables.
- Pre-existing anomalies receive cost_estimate_status='legacy_unverified' so historical
  estimated_cost=0.00 rows are never falsely marked as tariff-verified ('available').
- Pre-existing energy_insights rows receive cost_estimate_status='legacy_unverified',
  savings_basis='legacy_migrated', deterministic rule_code, and disambiguated active
  dedupe_key values so uq_insights_active_dedupe enforces cleanly without row loss.
- Downgrade drops Phase 2E objects and coerces NULL cost/payback columns to 0.00 before
  restoring 0001/0002 NOT NULL and >= 0 check constraints.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_phase2e_analytics"
down_revision: str | Sequence[str] | None = "0002_soft_deactivation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. telemetry_readings: baseline calculation & retry tracking columns + pending index
    op.add_column(
        "telemetry_readings",
        sa.Column("baseline_computed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "telemetry_readings",
        sa.Column("baseline_last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "telemetry_readings",
        sa.Column(
            "baseline_attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "telemetry_readings",
        sa.Column("baseline_retry_after", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "telemetry_readings",
        sa.Column("baseline_attempt_max_meter_id", sa.BigInteger(), nullable=True),
    )
    op.create_check_constraint(
        "ck_telemetry_readings_non_negative_baseline_attempt_count",
        "telemetry_readings",
        "baseline_attempt_count >= 0",
    )
    op.create_index(
        "ix_telemetry_baseline_pending",
        "telemetry_readings",
        ["meter_id", "recorded_at", "id"],
        unique=False,
        postgresql_where=sa.text(
            "baseline_computed_at IS NULL AND quality_flag = 'valid' AND source <> 'simulation'"
        ),
    )

    # 2. anomalies: fail fast if corrupted duplicate non-null reading_id rows exist
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM anomalies
                WHERE reading_id IS NOT NULL
                GROUP BY reading_id
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION 'Cannot create uq_anomalies_reading_id: duplicate non-null reading_id rows exist in anomalies.';
            END IF;
        END $$;
        """
    )

    op.alter_column(
        "anomalies",
        "estimated_cost",
        existing_type=sa.Numeric(precision=10, scale=2),
        nullable=True,
    )
    op.add_column(
        "anomalies",
        sa.Column("cost_estimate_status", sa.String(length=24), nullable=True),
    )
    op.execute(
        """
        UPDATE anomalies
        SET cost_estimate_status = 'legacy_unverified'
        WHERE cost_estimate_status IS NULL
        """
    )
    op.alter_column(
        "anomalies",
        "cost_estimate_status",
        existing_type=sa.String(length=24),
        nullable=False,
    )
    op.drop_constraint(op.f("ck_anomalies_non_negative_cost"), "anomalies", type_="check")
    op.create_check_constraint(
        "ck_anomalies_non_negative_cost",
        "anomalies",
        "estimated_cost IS NULL OR estimated_cost >= 0",
    )
    op.create_check_constraint(
        "ck_anomalies_valid_cost_status",
        "anomalies",
        "cost_estimate_status IN ('available', 'unavailable_tariff', 'legacy_unverified')",
    )
    op.create_check_constraint(
        "ck_anomalies_consistent_cost_status",
        "anomalies",
        "(cost_estimate_status = 'available' AND estimated_cost IS NOT NULL AND estimated_cost >= 0) "
        "OR (cost_estimate_status = 'unavailable_tariff' AND estimated_cost IS NULL) "
        "OR (cost_estimate_status = 'legacy_unverified' AND estimated_cost IS NOT NULL AND estimated_cost >= 0)",
    )
    op.create_index(
        "uq_anomalies_reading_id",
        "anomalies",
        ["reading_id"],
        unique=True,
        postgresql_where=sa.text("reading_id IS NOT NULL"),
    )

    # 3. energy_insights: meter linkage, nullable financials, cost status, savings basis & dedupe_key
    op.alter_column(
        "energy_insights",
        "payback_months",
        existing_type=sa.Numeric(precision=5, scale=2),
        nullable=True,
    )
    op.drop_constraint(
        op.f("ck_energy_insights_non_negative_payback"), "energy_insights", type_="check"
    )
    op.create_check_constraint(
        "ck_energy_insights_non_negative_payback",
        "energy_insights",
        "payback_months IS NULL OR payback_months >= 0",
    )

    op.alter_column(
        "energy_insights",
        "annual_cost_savings",
        existing_type=sa.Numeric(precision=12, scale=2),
        nullable=True,
    )
    op.drop_constraint(
        op.f("ck_energy_insights_non_negative_annual_cost"), "energy_insights", type_="check"
    )
    op.create_check_constraint(
        "ck_energy_insights_non_negative_annual_cost",
        "energy_insights",
        "annual_cost_savings IS NULL OR annual_cost_savings >= 0",
    )

    op.add_column(
        "energy_insights",
        sa.Column("meter_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "energy_insights",
        sa.Column("rule_code", sa.String(length=48), nullable=True),
    )
    op.add_column(
        "energy_insights",
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "energy_insights",
        sa.Column("cost_estimate_status", sa.String(length=24), nullable=True),
    )
    op.add_column(
        "energy_insights",
        sa.Column("savings_basis", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "energy_insights",
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_foreign_key(
        "fk_insights_meter_facility_zone",
        "energy_insights",
        "meters",
        ["meter_id", "facility_id", "zone_id"],
        ["id", "facility_id", "zone_id"],
        ondelete="RESTRICT",
    )

    # Backfill existing energy_insights rows safely before applying NOT NULL and partial unique index
    op.execute(
        """
        WITH derived AS (
            SELECT
                id,
                LEFT(
                    'LEGACY_' || UPPER(REGEXP_REPLACE(category, '[^A-Za-z0-9]+', '_', 'g')),
                    48
                ) AS derived_rule_code,
                facility_id,
                zone_id,
                meter_id,
                status
            FROM energy_insights
        ),
        ranked AS (
            SELECT
                d.id,
                d.derived_rule_code,
                LEFT(
                    d.derived_rule_code
                    || ':facility=' || d.facility_id
                    || ':zone=' || d.zone_id::text
                    || ':meter=' || COALESCE(d.meter_id::text, 'none'),
                    155
                ) AS canonical_prefix,
                d.derived_rule_code
                || ':facility=' || d.facility_id
                || ':zone=' || d.zone_id::text
                || ':meter=' || COALESCE(d.meter_id::text, 'none') AS canonical_key,
                CASE
                    WHEN d.status IN ('Recommended', 'In Progress') THEN
                        ROW_NUMBER() OVER (
                            PARTITION BY
                                d.derived_rule_code,
                                d.facility_id,
                                d.zone_id,
                                COALESCE(d.meter_id::text, 'none'),
                                (d.status IN ('Recommended', 'In Progress'))
                            ORDER BY ei.updated_at DESC, d.id DESC
                        )
                    ELSE 1
                END AS active_rn
            FROM derived AS d
            JOIN energy_insights AS ei ON ei.id = d.id
        )
        UPDATE energy_insights AS target
        SET
            rule_code = COALESCE(target.rule_code, ranked.derived_rule_code),
            dedupe_key = COALESCE(
                target.dedupe_key,
                CASE
                    WHEN ranked.active_rn = 1 THEN LEFT(ranked.canonical_key, 200)
                    ELSE ranked.canonical_prefix || ':legacy=' || target.id::text
                END
            ),
            cost_estimate_status = COALESCE(target.cost_estimate_status, 'legacy_unverified'),
            savings_basis = COALESCE(target.savings_basis, 'legacy_migrated')
        FROM ranked
        WHERE target.id = ranked.id
        """
    )

    op.alter_column(
        "energy_insights",
        "rule_code",
        existing_type=sa.String(length=48),
        nullable=False,
    )
    op.alter_column(
        "energy_insights",
        "dedupe_key",
        existing_type=sa.String(length=200),
        nullable=False,
    )
    op.alter_column(
        "energy_insights",
        "cost_estimate_status",
        existing_type=sa.String(length=24),
        nullable=False,
    )
    op.alter_column(
        "energy_insights",
        "savings_basis",
        existing_type=sa.String(length=32),
        nullable=False,
    )

    op.create_check_constraint(
        "ck_energy_insights_valid_cost_status",
        "energy_insights",
        "cost_estimate_status IN ('available', 'unavailable_tariff', 'not_quantifiable', 'legacy_unverified')",
    )
    op.create_check_constraint(
        "ck_energy_insights_valid_savings_basis",
        "energy_insights",
        "savings_basis IN ('tariff_arbitrage_only', 'estimated_excess_avoidance', 'unquantified_telemetry', 'legacy_migrated')",
    )
    op.create_check_constraint(
        "ck_energy_insights_consistent_cost_status",
        "energy_insights",
        "(cost_estimate_status = 'available' AND savings_basis IN ('tariff_arbitrage_only', 'estimated_excess_avoidance') AND annual_cost_savings IS NOT NULL AND annual_cost_savings >= 0) "
        "OR (cost_estimate_status = 'unavailable_tariff' AND savings_basis IN ('tariff_arbitrage_only', 'estimated_excess_avoidance') AND annual_cost_savings IS NULL) "
        "OR (cost_estimate_status = 'not_quantifiable' AND savings_basis = 'unquantified_telemetry' AND annual_cost_savings IS NULL) "
        "OR (cost_estimate_status = 'legacy_unverified' AND savings_basis = 'legacy_migrated' AND annual_cost_savings IS NOT NULL AND annual_cost_savings >= 0)",
    )
    op.create_index(
        "uq_insights_active_dedupe",
        "energy_insights",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('Recommended', 'In Progress')"),
    )


def downgrade() -> None:
    # 1. Revert energy_insights additions and restore pre-0003 NOT NULL constraints
    op.drop_index("uq_insights_active_dedupe", table_name="energy_insights")
    op.drop_constraint(
        "ck_energy_insights_consistent_cost_status", "energy_insights", type_="check"
    )
    op.drop_constraint(
        "ck_energy_insights_valid_savings_basis", "energy_insights", type_="check"
    )
    op.drop_constraint(
        "ck_energy_insights_valid_cost_status", "energy_insights", type_="check"
    )
    op.drop_constraint(
        "fk_insights_meter_facility_zone", "energy_insights", type_="foreignkey"
    )
    op.drop_column("energy_insights", "evidence")
    op.drop_column("energy_insights", "savings_basis")
    op.drop_column("energy_insights", "cost_estimate_status")
    op.drop_column("energy_insights", "dedupe_key")
    op.drop_column("energy_insights", "rule_code")
    op.drop_column("energy_insights", "meter_id")

    op.execute(
        """
        UPDATE energy_insights
        SET annual_cost_savings = 0.00
        WHERE annual_cost_savings IS NULL
        """
    )
    op.drop_constraint(
        op.f("ck_energy_insights_non_negative_annual_cost"), "energy_insights", type_="check"
    )
    op.create_check_constraint(
        "ck_energy_insights_non_negative_annual_cost",
        "energy_insights",
        "annual_cost_savings >= 0",
    )
    op.alter_column(
        "energy_insights",
        "annual_cost_savings",
        existing_type=sa.Numeric(precision=12, scale=2),
        nullable=False,
    )

    op.execute(
        """
        UPDATE energy_insights
        SET payback_months = 0.00
        WHERE payback_months IS NULL
        """
    )
    op.drop_constraint(
        "ck_energy_insights_non_negative_payback", "energy_insights", type_="check"
    )
    op.create_check_constraint(
        "ck_energy_insights_non_negative_payback",
        "energy_insights",
        "payback_months >= 0",
    )
    op.alter_column(
        "energy_insights",
        "payback_months",
        existing_type=sa.Numeric(precision=5, scale=2),
        nullable=False,
    )

    # 2. Revert anomalies additions and restore pre-0003 NOT NULL constraints
    op.drop_index("uq_anomalies_reading_id", table_name="anomalies")
    op.drop_constraint("ck_anomalies_consistent_cost_status", "anomalies", type_="check")
    op.drop_constraint("ck_anomalies_valid_cost_status", "anomalies", type_="check")
    op.drop_column("anomalies", "cost_estimate_status")

    op.execute(
        """
        UPDATE anomalies
        SET estimated_cost = 0.00
        WHERE estimated_cost IS NULL
        """
    )
    op.drop_constraint("ck_anomalies_non_negative_cost", "anomalies", type_="check")
    op.create_check_constraint(
        "ck_anomalies_non_negative_cost",
        "anomalies",
        "estimated_cost >= 0",
    )
    op.alter_column(
        "anomalies",
        "estimated_cost",
        existing_type=sa.Numeric(precision=10, scale=2),
        nullable=False,
    )

    # 3. Revert telemetry_readings columns & index
    op.drop_index("ix_telemetry_baseline_pending", table_name="telemetry_readings")
    op.drop_constraint(
        "ck_telemetry_readings_non_negative_baseline_attempt_count",
        "telemetry_readings",
        type_="check",
    )
    op.drop_column("telemetry_readings", "baseline_attempt_max_meter_id")
    op.drop_column("telemetry_readings", "baseline_retry_after")
    op.drop_column("telemetry_readings", "baseline_attempt_count")
    op.drop_column("telemetry_readings", "baseline_last_attempt_at")
    op.drop_column("telemetry_readings", "baseline_computed_at")
