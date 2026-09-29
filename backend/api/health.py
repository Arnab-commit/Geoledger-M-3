"""Health check endpoint."""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.database import get_db
from backend.config import settings
from backend.schemas.common import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/api/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    """System health check."""
    # Test database connection
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        # Health responses are public operational signals; never echo driver
        # errors that can contain host, database or credential details.
        db_status = "unavailable"

    return HealthResponse(
        status="healthy" if db_status == "connected" else "degraded",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        database=db_status,
        timestamp=datetime.now(timezone.utc),
    )
