"""Add soft-deactivation columns and constraints to facilities and zones.

Revision ID: 0002_soft_deactivation
Revises: 0001_initial_schema
Create Date: 2026-11-19 10:20:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_soft_deactivation"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "facilities",
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "facilities",
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_facilities_consistent_deactivation_state",
        "facilities",
        "(is_active = true AND deactivated_at IS NULL) OR (is_active = false AND deactivated_at IS NOT NULL)",
    )
    op.create_index("ix_facilities_is_active", "facilities", ["is_active"], unique=False)

    op.add_column(
        "zones",
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "zones",
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_zones_consistent_deactivation_state",
        "zones",
        "(is_active = true AND deactivated_at IS NULL) OR (is_active = false AND deactivated_at IS NOT NULL)",
    )
    op.create_index(
        "ix_zones_facility_active",
        "zones",
        ["facility_id", "is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_zones_facility_active", table_name="zones")
    op.drop_constraint("ck_zones_consistent_deactivation_state", "zones", type_="check")
    op.drop_column("zones", "deactivated_at")
    op.drop_column("zones", "is_active")

    op.drop_index("ix_facilities_is_active", table_name="facilities")
    op.drop_constraint(
        "ck_facilities_consistent_deactivation_state", "facilities", type_="check"
    )
    op.drop_column("facilities", "deactivated_at")
    op.drop_column("facilities", "is_active")
