from datetime import datetime
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.constants import UserRole
from app.core.security import validate_password_policy


def _normalize_email(value: str) -> str:
    return value.strip().lower()


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def strip_email(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return _normalize_email(str(value))

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Full name cannot be blank.")
        return cleaned

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_policy(value)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(..., min_length=1)

    @field_validator("email", mode="before")
    @classmethod
    def strip_email(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return _normalize_email(str(value))


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserResponse


class UserAdminUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: UserRole | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "UserAdminUpdateRequest":
        if self.role is None and self.is_active is None:
            raise ValueError("At least one of 'role' or 'is_active' must be provided.")
        return self
