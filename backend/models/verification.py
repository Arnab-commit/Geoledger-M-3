"""Verification workflow models."""

import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Float, Text, ForeignKey
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship
from backend.database import Base


class VerificationStatus(str, enum.Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    VERIFIED = "verified"
    CORRECTED = "corrected"
    REJECTED = "rejected"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"


class VerificationCase(Base):
    __tablename__ = "verification_cases"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    parcel_id = Column(String, ForeignKey("parcels.id"), nullable=True)
    document_id = Column(String, nullable=True)
    discrepancy_id = Column(String, nullable=True)
    case_type = Column(String(100), nullable=False)
    priority = Column(String(20), default="medium")
    status = Column(SAEnum(VerificationStatus), default=VerificationStatus.PENDING)
    assigned_to = Column(String, nullable=True)
    # Retained legacy SQLite column; keeping it mapped preserves existing rows
    # during PostgreSQL import even though current workflows use assigned_to.
    assigned_officer_id = Column(String(100), nullable=True)
    submitted_by = Column(String, nullable=True)
    state = Column(String(100), nullable=True)
    district = Column(String(100), nullable=True)
    tehsil = Column(String(100), nullable=True)
    village = Column(String(100), nullable=True)
    summary = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    parcel = relationship("Parcel", back_populates="verification_cases")
    actions = relationship("VerificationAction", back_populates="case", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<VerificationCase {self.case_type} ({self.status})>"


class VerificationAction(Base):
    __tablename__ = "verification_actions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("verification_cases.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    action = Column(String(50), nullable=False)
    field_name = Column(String(100), nullable=True)
    original_value = Column(Text, nullable=True)
    corrected_value = Column(Text, nullable=True)
    comment = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)  # Mandatory for Admin Override or Rejection
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    case = relationship("VerificationCase", back_populates="actions")
    user = relationship("User", back_populates="verification_actions")

    def __repr__(self):
        return f"<VerificationAction {self.action} by {self.user_id[:8]}>"
