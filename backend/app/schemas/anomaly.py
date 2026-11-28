from datetime import datetime
from decimal import Decimal
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import AnomalySeverity, AnomalyStatus, CostEstimateStatus


def _strip_required_note(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Note must not be blank.")
    return cleaned


def _strip_optional_note(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class AnomalyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_code: str
    facility_id: str
    zone_id: uuid.UUID
    meter_id: uuid.UUID
    reading_id: int | None
    detected_at: datetime
    severity: AnomalySeverity
    status: AnomalyStatus
    z_score: Decimal
    actual_kw: Decimal
    expected_kw: Decimal
    deviation_pct: Decimal
    duration_min: int
    estimated_waste_kwh: Decimal
    estimated_cost: Decimal | None
    cost_estimate_status: CostEstimateStatus
    signature: str
    recommendation: str
    assigned_to_user_id: uuid.UUID | None
    waveform: list[float]
    baseline_waveform: list[float]


class AnomalyDetailResponse(AnomalyResponse):
    pass


class AnomalyWorkflowLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    anomaly_id: uuid.UUID
    from_status: AnomalyStatus | None
    to_status: AnomalyStatus
    from_assignee_id: uuid.UUID | None
    to_assignee_id: uuid.UUID | None
    changed_by_user_id: uuid.UUID | None
    note: str | None
    changed_at: datetime


class AnomalyAcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str | None) -> str | None:
        return _strip_optional_note(value)


class AnomalyInvestigateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_to_user_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str | None) -> str | None:
        return _strip_optional_note(value)


class AnomalyResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(..., min_length=1, max_length=1000)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str) -> str:
        return _strip_required_note(value)


class AnomalyReopenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(..., min_length=1, max_length=1000)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str) -> str:
        return _strip_required_note(value)
