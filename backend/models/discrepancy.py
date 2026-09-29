"""Discrepancy models."""

import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Float, Text, ForeignKey
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship
from backend.database import Base


class DiscrepancyType(str, enum.Enum):
    OWNER_CONFLICT = "owner_conflict"
    AREA_CONFLICT = "area_conflict"
    IDENTIFIER_CONFLICT = "identifier_conflict"
    DATE_CONFLICT = "date_conflict"
    MUTATION_CONFLICT = "mutation_conflict"
    REGISTRATION_CONFLICT = "registration_conflict"
    BOUNDARY_CONFLICT = "boundary_conflict"
    LOCATION_CONFLICT = "location_conflict"
    MISSING_EVIDENCE = "missing_evidence"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    CHRONOLOGY_CONFLICT = "chronology_conflict"
    GIS_AREA_CONFLICT = "gis_area_conflict"


class Severity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Discrepancy(Base):
    __tablename__ = "discrepancies"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    parcel_id = Column(String, ForeignKey("parcels.id"), nullable=True)
    discrepancy_type = Column(SAEnum(DiscrepancyType), nullable=False)
    severity = Column(SAEnum(Severity), default=Severity.MEDIUM)
    field_name = Column(String(100), nullable=True)
    document_a_id = Column(String, nullable=True)
    document_b_id = Column(String, nullable=True)
    value_a = Column(Text, nullable=True)
    value_b = Column(Text, nullable=True)
    normalized_value_a = Column(Text, nullable=True)
    normalized_value_b = Column(Text, nullable=True)
    similarity_score = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    reason = Column(Text, nullable=True)
    resolution_status = Column(String(50), default="open")
    resolved_by = Column(String, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    parcel = relationship("Parcel", back_populates="discrepancies")
    evidence_items = relationship("Evidence", back_populates="discrepancy")

    def __repr__(self):
        return f"<Discrepancy {self.discrepancy_type} ({self.severity})>"
