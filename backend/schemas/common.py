"""Common Pydantic schemas."""

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class StatusResponse(BaseModel):
    status: str
    message: str


class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str
    database: str
    timestamp: datetime


class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None
