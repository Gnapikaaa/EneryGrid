from datetime import datetime
from decimal import Decimal
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import (
    CostEstimateStatus,
    InsightCategory,
    InsightPriority,
    InsightRuleCode,
    InsightSavingsBasis,
    InsightStatus,
)


def _clean_optional_note(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class InsightResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    facility_id: str
    zone_id: uuid.UUID
    meter_id: uuid.UUID | None
    rule_code: InsightRuleCode
    dedupe_key: str
    title: str
    category: InsightCategory
    summary: str
    monthly_kwh_savings: Decimal
    annual_cost_savings: Decimal | None
    payback_months: Decimal | None
    cost_estimate_status: CostEstimateStatus
    savings_basis: InsightSavingsBasis
    priority: InsightPriority
    status: InsightStatus
    updated_at: datetime


class InsightDetailResponse(InsightResponse):
    evidence: dict[str, Any] | None


class InsightWorkflowLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    insight_id: uuid.UUID
    from_status: InsightStatus | None
    to_status: InsightStatus
    changed_by_user_id: uuid.UUID | None
    note: str | None
    changed_at: datetime


class InsightStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: InsightStatus
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str | None) -> str | None:
        return _clean_optional_note(value)
