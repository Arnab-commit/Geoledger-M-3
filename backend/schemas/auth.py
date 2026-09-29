"""Authentication schemas."""

import re
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=256)
    full_name: str = Field(..., min_length=1, max_length=255)
    # Kept only for backward compatibility with older clients. The server
    # rejects privileged role requests and always creates a citizen account.
    role: str | None = None

    @field_validator("username", "full_name", mode="before")
    @classmethod
    def trim_required_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value


class UserLogin(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=256)

    @field_validator("username", mode="before")
    @classmethod
    def trim_identifier(cls, value):
        return value.strip() if isinstance(value, str) else value


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True

    @classmethod
    def model_validate(cls, obj, **kwargs):
        # Handle string is_active and enum/string role
        raw_active = getattr(obj, "is_active", True)
        if isinstance(raw_active, str):
            bool_active = raw_active.lower() in ("true", "1", "yes")
        else:
            bool_active = bool(raw_active)

        raw_role = getattr(obj, "role", "citizen")
        role_str = raw_role.value if hasattr(raw_role, "value") else str(raw_role)

        data = {
            "id": getattr(obj, "id"),
            "username": getattr(obj, "username"),
            "email": getattr(obj, "email"),
            "full_name": getattr(obj, "full_name"),
            "role": role_str.lower(),
            "is_active": bool_active,
            "created_at": getattr(obj, "created_at"),
            "last_login": getattr(obj, "last_login", None),
        }
        return cls(**data)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
